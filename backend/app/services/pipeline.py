"""Pipeline orchestrator: runs Stages 1-5 sequentially and saves debug output."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone

from app.services.image_gen.generate import generate_room_image
from app.services.models import (
    AggregatedProfile,
    ConvertToSceneResult,
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
from app.services.worldslabs.config import MarbleModel

logger = logging.getLogger(__name__)


async def run_pipeline(
    crawl_result: ScrapeResult,
    output_dir: str = "output",
    run_3d_conversion: bool = True,
) -> tuple[ImageGenResult, AggregatedProfile, ConvertToSceneResult | None]:
    """Run the full VLM pipeline: Stage 1 → 2 → 3 → 4 → 5.

    Returns the final image generation result, the aggregated profile,
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

    # Stage 3: Prompt design
    logger.info("Stage 3: Designing image generation prompt")
    prompt_data = await design_prompt(profile)
    logger.info("Stage 3 complete: prompt length=%d, %d reference images", len(prompt_data.final_prompt), len(prompt_data.reference_image_urls))

    # Stage 4: Image generation + critique
    logger.info("Stage 4: Generating room image")
    result = await generate_room_image(prompt_data, profile)
    logger.info("Stage 4 complete: %d attempts, final score=%.2f",
                result.total_attempts,
                result.final_critique.avg_score if result.final_critique else 0)

    # Stage 5: 3D conversion via World Labs Marble
    scene_result: ConvertToSceneResult | None = None
    if run_3d_conversion and result.final_image_base64:
        try:
            logger.info("Stage 5: Converting to 3D scene via World Labs")

            image_bytes = base64.b64decode(result.final_image_base64)

            text_prompt_3d = await generate_3d_prompt(profile, prompt_data)
            logger.info("Stage 5: 3D prompt generated (%d chars)", len(text_prompt_3d))

            request = ConvertToSceneRequest(
                image_bytes=image_bytes,
                text_prompt=text_prompt_3d,
                model=MarbleModel.MINI,
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
        logger.warning("Stage 5: Skipped (no final image from Stage 4)")

    # Save debug output
    _save_debug_output(output_dir, crawl_result, analyses, profile, prompt_data, result, scene_result)

    return result, profile, scene_result


def _save_debug_output(
    output_dir: str,
    crawl_result: ScrapeResult,
    analyses: list[PostAnalysisWithMeta],
    profile: AggregatedProfile,
    prompt_data: ImageGenPrompt,
    result: ImageGenResult,
    scene_result: ConvertToSceneResult | None,
) -> None:
    """Save all intermediate results to a debug JSON file + image files."""
    username = crawl_result.profile.username
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    os.makedirs(output_dir, exist_ok=True)

    # Save attempt images as separate files and strip base64 from JSON
    attempts_for_json = []
    for attempt in result.attempts:
        image_filename = ""
        if attempt.image_base64:
            image_filename = f"{username}_{timestamp}_attempt_{attempt.attempt_number}.png"
            image_path = os.path.join(output_dir, image_filename)
            try:
                image_bytes = base64.b64decode(attempt.image_base64)
                with open(image_path, "wb") as f:
                    f.write(image_bytes)
                logger.info("Saved attempt %d image to %s", attempt.attempt_number, image_path)
            except Exception:
                logger.error("Failed to save attempt image", exc_info=True)

        attempts_for_json.append({
            "attempt_number": attempt.attempt_number,
            "image_file": image_filename,
            "critique": attempt.critique.model_dump() if attempt.critique else None,
            "prompt_used": attempt.prompt_used,
        })

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
            "layout": prompt_data.layout.model_dump(),
            "object_details": [od.model_dump() for od in prompt_data.object_details],
            "final_prompt": prompt_data.final_prompt,
            "reference_image_urls": prompt_data.reference_image_urls,
            "reference_image_mapping": {
                str(k): v for k, v in prompt_data.reference_image_mapping.items()
            },
        },
        "stage_4_result": {
            "attempts": attempts_for_json,
            "final_critique": result.final_critique.model_dump() if result.final_critique else None,
            "total_attempts": result.total_attempts,
        },
        "stage_5_result": {
            "world_id": scene_result.world_id if scene_result else None,
            "world_marble_url": scene_result.world_marble_url if scene_result else None,
            "thumbnail_url": scene_result.thumbnail_url if scene_result else None,
            "viewer_data": scene_result.viewer_data.model_dump() if scene_result else None,
        } if scene_result else None,
    }

    json_path = os.path.join(output_dir, f"{username}_{timestamp}.json")
    try:
        with open(json_path, "w") as f:
            json.dump(debug_data, f, indent=2, ensure_ascii=False)
        logger.info("Saved debug output to %s", json_path)
    except Exception:
        logger.error("Failed to save debug output", exc_info=True)
