"""Apify Instagram Scraper client for fetching profile and post data.

Uses the apify/instagram-scraper actor via Apify API.
Requires APIFY_API_TOKEN environment variable.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from apify_client import ApifyClient
from pydantic import BaseModel


class Post(BaseModel):
    image_urls: list[str]
    video_url: str | None
    caption: str
    hashtags: list[str]
    likes: int
    date: datetime
    location: str | None
    is_video: bool


class Profile(BaseModel):
    username: str
    biography: str
    profile_pic_url: str
    follower_count: int
    post_count: int


class ScrapeResult(BaseModel):
    profile: Profile
    posts: list[Post]


def _extract_hashtags(caption: str) -> list[str]:
    """Extract hashtags from a caption string."""
    return re.findall(r"#\w+", caption)


def _parse_post(raw: dict) -> Post:
    """Map Apify post output to our Post model."""
    caption = raw.get("caption") or ""

    # Handle carousel images: use displayUrl as primary, plus any sidecar images
    image_urls: list[str] = []
    if raw.get("images"):
        image_urls = [img for img in raw["images"] if img]
    elif raw.get("displayUrl"):
        image_urls = [raw["displayUrl"]]

    return Post(
        image_urls=image_urls,
        video_url=raw.get("videoUrl"),
        caption=caption,
        hashtags=raw.get("hashtags") or _extract_hashtags(caption),
        likes=raw.get("likesCount", 0),
        date=raw.get("timestamp", datetime.now()),
        location=raw.get("locationName"),
        is_video=raw.get("type", "") == "Video",
    )


def _parse_profile(raw: dict) -> Profile:
    """Map Apify profile output to our Profile model."""
    return Profile(
        username=raw.get("username", ""),
        biography=raw.get("biography", ""),
        profile_pic_url=raw.get("profilePicUrl", ""),
        follower_count=raw.get("followersCount", 0),
        post_count=raw.get("postsCount", 0),
    )


def scrape_profile(username: str) -> ScrapeResult:
    """Scrape an Instagram profile's details and 10 most recent posts.

    Args:
        username: Instagram username (without @).

    Returns:
        ScrapeResult with profile info and recent posts.

    Raises:
        ValueError: If APIFY_API_TOKEN is not set.
        RuntimeError: If the scraper fails or returns no data.
    """
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise ValueError(
            "APIFY_API_TOKEN environment variable is not set. "
            "Get your token at https://console.apify.com/account/integrations"
        )

    client = ApifyClient(token)
    profile_url = f"https://www.instagram.com/{username}/"

    # Call 1 — Profile details
    profile_run = client.actor("apify/instagram-scraper").call(run_input={
        "directUrls": [profile_url],
        "resultsType": "details",
        "resultsLimit": 1,
    })
    profile_items = list(
        client.dataset(profile_run["defaultDatasetId"]).iterate_items()
    )
    if not profile_items:
        raise RuntimeError(
            f"No profile data returned for '{username}'. "
            "The account may be private or does not exist."
        )
    profile = _parse_profile(profile_items[0])

    # Call 2 — 10 most recent posts
    posts_run = client.actor("apify/instagram-scraper").call(run_input={
        "directUrls": [profile_url],
        "resultsType": "posts",
        "resultsLimit": 10,
    })
    post_items = list(
        client.dataset(posts_run["defaultDatasetId"]).iterate_items()
    )
    if not post_items:
        raise RuntimeError(
            f"No posts returned for '{username}'. "
            "The account may be private or has no posts."
        )
    posts = [_parse_post(item) for item in post_items]

    return ScrapeResult(profile=profile, posts=posts)
