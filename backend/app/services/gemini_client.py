"""Shared Gemini client singleton and image download utilities."""

from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

import httpx
from google import genai

logger = logging.getLogger(__name__)

FLASH_MODEL = "gemini-2.5-flash"
IMAGE_GEN_MODEL = "gemini-3-flash-preview"


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    """Return a singleton Gemini client."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY environment variable is not set")
    return genai.Client(api_key=api_key)


async def download_image(
    url: str,
    client: httpx.AsyncClient | None = None,
) -> bytes | None:
    """Download a single image, returning bytes or None on failure."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception:
        logger.warning("Failed to download image: %s", url, exc_info=True)
        return None
    finally:
        if own_client:
            await client.aclose()


async def download_images(
    urls: list[str],
    client: httpx.AsyncClient | None = None,
    max_concurrent: int = 10,
) -> list[bytes | None]:
    """Download multiple images concurrently with a semaphore."""
    sem = asyncio.Semaphore(max_concurrent)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)

    async def _dl(url: str) -> bytes | None:
        async with sem:
            return await download_image(url, client)

    try:
        return await asyncio.gather(*[_dl(u) for u in urls])
    finally:
        if own_client:
            await client.aclose()
