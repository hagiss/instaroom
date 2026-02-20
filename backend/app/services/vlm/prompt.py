"""Stage 3: Agentic prompt design for image generation.

Builds the image generation prompt step by step:
layout planning -> object details -> final assembly.
Three VLM calls total.
"""

from __future__ import annotations

import logging

from google.genai import types
from pydantic import BaseModel, Field

from app.services.gemini_client import FLASH_MODEL, get_gemini_client
from app.services.models import (
    AggregatedProfile,
    ImageGenPrompt,
    LayoutPlan,
    ObjectDetail,
)

logger = logging.getLogger(__name__)

_MAX_REFERENCE_IMAGES = 14  # Gemini image generation limit


# ---------------------------------------------------------------------------
# Internal response schemas
# ---------------------------------------------------------------------------

class _LayoutResponse(BaseModel):
    room_shape: str = ""
    window_placement: str = ""
    furniture: list[str] = Field(default_factory=list)
    object_placements: list[str] = Field(default_factory=list)
    visual_flow: str = ""
    camera_position: str = ""
    camera_direction: str = ""


class _ObjectDetailsResponse(BaseModel):
    object_details: list[ObjectDetail] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def design_prompt(profile: AggregatedProfile) -> ImageGenPrompt:
    """Design an image generation prompt in 3 VLM steps.

    1. Layout planning (structured JSON)
    2. Object detail descriptions (structured JSON)
    3. Final prompt assembly (free-form text)
    """
    # Build reference image list from key objects
    ref_urls, ref_mapping = _build_reference_images(profile)

    # Step 1: Layout planning
    layout = await _plan_layout(profile)

    # Step 2: Object detail descriptions
    object_details = await _describe_objects(profile, layout)

    # Step 3: Final prompt assembly
    final_prompt = await _assemble_final_prompt(
        profile, layout, object_details, ref_mapping,
    )

    return ImageGenPrompt(
        layout=LayoutPlan(
            room_shape=layout.room_shape,
            window_placement=layout.window_placement,
            furniture=layout.furniture,
            object_placements=layout.object_placements,
            visual_flow=layout.visual_flow,
            camera_position=layout.camera_position,
            camera_direction=layout.camera_direction,
        ),
        object_details=object_details,
        final_prompt=final_prompt,
        reference_image_urls=ref_urls,
        reference_image_mapping=ref_mapping,
    )


# ---------------------------------------------------------------------------
# Reference image strategy
# ---------------------------------------------------------------------------

def _build_reference_images(
    profile: AggregatedProfile,
) -> tuple[list[str], dict[int, str]]:
    """Build ordered reference image list from key objects.

    Returns (urls, mapping) where mapping is {1-indexed position: object description}.
    """
    urls: list[str] = []
    mapping: dict[int, str] = {}

    for obj in profile.key_objects:
        if len(urls) >= _MAX_REFERENCE_IMAGES:
            break
        if obj.source_image_url:
            urls.append(obj.source_image_url)
            mapping[len(urls)] = obj.name

    return urls, mapping


# ---------------------------------------------------------------------------
# Step 1: Layout planning (1 VLM call)
# ---------------------------------------------------------------------------

_LAYOUT_PROMPT = """\
You are an expert interior designer planning a room layout for image generation.

**Persona**: {persona}
**Style**: {style}
**Atmosphere**: mood={mood}, lighting={lighting}, time_of_day={time_of_day}
**Window view**: {window_view}
**Room size**: {room_size}

**Key objects that MUST be in the room** (ranked by importance):
{objects_text}

Design a room layout with these constraints:
1. The room should feel personal and lived-in, not like a showroom
2. ALL key objects must be visible from a SINGLE camera viewpoint — this is a hard constraint
3. Arrange objects naturally so they can all be seen from one direction
4. Choose a camera position and direction that captures the most compelling composition

Return:
- room_shape: The shape of the room (e.g., "rectangular", "L-shaped", "open plan")
- window_placement: Where the window is relative to the camera (e.g., "left wall", "far wall", "behind camera")
- furniture: List of major furniture pieces and their positions
- object_placements: Where each key object is placed (e.g., "acoustic_guitar: leaning against the wall to the right")
- visual_flow: How the eye moves through the scene
- camera_position: Where the camera is (e.g., "standing at the doorway", "corner of the room")
- camera_direction: What direction the camera faces (e.g., "looking toward the far wall with window")
"""


