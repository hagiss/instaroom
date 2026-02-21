"""Dual-viewpoint room image generation with self-critique loop.

Uses a SINGLE multi-turn chat session to generate both forward and backward
room images sequentially. This ensures geometric consistency — the model
remembers the room it created for the forward view when generating the backward view.

Max 2 attempts per viewpoint (1 round of critique each).
"""

from __future__ import annotations

import asyncio
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
    DualImageGenResult,
    GenerationAttempt,
    ImageGenPrompt,
    ImageGenResult,
)

logger = logging.getLogger(__name__)

_CRITIQUE_THRESHOLD = 3.5
_MAX_ATTEMPTS = 2

_BACKWARD_TRANSITION = (
    "Now turn the camera 180° to face the opposite direction. "
    "The room you just created continues behind you — same walls, same floor, "
    "same style and lighting. You are now looking at the other half of the room. "
    "Generate this backward view:\n\n"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_dual_room_images(
    forward_prompt: ImageGenPrompt,
    backward_prompt: ImageGenPrompt | None,
    profile: AggregatedProfile,
) -> DualImageGenResult:
    """Generate forward (and optionally backward) room images.

    When backward_prompt is None, only the forward view is generated and
    backward is returned as an empty ImageGenResult.

    When backward_prompt is provided, both views are generated in a single
    multi-turn chat session for geometric consistency.
    """
    # Download reference images (parallel if both views needed)
    if backward_prompt is not None:
        fwd_ref_images, bwd_ref_images = await asyncio.gather(
            _download_reference_images(forward_prompt.reference_image_urls),
            _download_reference_images(backward_prompt.reference_image_urls),
        )
    else:
        fwd_ref_images = await _download_reference_images(
            forward_prompt.reference_image_urls,
        )

    # Create a single multi-turn chat session
    client = get_gemini_client()
    chat = client.aio.chats.create(
        model=IMAGE_GEN_MODEL,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9",
                image_size="4K",
            ),
        ),
    )

    # --- Forward view ---
    logger.info("Generating forward view")
    forward_result = await _generate_single_view(
        chat=chat,
        prompt_data=forward_prompt,
        profile=profile,
        ref_images=fwd_ref_images,
        view_label="forward",
        transition_prefix=None,
    )

    # --- Backward view ---
    if backward_prompt is not None:
        logger.info("Generating backward view (same chat session)")
        backward_result = await _generate_single_view(
            chat=chat,
            prompt_data=backward_prompt,
            profile=profile,
            ref_images=bwd_ref_images,
            view_label="backward",
            transition_prefix=_BACKWARD_TRANSITION,
        )
    else:
        logger.info("Backward view skipped (single-view mode)")
        backward_result = ImageGenResult()

    return DualImageGenResult(
        forward=forward_result,
        backward=backward_result,
    )


# ---------------------------------------------------------------------------
# Single-view generation (used for both forward and backward)
# ---------------------------------------------------------------------------

async def _generate_single_view(
    chat: types.AsyncChat,
    prompt_data: ImageGenPrompt,
    profile: AggregatedProfile,
    ref_images: list[Image.Image],
    view_label: str,
    transition_prefix: str | None,
) -> ImageGenResult:
    """Generate a single viewpoint with critique-driven refinement.

    Up to _MAX_ATTEMPTS turns in the chat for this viewpoint.
    """
    attempts: list[GenerationAttempt] = []
    best_attempt: GenerationAttempt | None = None

    for attempt_num in range(1, _MAX_ATTEMPTS + 1):
        if attempt_num == 1:
            # First attempt: send reference images + prompt
            prompt_text = prompt_data.final_prompt
            if transition_prefix:
                prompt_text = transition_prefix + prompt_text

            message: list = []
            for img in ref_images:
                message.append(img)
            message.append(prompt_text)
        else:
            # Refinement: send critique feedback
            prompt_text = _build_refinement_message(
                best_attempt.critique if best_attempt else None,
            )
            message = [prompt_text]

        # Generate image via chat turn
        image_b64 = await _chat_generate(chat, message)
        if not image_b64:
            logger.error(
                "%s view: image generation failed on attempt %d",
                view_label, attempt_num,
            )
            attempts.append(GenerationAttempt(
                attempt_number=attempt_num,
                prompt_used=prompt_text if isinstance(prompt_text, str) else str(prompt_text),
            ))
            continue

        # Critique — only against THIS view's objects
        critique = await _critique_image(image_b64, prompt_data, profile)

        attempt = GenerationAttempt(
            attempt_number=attempt_num,
            image_base64=image_b64,
            critique=critique,
            prompt_used=prompt_text if isinstance(prompt_text, str) else str(prompt_text),
        )
        attempts.append(attempt)

        if best_attempt is None or (
            critique is not None and (
                best_attempt.critique is None
                or critique.avg_score > best_attempt.critique.avg_score
            )
        ):
            best_attempt = attempt

        if critique is None:
            # Critique call failed (e.g. 503) — accept the image as-is
            logger.warning(
                "%s view attempt %d: critique failed, accepting image",
                view_label, attempt_num,
            )
            break

        if critique.avg_score >= _CRITIQUE_THRESHOLD:
            logger.info(
                "%s view attempt %d scored %.2f (>= %.1f), stopping",
                view_label, attempt_num, critique.avg_score, _CRITIQUE_THRESHOLD,
            )
            break

        if attempt_num < _MAX_ATTEMPTS:
            logger.info(
                "%s view attempt %d scored %.2f (< %.1f), will retry",
                view_label, attempt_num, critique.avg_score, _CRITIQUE_THRESHOLD,
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
**Key objects that should be present in this view**: {objects}

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
    """Critique a generated image with Gemini Flash.

    Uses the per-view object list (prompt_data.object_details) so each view
    is only judged on its own objects, not the full profile.
    """
    image_bytes = base64.b64decode(image_b64)

    # Per-view critique: use this view's object details, not the full profile
    objects_list = ", ".join(od.name for od in prompt_data.object_details)

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
