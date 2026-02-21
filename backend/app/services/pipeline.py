"""Pipeline orchestrator: runs Stages 1-5 sequentially and saves debug output."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone

from app.services.image_gen.generate import generate_dual_room_images
from app.services.models import (
    AggregatedProfile,
    ConvertToSceneResult,
    DualImageGenResult,
    ImageGenPrompt,
    ImageGenResult,
    PostAnalysisWithMeta,
    ScrapeResult,
)
from app.services.vlm.aggregation import aggregate_analyses
from app.services.vlm.analysis import analyze_posts
from app.services.vlm.prompt import design_prompt
from app.services.worldslabs import (
    ConvertToSceneRequest,
    WorldLabsError,
    convert_to_3d_scene,
    generate_3d_prompt,
)
from app.services.worldslabs.config import MarbleModel, get_api_key as _get_worldlabs_key

logger = logging.getLogger(__name__)


async def run_pipeline(
    crawl_result: ScrapeResult,
    output_dir: str = "output",
    run_3d_conversion: bool = False,
    dual_view: bool = True,
) -> tuple[DualImageGenResult, AggregatedProfile, ConvertToSceneResult | None]:
    """Run the full VLM pipeline: Stage 1 → 2 → 3 → 4 → 5.

    Returns the dual image generation result, the aggregated profile,
    and the 3D scene conversion result (None if skipped or failed).
    All intermediate results are saved to a debug JSON file.
    """
    username = crawl_result.profile.username

    # Stage 1: Per-post analysis
    logger.info("Stage 1: Analyzing %d posts for @%s", len(crawl_result.posts), username)
    analyses = await analyze_posts(crawl_result.posts)
    if not analyses:
        raise ValueError(
            f"No posts could be analyzed for @{username}. "
            "Check that posts have valid image URLs."
        )
    logger.info("Stage 1 complete: %d/%d posts analyzed", len(analyses), len(crawl_result.posts))

    # Stage 2: Aggregation
    logger.info("Stage 2: Aggregating analyses into persona profile")
    profile = await aggregate_analyses(analyses, crawl_result.profile)
    logger.info("Stage 2 complete: %d key objects, style=%s", len(profile.key_objects), profile.atmosphere.style)

    # Stage 3: Prompt design (returns forward + optional backward prompts)
    logger.info("Stage 3: Designing %s image generation prompts", "dual" if dual_view else "single")
    forward_prompt, backward_prompt = await design_prompt(profile, dual_view=dual_view)
    if backward_prompt is not None:
        logger.info(
            "Stage 3 complete: forward prompt=%d chars (%d refs), backward prompt=%d chars (%d refs)",
            len(forward_prompt.final_prompt), len(forward_prompt.reference_image_urls),
            len(backward_prompt.final_prompt), len(backward_prompt.reference_image_urls),
        )
    else:
        logger.info(
            "Stage 3 complete: single-view prompt=%d chars (%d refs)",
            len(forward_prompt.final_prompt), len(forward_prompt.reference_image_urls),
        )

    # Stage 4: Image generation + critique
    logger.info("Stage 4: Generating %s room images", "dual (forward + backward)" if backward_prompt else "single")
    result = await generate_dual_room_images(forward_prompt, backward_prompt, profile)
    logger.info(
        "Stage 4 complete: forward=%d attempts (score=%.2f), backward=%d attempts (score=%.2f)",
        result.forward.total_attempts,
        result.forward.final_critique.avg_score if result.forward.final_critique else 0,
        result.backward.total_attempts,
        result.backward.final_critique.avg_score if result.backward.final_critique else 0,
    )

    # Generate 3D spatial prompt (always, for debug output)
    text_prompt_3d: str | None = None
    has_any_image = result.forward.final_image_base64 or result.backward.final_image_base64
    if has_any_image:
        text_prompt_3d = await generate_3d_prompt(profile, forward_prompt)
        logger.info("3D spatial prompt generated (%d chars)", len(text_prompt_3d))

    # Stage 5: 3D conversion via World Labs Marble
    scene_result: ConvertToSceneResult | None = None
    has_both_images = result.forward.final_image_base64 and result.backward.final_image_base64

    if run_3d_conversion and has_any_image:
        try:
            _get_worldlabs_key()

            logger.info("Stage 5: Converting to 3D scene via World Labs")

            if has_both_images:
                # Multi-image mode: send both forward and backward views
                fwd_bytes = base64.b64decode(result.forward.final_image_base64)
                bwd_bytes = base64.b64decode(result.backward.final_image_base64)

                request = ConvertToSceneRequest(
                    image_bytes_list=[fwd_bytes, bwd_bytes],
                    text_prompt=text_prompt_3d,
                    model=MarbleModel.PLUS,
                    display_name=f"Instaroom — @{username}",
                    tags=["instaroom", username],
                )
            else:
                # Fallback: single image (whichever succeeded)
                image_b64 = result.forward.final_image_base64 or result.backward.final_image_base64
                image_bytes = base64.b64decode(image_b64)

                request = ConvertToSceneRequest(
                    image_bytes=image_bytes,
                    text_prompt=text_prompt_3d,
                    model=MarbleModel.PLUS,
                    display_name=f"Instaroom — @{username}",
                    tags=["instaroom", username],
                )

            scene_result = await convert_to_3d_scene(request)
            logger.info("Stage 5 complete: world_id=%s", scene_result.world_id)

        except WorldLabsError:
            logger.error("Stage 5 failed (WorldLabsError)", exc_info=True)
        except Exception:
            logger.error("Stage 5 failed (unexpected)", exc_info=True)
    elif not run_3d_conversion:
        logger.info("Stage 5: Skipped (run_3d_conversion=False)")
    else:
        logger.warning("Stage 5: Skipped (no images from Stage 4)")

    # Save debug output
    _save_debug_output(
        output_dir, crawl_result, analyses, profile,
        forward_prompt, backward_prompt, result, scene_result,
        text_prompt_3d,
    )

    return result, profile, scene_result


def _save_debug_output(
    output_dir: str,
    crawl_result: ScrapeResult,
    analyses: list[PostAnalysisWithMeta],
    profile: AggregatedProfile,
    forward_prompt: ImageGenPrompt,
    backward_prompt: ImageGenPrompt | None,
    result: DualImageGenResult,
    scene_result: ConvertToSceneResult | None,
    text_prompt_3d: str | None = None,
) -> None:
    """Save all intermediate results to a debug JSON file + image files."""
    username = crawl_result.profile.username
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    os.makedirs(output_dir, exist_ok=True)

    def _save_view_attempts(
        view_result: ImageGenResult,
        view_label: str,
    ) -> list[dict]:
        """Save attempt images for a single viewpoint and return JSON-safe data."""
        attempts_json = []
        for attempt in view_result.attempts:
            image_filename = ""
            if attempt.image_base64:
                image_filename = (
                    f"{username}_{timestamp}_{view_label}_attempt_{attempt.attempt_number}.png"
                )
                image_path = os.path.join(output_dir, image_filename)
                try:
                    image_bytes = base64.b64decode(attempt.image_base64)
                    with open(image_path, "wb") as f:
                        f.write(image_bytes)
                    logger.info(
                        "Saved %s attempt %d image to %s",
                        view_label, attempt.attempt_number, image_path,
                    )
                except Exception:
                    logger.error("Failed to save attempt image", exc_info=True)

            attempts_json.append({
                "attempt_number": attempt.attempt_number,
                "image_file": image_filename,
                "critique": attempt.critique.model_dump() if attempt.critique else None,
                "prompt_used": attempt.prompt_used,
            })
        return attempts_json

    fwd_attempts_json = _save_view_attempts(result.forward, "forward")
    bwd_attempts_json = _save_view_attempts(result.backward, "backward")

    def _prompt_to_dict(prompt_data: ImageGenPrompt) -> dict:
        return {
            "layout": prompt_data.layout.model_dump(),
            "object_details": [od.model_dump() for od in prompt_data.object_details],
            "final_prompt": prompt_data.final_prompt,
            "reference_image_urls": prompt_data.reference_image_urls,
            "reference_image_mapping": {
                str(k): v for k, v in prompt_data.reference_image_mapping.items()
            },
        }

    debug_data = {
        "metadata": {
            "username": username,
            "timestamp": timestamp,
            "post_count": len(crawl_result.posts),
            "analyzed_count": len(analyses),
        },
        "stage_1_analyses": [a.model_dump() for a in analyses],
        "stage_2_profile": profile.model_dump(),
        "stage_3_prompt": {
            "forward": _prompt_to_dict(forward_prompt),
            "backward": _prompt_to_dict(backward_prompt) if backward_prompt else None,
        },
        "stage_4_result": {
            "forward": {
                "attempts": fwd_attempts_json,
                "final_critique": (
                    result.forward.final_critique.model_dump()
                    if result.forward.final_critique else None
                ),
                "total_attempts": result.forward.total_attempts,
            },
            "backward": {
                "attempts": bwd_attempts_json,
                "final_critique": (
                    result.backward.final_critique.model_dump()
                    if result.backward.final_critique else None
                ),
                "total_attempts": result.backward.total_attempts,
            },
        },
        "stage_5_result": {
            "text_prompt_3d": text_prompt_3d,
            "world_id": scene_result.world_id if scene_result else None,
            "world_marble_url": scene_result.world_marble_url if scene_result else None,
            "thumbnail_url": scene_result.thumbnail_url if scene_result else None,
            "viewer_data": scene_result.viewer_data.model_dump() if scene_result else None,
        } if scene_result or text_prompt_3d else None,
    }

    json_path = os.path.join(output_dir, f"{username}_{timestamp}.json")
    try:
        with open(json_path, "w") as f:
            json.dump(debug_data, f, indent=2, ensure_ascii=False)
        logger.info("Saved debug output to %s", json_path)
    except Exception:
        logger.error("Failed to save debug output", exc_info=True)