async def _plan_layout(profile: AggregatedProfile) -> _LayoutResponse:
    objects_text = "\n".join(
        f"  {i+1}. {o.name} — {o.description}"
        for i, o in enumerate(profile.key_objects)
    )

    prompt = _LAYOUT_PROMPT.format(
        persona=profile.persona_summary,
        style=profile.atmosphere.style,
        mood=profile.atmosphere.dominant_mood,
        lighting=profile.atmosphere.dominant_lighting,
        time_of_day=profile.atmosphere.time_of_day,
        window_view=profile.atmosphere.window_view,
        room_size=profile.atmosphere.room_size,
        objects_text=objects_text or "(no specific objects)",
    )

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=FLASH_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_LayoutResponse,
            temperature=0.6,
        ),
    )

    raw = response.text
    if not raw:
        logger.warning("Empty layout response")
        return _LayoutResponse()

    return _LayoutResponse.model_validate_json(raw)


# ---------------------------------------------------------------------------
# Step 2: Object detail descriptions (1 VLM call)
# ---------------------------------------------------------------------------

_OBJECT_DETAIL_PROMPT = """\
You are describing objects in a room for an image generation prompt. The room is viewed \
from a specific camera angle.

**Camera position**: {camera_position}
**Camera direction**: {camera_direction}
**Room style**: {style}

**Objects and their placements**:
{placements_text}

For each object, describe how it appears FROM THE CAMERA'S PERSPECTIVE. Include:
- name: the object name
- placement: where it sits in the frame (left, right, center, foreground, background)
- detailed_description: vivid, specific visual description as seen from the camera angle. \
Include material, color, texture, size relative to the scene, and any distinctive features \
that make it personal rather than generic.
"""


async def _describe_objects(
    profile: AggregatedProfile,
    layout: _LayoutResponse,
) -> list[ObjectDetail]:
    placements = "\n".join(layout.object_placements) if layout.object_placements else ""
    obj_placements = placements or "\n".join(
        f"  - {o.name}: {o.description}" for o in profile.key_objects
    )

    prompt = _OBJECT_DETAIL_PROMPT.format(
        camera_position=layout.camera_position or "doorway",
        camera_direction=layout.camera_direction or "looking into the room",
        style=profile.atmosphere.style,
        placements_text=obj_placements,
    )

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=FLASH_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_ObjectDetailsResponse,
            temperature=0.5,
        ),
    )

    raw = response.text
    if not raw:
        logger.warning("Empty object detail response")
        return []

    parsed = _ObjectDetailsResponse.model_validate_json(raw)
    return parsed.object_details


# ---------------------------------------------------------------------------
# Step 3: Final prompt assembly (1 VLM call)
# ---------------------------------------------------------------------------

_ASSEMBLY_PROMPT = """\
You are writing an image generation prompt for a room scene. Write a single, detailed, \
natural-language paragraph that describes the room from the camera's viewpoint.

**Persona**: {persona}
**Style**: {style}
**Atmosphere**: mood={mood}, lighting={lighting}, time_of_day={time_of_day}
**Window view**: {window_view}
**Color palette**: {colors}

**Camera setup**:
- Position: {camera_position}
- Direction: {camera_direction}

**Object details (as seen from camera)**:
{object_details_text}

**Reference images are provided for these objects** (refer to them by number):
{ref_mapping_text}

Instructions:
- Write a vivid, photorealistic description of the room as seen from the camera angle
- Explicitly mention each key object with its visual details
- For objects that have reference images, say "the [object] from reference image [N]" \
so the image generator knows to match the reference
- Describe lighting, colors, mood, and atmosphere
- Include what's visible through the window
- Make it feel like a real, lived-in space — not a catalog
- Do NOT use bullet points or structured format — write flowing prose
- Keep it under 300 words

Return ONLY the prompt text, nothing else.
"""


async def _assemble_final_prompt(
    profile: AggregatedProfile,
    layout: _LayoutResponse,
    object_details: list[ObjectDetail],
    ref_mapping: dict[int, str],
) -> str:
    details_text = "\n".join(
        f"  - {od.name}: {od.detailed_description} (placed {od.placement})"
        for od in object_details
    )

    ref_text = "\n".join(
        f"  Reference image {idx}: {desc}" for idx, desc in ref_mapping.items()
    ) if ref_mapping else "  (no reference images)"

    prompt = _ASSEMBLY_PROMPT.format(
        persona=profile.persona_summary,
        style=profile.atmosphere.style,
        mood=profile.atmosphere.dominant_mood,
        lighting=profile.atmosphere.dominant_lighting,
        time_of_day=profile.atmosphere.time_of_day,
        window_view=profile.atmosphere.window_view,
        colors=", ".join(profile.atmosphere.color_palette) or "(varied)",
        camera_position=layout.camera_position or "doorway",
        camera_direction=layout.camera_direction or "looking into the room",
        object_details_text=details_text or "(no specific objects)",
        ref_mapping_text=ref_text,
    )

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=FLASH_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
        ),
    )

    raw = response.text
    if not raw:
        logger.warning("Empty assembly response")
        return ""

    return raw.strip()
