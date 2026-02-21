"""Generate a spatial 3D prompt for World Labs Marble from Stage 2/3 data.

Uses Gemini Flash to write a short paragraph focusing on the room's spatial
envelope and atmosphere — the parts NOT already captured by the image(s).
The 3D engine already sees every object in the images; the text prompt should
describe the surrounding space, hidden surfaces, and environmental context
so the engine can reconstruct a coherent 3D volume.
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
You are writing a short spatial description for a 3D scene generator that will \
turn room photograph(s) into an explorable 3D environment.

CRITICAL: The 3D engine already has the photograph(s). Every object, piece of \
furniture, and surface visible in the image will be reconstructed automatically. \
Do NOT name, list, or describe any object that appears in the image — doing so \
causes ugly duplication in the 3D scene.

Instead, describe ONLY what the camera CANNOT see but what a person standing in \
the room would know exists:

**Room context**:
- Room shape: {room_shape}
- Room size: {room_size}
- Camera position: {camera_position}
- Camera direction (forward): {camera_direction}
{backward_direction_line}
- Window placement: {window_placement}
- Window view: {window_view}
- Time of day: {time_of_day}

**What to describe** (~100 words, single paragraph):
1. **Room envelope** — ceiling height, ceiling material (beams, plaster, sloped?), \
wall material/texture on surfaces not fully visible, floor material extending beyond \
the frame
2. **Spatial continuation** — what is behind the camera (if single-view), what is to \
the left and right edges just out of frame, how the room connects to other spaces \
(doorway, hallway, open plan)
3. **Environmental depth** — what is beyond the window (sky, trees, cityscape, \
distance), natural light direction and how it falls across the floor
4. **Atmosphere** — ambient sound cues that imply space (echo of a large room, \
muffled coziness of a small one), air quality (dusty, fresh, warm)
{dual_view_instruction}

**Do NOT**:
- Name or describe ANY object, furniture, artwork, or item visible in the image(s)
- Repeat what the camera already sees — no "a desk sits against the wall", no \
"a framed photograph hangs above the sofa"
- Describe colors or materials of objects in the image

Return ONLY the spatial paragraph, nothing else.
"""


async def generate_3d_prompt(
    profile: AggregatedProfile,
    prompt_data: ImageGenPrompt,
) -> str:
    """Generate a spatial text prompt for the World Labs Marble 3D conversion.

    Focuses on the room envelope, hidden surfaces, and atmosphere —
    NOT the objects already visible in the image(s).

    Returns ``DEFAULT_TEXT_PROMPT`` on any failure — Stage 5 should never
    fail due to prompt generation.
    """
    try:
        layout = prompt_data.layout
        is_dual = bool(layout.camera_direction_back and layout.backward_objects)

        if is_dual:
            backward_direction_line = (
                f"- Camera direction (backward, 180°): {layout.camera_direction_back}"
            )
            dual_view_instruction = (
                "5. **Between the views** — TWO images are provided (forward + "
                "backward from the same position). Describe how the room volume "
                "connects between the two views: the side walls, the ceiling "
                "continuity, and any transitional space at the 90° angles that "
                "neither camera captures."
            )
        else:
            backward_direction_line = ""
            dual_view_instruction = ""

        prompt = _SPATIAL_PROMPT.format(
            room_shape=layout.room_shape or "rectangular",
            room_size=profile.atmosphere.room_size or "medium",
            camera_position=layout.camera_position or "doorway",
            camera_direction=layout.camera_direction or "looking into the room",
            backward_direction_line=backward_direction_line,
            window_placement=layout.window_placement or "far wall",
            window_view=profile.atmosphere.window_view or "exterior",
            time_of_day=profile.atmosphere.time_of_day or "afternoon",
            dual_view_instruction=dual_view_instruction,
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
