#!/usr/bin/env python
"""Quick standalone pipeline test.

Runs the full pipeline (Stages 1-4, optionally Stage 5) against the natgeo
fixture and saves output to the output/ directory.

Usage:
    cd backend
    .venv/bin/python tests/test_quick.py              # dual-view, no 3D
    .venv/bin/python tests/test_quick.py --single-view # single image
    .venv/bin/python tests/test_quick.py --3d          # include Stage 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so `app` is importable without pip install
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Load .env from backend/ directory before any service imports
try:
    import dotenv
    dotenv.load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from app.services.crawler.scraper import ScrapeResult
from app.services.pipeline import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def _load_fixture() -> ScrapeResult:
    fixture_path = FIXTURES_DIR / "natgeo_parsed.json"
    with open(fixture_path) as f:
        data = json.load(f)
    return ScrapeResult.model_validate(data)


async def main(*, dual_view: bool = True, run_3d: bool = False) -> None:
    if not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY is not set. Add it to backend/.env or export it.")
        sys.exit(1)

    crawl = _load_fixture()
    logger.info(
        "Running pipeline for @%s (%d posts) — dual_view=%s, 3d=%s",
        crawl.profile.username, len(crawl.posts), dual_view, run_3d,
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    result, profile, scene_result = await run_pipeline(
        crawl,
        output_dir=str(OUTPUT_DIR),
        run_3d_conversion=run_3d,
        dual_view=dual_view,
    )

    # Summary
    fwd = result.forward
    bwd = result.backward
    print("\n=== PIPELINE COMPLETE ===")
    print(f"  Key objects: {[o.name for o in profile.key_objects]}")
    print(f"  Style: {profile.atmosphere.style}")
    if fwd.final_image_base64:
        score = fwd.final_critique.avg_score if fwd.final_critique else 0
        print(f"  Forward:  {fwd.total_attempts} attempts, score={score:.2f}")
    else:
        print("  Forward:  no image generated")
    if bwd.final_image_base64:
        score = bwd.final_critique.avg_score if bwd.final_critique else 0
        print(f"  Backward: {bwd.total_attempts} attempts, score={score:.2f}")
    else:
        print(f"  Backward: skipped" if not dual_view else "  Backward: no image generated")
    if scene_result:
        print(f"  3D world: {scene_result.world_id}")
    print(f"  Output:   {OUTPUT_DIR}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quick pipeline test")
    parser.add_argument(
        "--single-view", action="store_true",
        help="Generate a single image with all objects (instead of dual forward+backward)",
    )
    parser.add_argument(
        "--3d", action="store_true", dest="run_3d",
        help="Run Stage 5 (World Labs 3D conversion). Requires WORLDLABS_API_KEY.",
    )
    args = parser.parse_args()

    asyncio.run(main(dual_view=not args.single_view, run_3d=args.run_3d))
