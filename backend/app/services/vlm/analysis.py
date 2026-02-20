"""Stage 1: Per-post VLM analysis.

Each post is analyzed individually by Gemini Flash to extract
objects, scene info, people, emotional weight, and frame-worthiness.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from google.genai import types

from app.services.gemini_client import (
    FLASH_MODEL,
    download_images,
    get_gemini_client,
)
from app.services.models import Post, PostAnalysis, PostAnalysisWithMeta

logger = logging.getLogger(__name__)

_ANALYSIS_PROMPT = """\
You are an expert visual analyst. Analyze this Instagram post and extract structured information.

Context provided by the poster:
- Caption: {caption}
- Hashtags: {hashtags}
- Location: {location}

Analyze the image(s) and return a JSON object with these fields:

- objects: list of notable physical objects in the image. For each object provide:
  - name: lowercase snake_case identifier (e.g. "acoustic_guitar", "orange_cat")
  - prominence: "center" if it's a main subject, "background" if visible but not focal, "minor" if barely visible
  - description: brief visual description (color, style, condition)
- scene: information about the setting:
  - location_type: e.g. "bedroom", "cafe", "beach", "studio", "outdoors", "kitchen"
  - mood: list of mood descriptors (e.g. ["warm", "cozy", "intimate"])
  - lighting: one of "natural", "golden_hour", "artificial", "dark", "bright", "neon", "soft"
  - color_palette: list of 3-5 dominant hex colors
- people: information about people in the image:
  - count: number of people visible
  - is_selfie: true if this appears to be a selfie
  - activity: what the person is doing (null if no people)
- emotional_weight: 1-5 scale of how emotionally significant this post appears (5 = deeply personal/meaningful, 1 = casual/mundane)
- frame_worthy: true if this image would look good as a framed photo on a wall (good composition, aesthetic appeal, personal significance)
- frame_reason: brief explanation of why this image is or isn't frame-worthy

Focus on physical objects that could be placed in a room to represent this person's identity.
If this is a video thumbnail, analyze whatever is visible in the still frame.
If multiple images are provided (carousel post), analyze them holistically as a single post.
"""

_CONCURRENCY_LIMIT = 5


async def analyze_posts(posts: list[Post]) -> list[PostAnalysisWithMeta]:
    """Analyze all posts concurrently, returning successful analyses."""
    if not posts:
        return []

    sem = asyncio.Semaphore(_CONCURRENCY_LIMIT)

    async with httpx.AsyncClient(timeout=30.0) as http_client:

        async def _analyze_one(idx: int, post: Post) -> PostAnalysisWithMeta | None:
            async with sem:
                return await _analyze_single_post(idx, post, http_client)

        results = await asyncio.gather(
            *[_analyze_one(i, p) for i, p in enumerate(posts)],
            return_exceptions=True,
        )

    successes: list[PostAnalysisWithMeta] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(
                "Failed to analyze post #%d: %s",
                i,
                result,
            )
        elif result is not None:
            successes.append(result)

    logger.info("Analyzed %d/%d posts successfully", len(successes), len(posts))
    return successes


async def _analyze_single_post(
    index: int,
    post: Post,
    http_client: httpx.AsyncClient,
) -> PostAnalysisWithMeta | None:
    """Analyze a single post with Gemini Flash."""
    # Determine which images to send
    image_urls = post.image_urls or []
    if not image_urls and post.video_url:
        logger.warning("Post #%d is video with no thumbnail, skipping", index)
        return None
    if not image_urls:
        logger.warning("Post #%d has no images, skipping", index)
        return None

    # Download images
    image_bytes_list = await download_images(image_urls, client=http_client)
    valid_images = [b for b in image_bytes_list if b is not None]
    if not valid_images:
        logger.warning("Post #%d: all image downloads failed, skipping", index)
        return None

    # Build the prompt
    prompt_text = _ANALYSIS_PROMPT.format(
        caption=post.caption or "(no caption)",
        hashtags=", ".join(post.hashtags) if post.hashtags else "(none)",
        location=post.location or "(unknown)",
    )

    # Build content parts: images first, then text
    parts: list[types.Part] = []
    for img_bytes in valid_images:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text=prompt_text))

    # Call Gemini Flash with structured JSON output
    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=FLASH_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PostAnalysis,
            temperature=0.3,
        ),
    )

    # Parse the response
    raw_text = response.text
    if not raw_text:
        logger.warning("Post #%d: empty response from Gemini", index)
        return None

    analysis = PostAnalysis.model_validate_json(raw_text)

    return PostAnalysisWithMeta(
        analysis=analysis,
        post_index=index,
        likes=post.likes,
        image_urls=post.image_urls,
        caption=post.caption,
        hashtags=post.hashtags,
    )
