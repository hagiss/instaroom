"""Room image generation and self-critique loop.

Generates room image via image generation model, then runs VLM critique.
Retries once with prompt adjustments based on critique scores.
Max 2 attempts total (1 round of critique).
"""

from __future__ import annotations

import base64
import io
import logging

from google.genai import types
from PIL import Image

from app.services.gemini_client import (
    FLASH_MODEL,
    IMAGE_GEN_MODEL,
    download_images,
    get_gemini_client,
)
from app.services.models import (
    AggregatedProfile,
    CritiqueScores,
    GenerationAttempt,
    ImageGenPrompt,
    ImageGenResult,
)

logger = logging.getLogger(__name__)

_CRITIQUE_THRESHOLD = 3.5
_MAX_ATTEMPTS = 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_room_image(
    prompt_data: ImageGenPrompt,
    profile: AggregatedProfile,
) -> ImageGenResult:
    """Generate a room image with optional critique-driven retry.

    1. Download reference images
    2. Generate image (attempt 1)
    3. Critique with VLM
    4. If avg score < 3.5, adjust prompt and regenerate (attempt 2)
    5. Return best attempt
    """
    # Download reference images once
    ref_pil_images = await _download_reference_images(prompt_data.reference_image_urls)

    attempts: list[GenerationAttempt] = []
    best_attempt: GenerationAttempt | None = None

    for attempt_num in range(1, _MAX_ATTEMPTS + 1):
        # Build prompt text
        if attempt_num == 1:
            prompt_text = prompt_data.final_prompt
        else:
            # Adjust prompt based on previous critique
            prompt_text = _build_adjusted_prompt(
                prompt_data.final_prompt,
                best_attempt.critique if best_attempt else None,
            )

        # Generate image
        image_b64 = await _generate_image(prompt_text, ref_pil_images)
        if not image_b64:
            logger.error("Image generation failed on attempt %d", attempt_num)
            attempts.append(GenerationAttempt(
                attempt_number=attempt_num,
                prompt_used=prompt_text,
            ))
            continue

        # Critique the generated image
        critique = await _critique_image(image_b64, prompt_data, profile)

        attempt = GenerationAttempt(
            attempt_number=attempt_num,
            image_base64=image_b64,
            critique=critique,
            prompt_used=prompt_text,
        )
        attempts.append(attempt)

        # Track best attempt: prefer critiqued over uncritiqued, then higher score
        if best_attempt is None or (
            critique is not None and (
                best_attempt.critique is None
                or critique.avg_score > best_attempt.critique.avg_score
            )
        ):
            best_attempt = attempt

        # Check if good enough to stop
        if critique and critique.avg_score >= _CRITIQUE_THRESHOLD:
            logger.info(
                "Attempt %d scored %.2f (>= %.1f), stopping",
                attempt_num, critique.avg_score, _CRITIQUE_THRESHOLD,
            )
            break

        if attempt_num < _MAX_ATTEMPTS:
            logger.info(
                "Attempt %d scored %.2f (< %.1f), will retry",
                attempt_num,
                critique.avg_score if critique else 0,
                _CRITIQUE_THRESHOLD,
            )

    if best_attempt is None:
        best_attempt = attempts[-1] if attempts else GenerationAttempt(attempt_number=0)

    return ImageGenResult(
        final_image_base64=best_attempt.image_base64,
        final_critique=best_attempt.critique,
        attempts=attempts,
        total_attempts=len(attempts),
    )


# ---------------------------------------------------------------------------
# Reference image download
# ---------------------------------------------------------------------------

async def _download_reference_images(urls: list[str]) -> list[Image.Image]:
    """Download and convert reference images to PIL Image objects."""
    if not urls:
        return []

    raw_images = await download_images(urls)
    pil_images: list[Image.Image] = []
    for raw in raw_images:
        if raw is not None:
            try:
                pil_images.append(Image.open(io.BytesIO(raw)))
            except Exception:
                logger.warning("Failed to open reference image as PIL", exc_info=True)
    return pil_images


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

