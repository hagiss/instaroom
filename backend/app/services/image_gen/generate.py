"""Room image generation and self-critique loop.

Uses multi-turn chat for image generation so the model can iteratively
refine its output based on critique feedback.
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
    """Generate a room image with multi-turn critique-driven refinement.

    1. Download reference images
    2. Create a chat session with the image gen model
    3. Turn 1: generate image from prompt + reference images
    4. Critique with Gemini Flash
    5. If avg score < 3.5, Turn 2: send critique feedback to same chat for refinement
    6. Return best attempt
    """
    # Download reference images once
    ref_pil_images = await _download_reference_images(prompt_data.reference_image_urls)

    # Create multi-turn chat session
    client = get_gemini_client()
    chat = client.aio.chats.create(
        model=IMAGE_GEN_MODEL,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9",
            ),
        ),
    )

    attempts: list[GenerationAttempt] = []
    best_attempt: GenerationAttempt | None = None

    for attempt_num in range(1, _MAX_ATTEMPTS + 1):
        if attempt_num == 1:
            # Turn 1: reference images + prompt
            prompt_text = prompt_data.final_prompt
            message: list = []
            for img in ref_pil_images:
                message.append(img)
            message.append(prompt_text)
        else:
            # Turn 2: send critique feedback — the chat remembers the previous image
            prompt_text = _build_refinement_message(
                best_attempt.critique if best_attempt else None,
            )
            message = [prompt_text]

        # Generate image via chat turn
        image_b64 = await _chat_generate(chat, message)
        if not image_b64:
            logger.error("Image generation failed on attempt %d", attempt_num)
            attempts.append(GenerationAttempt(
                attempt_number=attempt_num,
                prompt_used=prompt_text if isinstance(prompt_text, str) else str(prompt_text),
            ))
            continue

        # Critique the generated image with Gemini Flash
        critique = await _critique_image(image_b64, prompt_data, profile)

        attempt = GenerationAttempt(
            attempt_number=attempt_num,
            image_base64=image_b64,
            critique=critique,
            prompt_used=prompt_text if isinstance(prompt_text, str) else str(prompt_text),
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
                "Attempt %d scored %.2f (< %.1f), will retry with feedback",
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
# Multi-turn image generation
# ---------------------------------------------------------------------------

async def _chat_generate(
    chat: types.AsyncChat,
    message: list,
) -> str | None:
    """Send a message in the chat and extract the generated image."""
    try:
        response = await chat.send_message(message)
    except Exception:
        logger.error("Image generation chat call failed", exc_info=True)
        return None

    # Extract image from response parts
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
# Refinement message
# ---------------------------------------------------------------------------

def _build_refinement_message(critique: CritiqueScores | None) -> str:
    """Build a refinement message from critique feedback for the next chat turn."""
    if not critique:
        return (
            "The previous image needs improvement. Please regenerate with "
            "better overall quality, sharper objects, and more natural lighting."
        )

    issues: list[str] = []

    if critique.object_presence < 3:
        issues.append(
            f"Objects are not visible enough: {critique.object_presence_feedback}"
        )
    if critique.atmosphere_match < 3:
        issues.append(
            f"Atmosphere doesn't match: {critique.atmosphere_match_feedback}"
        )
    if critique.spatial_coherence < 3:
        issues.append(
            f"Spatial layout issues: {critique.spatial_coherence_feedback}"
        )
    if critique.overall_quality < 3:
        issues.append(
            f"Quality issues: {critique.overall_quality_feedback}"
        )

    if not issues:
        issues.append(
            "Overall quality could be better — make objects sharper, "
            "lighting more natural, and composition more compelling."
        )

    feedback = "\n".join(f"- {issue}" for issue in issues)
    return (
        f"Please refine the previous image. Keep what works well but fix these issues:\n"
        f"{feedback}\n\n"
        f"Do not change the overall room layout or style — only improve the weak areas."
    )
