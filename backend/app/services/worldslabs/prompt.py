"""Generate a spatial 3D prompt for World Labs Marble from Stage 2/3 data.

Uses Gemini Flash to write a short paragraph focusing on room geometry,
furniture positions, and camera viewpoint — NOT aesthetics (already in the image).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from google.genai import types

from app.services.gemini_client import FLASH_MODEL, get_gemini_client

from .config import DEFAULT_TEXT_PROMPT

if TYPE_CHECKING:
    from app.services.models import AggregatedProfile, ImageGenPrompt

logger = logging.getLogger(__name__)

_SPATIAL_PROMPT = """\
You are writing a short spatial description of a room for a 3D scene generator.
The 3D engine already has the image — it needs help understanding the GEOMETRY and DEPTH,
not the aesthetics.

**Room shape**: {room_shape}
**Room size**: {room_size}
**Camera position**: {camera_position}
**Camera direction**: {camera_direction}
**Window placement**: {window_placement}
**Window view**: {window_view}
**Time of day**: {time_of_day}

**Object placements in the room**:
{object_placements}

**Visual flow**: {visual_flow}

Instructions:
- Write a single paragraph (~120 words) describing the room's 3D spatial layout
- Focus on: room dimensions, wall/floor/ceiling relationships, furniture positions \
relative to walls and each other, depth layering (foreground → background), and camera viewpoint
- DO NOT describe colors, mood, aesthetics, lighting quality, or artistic style — \
those are already captured in the image
- Use spatial language: "near the left wall", "receding toward the far corner", \
"in the foreground at knee height", "the ceiling slopes down to the right"
- Mention the window as a depth anchor (where it sits in the room geometry)
- Keep it factual and geometric

Return ONLY the spatial paragraph, nothing else.
"""


async def generate_3d_prompt(
    profile: AggregatedProfile,
    prompt_data: ImageGenPrompt,
) -> str:
    """Generate a spatial text prompt for the World Labs Marble 3D conversion.

    Returns ``DEFAULT_TEXT_PROMPT`` on any failure — Stage 5 should never
    fail due to prompt generation.
    """
    try:
        layout = prompt_data.layout

        object_placements = "\n".join(
            f"  - {p}" for p in layout.object_placements
        ) if layout.object_placements else "  (no specific placements)"

        prompt = _SPATIAL_PROMPT.format(
            room_shape=layout.room_shape or "rectangular",
            room_size=profile.atmosphere.room_size or "medium",
            camera_position=layout.camera_position or "doorway",
            camera_direction=layout.camera_direction or "looking into the room",
            window_placement=layout.window_placement or "far wall",
            window_view=profile.atmosphere.window_view or "exterior",
            time_of_day=profile.atmosphere.time_of_day or "afternoon",
            object_placements=object_placements,
            visual_flow=layout.visual_flow or "natural left-to-right",
        )

        client = get_gemini_client()
        response = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,
            ),
        )

        raw = response.text
        if not raw or not raw.strip():
            logger.warning("Empty 3D prompt response from Gemini, using default")
            return DEFAULT_TEXT_PROMPT

        result = raw.strip()
        logger.info("Generated 3D spatial prompt (%d chars)", len(result))
        return result

    except Exception:
        logger.warning(
            "Failed to generate 3D prompt, using default", exc_info=True
        )
        return DEFAULT_TEXT_PROMPT