async def _generate_image(
    prompt_text: str,
    ref_images: list[Image.Image],
) -> str | None:
    """Call image generation model and return base64-encoded image."""
    client = get_gemini_client()

    # Build contents: reference images + text prompt
    contents: list = []
    for img in ref_images:
        contents.append(img)
    contents.append(prompt_text)

    try:
        response = await client.aio.models.generate_content(
            model=IMAGE_GEN_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_generation_config=types.ImageGenerationConfig(
                    aspect_ratio="16:9",
                ),
            ),
        )
    except Exception:
        logger.error("Image generation API call failed", exc_info=True)
        return None

    # Extract image from response
    if not response.candidates:
        logger.warning("No candidates in image generation response")
        return None

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            return base64.b64encode(part.inline_data.data).decode("utf-8")

    logger.warning("No image data in generation response")
    return None


# ---------------------------------------------------------------------------
# Critique
# ---------------------------------------------------------------------------

_CRITIQUE_PROMPT = """\
You are a professional art critic evaluating a generated room image. The image was \
generated to represent a specific person's ideal room.

**Persona**: {persona}
**Target atmosphere**: mood={mood}, lighting={lighting}, style={style}
**Key objects that should be present**: {objects}

Score the image on these 4 dimensions (1-4 scale, where 4 is excellent):

1. object_presence: Are the key personal objects visible and recognizable?
2. atmosphere_match: Does the mood, lighting, and color palette match the target?
3. spatial_coherence: Is the room layout realistic and well-composed?
4. overall_quality: Overall visual quality and appeal of the image

For each dimension, provide a score (1-4) and brief feedback explaining why.
"""


async def _critique_image(
    image_b64: str,
    prompt_data: ImageGenPrompt,
    profile: AggregatedProfile,
) -> CritiqueScores | None:
    """Critique a generated image with Gemini Flash."""
    image_bytes = base64.b64decode(image_b64)

    objects_list = ", ".join(o.name for o in profile.key_objects)

    prompt = _CRITIQUE_PROMPT.format(
        persona=profile.persona_summary,
        mood=profile.atmosphere.dominant_mood,
        lighting=profile.atmosphere.dominant_lighting,
        style=profile.atmosphere.style,
        objects=objects_list or "(none specified)",
    )

    parts: list[types.Part] = [
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        types.Part.from_text(text=prompt),
    ]

    client = get_gemini_client()
    try:
        response = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CritiqueScores,
                temperature=0.2,
            ),
        )
    except Exception:
        logger.error("Critique API call failed", exc_info=True)
        return None

    raw = response.text
    if not raw:
        logger.warning("Empty critique response")
        return None

    return CritiqueScores.model_validate_json(raw)


# ---------------------------------------------------------------------------
# Prompt adjustment
# ---------------------------------------------------------------------------

def _build_adjusted_prompt(
    original_prompt: str,
    critique: CritiqueScores | None,
) -> str:
    """Append critical adjustments to the original prompt based on critique."""
    if not critique:
        return original_prompt

    adjustments: list[str] = []

    if critique.object_presence < 3:
        adjustments.append(
            f"CRITICAL: Make all personal objects more visible and prominent. "
            f"Issue: {critique.object_presence_feedback}"
        )
    if critique.atmosphere_match < 3:
        adjustments.append(
            f"CRITICAL: Adjust mood, lighting and colors to better match target. "
            f"Issue: {critique.atmosphere_match_feedback}"
        )
    if critique.spatial_coherence < 3:
        adjustments.append(
            f"CRITICAL: Fix spatial layout for realism. "
            f"Issue: {critique.spatial_coherence_feedback}"
        )
    if critique.overall_quality < 3:
        adjustments.append(
            f"CRITICAL: Improve overall visual quality. "
            f"Issue: {critique.overall_quality_feedback}"
        )

    if not adjustments:
        # All scores >= 3 but average < threshold, general improvement
        adjustments.append(
            "Improve overall quality: make objects sharper, lighting more natural, "
            "and composition more compelling."
        )

    return f"{original_prompt}\n\n[CRITICAL ADJUSTMENTS]\n" + "\n".join(adjustments)
