"""End-to-end pipeline test using the natgeo fixture.

Requires GOOGLE_API_KEY to be set (calls Gemini Flash + image gen).
Stage 5 (World Labs 3D) is skipped by default.

Usage:
    # From backend/
    .venv/bin/python -m pytest tests/test_pipeline.py -v -s

    # Or run directly:
    .venv/bin/python tests/test_pipeline.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

from app.services.crawler.scraper import ScrapeResult
from app.services.models import (
    AggregatedProfile,
    DualImageGenResult,
    ImageGenPrompt,
    LayoutPlan,
)
from app.services.pipeline import run_pipeline
from app.services.vlm.aggregation import aggregate_analyses
from app.services.vlm.analysis import analyze_posts
from app.services.vlm.prompt import design_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture() -> ScrapeResult:
    """Load the natgeo parsed fixture as a ScrapeResult."""
    fixture_path = FIXTURES_DIR / "natgeo_parsed.json"
    with open(fixture_path) as f:
        data = json.load(f)
    return ScrapeResult.model_validate(data)


def _require_google_api_key():
    """Skip test if GOOGLE_API_KEY is not set."""
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not set — skipping live API test")


# ---------------------------------------------------------------------------
# Stage-level tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stage1_analysis():
    """Stage 1: Per-post VLM analysis produces results for each post."""
    _require_google_api_key()

    crawl = _load_fixture()
    # Use only first 3 posts to keep test fast
    analyses = await analyze_posts(crawl.posts[:3])

    assert len(analyses) > 0, "No posts were analyzed"
    for a in analyses:
        assert a.analysis.objects, f"Post {a.post_index} has no detected objects"
    logger.info("Stage 1 OK: %d posts analyzed", len(analyses))


@pytest.mark.asyncio
async def test_stage2_aggregation():
    """Stage 2: Aggregation produces a profile with key objects."""
    _require_google_api_key()

    crawl = _load_fixture()
    analyses = await analyze_posts(crawl.posts[:3])
    profile = await aggregate_analyses(analyses, crawl.profile)

    assert profile.persona_summary, "Persona summary is empty"
    assert len(profile.key_objects) > 0, "No key objects"
    assert profile.atmosphere.style, "Style is empty"
    logger.info(
        "Stage 2 OK: %d key objects, style=%s",
        len(profile.key_objects), profile.atmosphere.style,
    )


@pytest.mark.asyncio
async def test_stage3_dual_prompts():
    """Stage 3: Prompt design returns two prompts with split objects."""
    _require_google_api_key()

    crawl = _load_fixture()
    analyses = await analyze_posts(crawl.posts[:3])
    profile = await aggregate_analyses(analyses, crawl.profile)

    forward_prompt, backward_prompt = await design_prompt(profile)

    # Both prompts should have content
    assert forward_prompt.final_prompt, "Forward prompt is empty"
    assert backward_prompt.final_prompt, "Backward prompt is empty"

    # Layout should have dual camera directions
    layout = forward_prompt.layout
    assert layout.camera_direction, "Forward camera direction is empty"
    assert layout.camera_direction_back, "Backward camera direction is empty"

    # Objects should be split between views
    assert layout.forward_objects, "No forward objects"
    assert layout.backward_objects, "No backward objects"

    # Each prompt should have its own object details
    assert forward_prompt.object_details, "Forward has no object details"
    assert backward_prompt.object_details, "Backward has no object details"

    # Forward and backward object details should differ
    fwd_names = {od.name for od in forward_prompt.object_details}
    bwd_names = {od.name for od in backward_prompt.object_details}
    assert fwd_names != bwd_names, "Forward and backward have identical objects"

    logger.info(
        "Stage 3 OK: forward=%d objects (%d chars), backward=%d objects (%d chars)",
        len(forward_prompt.object_details), len(forward_prompt.final_prompt),
        len(backward_prompt.object_details), len(backward_prompt.final_prompt),
    )
    logger.info("  Forward objects: %s", layout.forward_objects)
    logger.info("  Backward objects: %s", layout.backward_objects)


# ---------------------------------------------------------------------------
# Full pipeline test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_pipeline():
    """Full pipeline (Stages 1-4): produces two 4K images with debug output."""
    _require_google_api_key()

    crawl = _load_fixture()

    with tempfile.TemporaryDirectory(prefix="instaroom_test_") as tmpdir:
        result, profile, scene_result = await run_pipeline(
            crawl, output_dir=tmpdir, run_3d_conversion=False,
        )

        # --- Validate return types ---
        assert isinstance(result, DualImageGenResult)
        assert isinstance(profile, AggregatedProfile)
        assert scene_result is None  # 3D conversion skipped

        # --- Stage 2 checks ---
        assert len(profile.key_objects) > 0, "No key objects in profile"
        assert profile.atmosphere.style, "No style in profile"

        # --- Stage 4 forward checks ---
        fwd = result.forward
        assert fwd.final_image_base64, "No forward image generated"
        assert fwd.total_attempts > 0, "Forward has 0 attempts"
        assert fwd.final_critique is not None, "Forward has no critique"
        logger.info(
            "Forward: %d attempts, score=%.2f",
            fwd.total_attempts, fwd.final_critique.avg_score,
        )

        # --- Stage 4 backward checks ---
        bwd = result.backward
        assert bwd.final_image_base64, "No backward image generated"
        assert bwd.total_attempts > 0, "Backward has 0 attempts"
        assert bwd.final_critique is not None, "Backward has no critique"
        logger.info(
            "Backward: %d attempts, score=%.2f",
            bwd.total_attempts, bwd.final_critique.avg_score,
        )

        # --- Debug output checks ---
        output_files = os.listdir(tmpdir)
        json_files = [f for f in output_files if f.endswith(".json")]
        assert len(json_files) == 1, f"Expected 1 debug JSON, got {json_files}"

        # Check debug JSON structure
        with open(os.path.join(tmpdir, json_files[0])) as f:
            debug = json.load(f)

        assert "stage_3_prompt" in debug
        assert "forward" in debug["stage_3_prompt"]
        assert "backward" in debug["stage_3_prompt"]
        assert debug["stage_3_prompt"]["forward"]["final_prompt"]
        assert debug["stage_3_prompt"]["backward"]["final_prompt"]

        assert "stage_4_result" in debug
        assert "forward" in debug["stage_4_result"]
        assert "backward" in debug["stage_4_result"]

        # Check image files saved with correct prefixes
        png_files = [f for f in output_files if f.endswith(".png")]
        fwd_pngs = [f for f in png_files if "_forward_" in f]
        bwd_pngs = [f for f in png_files if "_backward_" in f]
        assert fwd_pngs, f"No forward PNG files found in {png_files}"
        assert bwd_pngs, f"No backward PNG files found in {png_files}"

        logger.info(
            "Debug output OK: %d JSON, %d forward PNGs, %d backward PNGs",
            len(json_files), len(fwd_pngs), len(bwd_pngs),
        )
        logger.info("Output dir: %s", tmpdir)

        # Print summary
        logger.info("=== PIPELINE TEST PASSED ===")
        logger.info("  Key objects: %s", [o.name for o in profile.key_objects])
        logger.info("  Forward score: %.2f", fwd.final_critique.avg_score)
        logger.info("  Backward score: %.2f", bwd.final_critique.avg_score)


# ---------------------------------------------------------------------------
# Direct invocation
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(test_full_pipeline())
