"""Stage 3: Agentic prompt design for image generation.

When dual_view=True (default):
  Builds TWO image generation prompts (forward + backward) step by step:
  1. Full-room layout planning (single VLM call — distributes objects across both views)
  2. Object detail descriptions (parallel VLM calls — one per view)
  3. Final prompt assembly (parallel VLM calls — one per view)
  Five VLM calls total (steps 2+3 run in parallel per viewpoint).

When dual_view=False:
  Builds a SINGLE image generation prompt with all objects in one view:
  1. Single-view layout planning (1 VLM call)
  2. Object detail descriptions (1 VLM call)
  3. Final prompt assembly (1 VLM call)
  Three VLM calls total.
"""

from __future__ import annotations

import asyncio
import logging
import re

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

class _FullRoomLayoutResponse(BaseModel):
    room_shape: str = ""
    window_placement: str = ""
    furniture: list[str] = Field(default_factory=list)
    object_placements: list[str] = Field(default_factory=list)
    visual_flow: str = ""
    camera_position: str = ""
    camera_direction_forward: str = ""
    camera_direction_backward: str = ""
    forward_objects: list[str] = Field(default_factory=list)
    backward_objects: list[str] = Field(default_factory=list)


class _ObjectDetailsResponse(BaseModel):
    object_details: list[ObjectDetail] = Field(default_factory=list)


class _ViewLayout:
    """Helper grouping per-view camera direction + filtered object placements."""

    def __init__(
        self,
        camera_direction: str,
        object_names: list[str],
        all_placements: list[str],
    ) -> None:
        self.camera_direction = camera_direction
        self.object_names = object_names
        self.object_placements = [
            p for p in all_placements
            if _placement_matches_objects(p, object_names)
        ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def design_prompt(
    profile: AggregatedProfile,
    *,
    dual_view: bool = True,
) -> tuple[ImageGenPrompt, ImageGenPrompt | None]:
    """Design image generation prompts.

    When dual_view=True (default): 5 VLM calls, returns (forward_prompt, backward_prompt).
    When dual_view=False: 3 VLM calls, returns (forward_prompt, None).
    """
    # Step 1: Layout planning
    layout = await _plan_layout(profile, dual_view=dual_view)

    if not dual_view:
        return await _design_single_view(profile, layout)

    return await _design_dual_view(profile, layout)


async def _design_single_view(
    profile: AggregatedProfile,
    layout: _FullRoomLayoutResponse,
) -> tuple[ImageGenPrompt, None]:
    """Single-view path: all objects in one forward view (3 VLM calls total)."""
    # Ensure all objects land in forward_objects
    if not layout.forward_objects:
        layout.forward_objects = [o.name for o in profile.key_objects]
    layout.backward_objects = []

    fwd_view = _ViewLayout(
        camera_direction=layout.camera_direction_forward,
        object_names=layout.forward_objects,
        all_placements=layout.object_placements,
    )

    # Step 2: Object detail descriptions (1 call)
    fwd_details = await _describe_objects(profile, layout, fwd_view)

    # Build reference images
    fwd_urls, fwd_mapping = _build_reference_images_for_view(
        profile, fwd_view.object_names,
    )

    # Step 3: Final prompt assembly (1 call)
    fwd_prompt_text = await _assemble_final_prompt(
        profile, layout, fwd_view, fwd_details, fwd_mapping,
    )

    shared_layout = LayoutPlan(
        room_shape=layout.room_shape,
        window_placement=layout.window_placement,
        furniture=layout.furniture,
        object_placements=layout.object_placements,
        visual_flow=layout.visual_flow,
        camera_position=layout.camera_position,
        camera_direction=layout.camera_direction_forward,
        camera_direction_back="",
        forward_objects=layout.forward_objects,
        backward_objects=[],
    )

    forward_prompt = ImageGenPrompt(
        layout=shared_layout,
        object_details=fwd_details,
        final_prompt=fwd_prompt_text,
        reference_image_urls=fwd_urls,
        reference_image_mapping=fwd_mapping,
    )

    return forward_prompt, None


async def _design_dual_view(
    profile: AggregatedProfile,
    layout: _FullRoomLayoutResponse,
) -> tuple[ImageGenPrompt, ImageGenPrompt]:
    """Dual-view path: forward + backward views (5 VLM calls total)."""
    # Fallback: if LLM returned empty object lists, split by alternating rank
    if not layout.forward_objects and not layout.backward_objects:
        all_names = [o.name for o in profile.key_objects]
        layout.forward_objects = all_names[0::2]   # even indices
        layout.backward_objects = all_names[1::2]  # odd indices
        logger.warning(
            "LLM returned empty object splits — falling back to alternating split: "
            "forward=%d, backward=%d",
            len(layout.forward_objects), len(layout.backward_objects),
        )
    elif not layout.forward_objects:
        # All objects went backward — move first half to forward
        half = len(layout.backward_objects) // 2 or 1
        layout.forward_objects = layout.backward_objects[:half]
        layout.backward_objects = layout.backward_objects[half:]
        logger.warning("LLM returned empty forward_objects — rebalanced split")
    elif not layout.backward_objects:
        # All objects went forward — move second half to backward
        half = len(layout.forward_objects) // 2 or 1
        layout.backward_objects = layout.forward_objects[half:]
        layout.forward_objects = layout.forward_objects[:half]
        logger.warning("LLM returned empty backward_objects — rebalanced split")

    fwd_view = _ViewLayout(
        camera_direction=layout.camera_direction_forward,
        object_names=layout.forward_objects,
        all_placements=layout.object_placements,
    )
    bwd_view = _ViewLayout(
        camera_direction=layout.camera_direction_backward,
        object_names=layout.backward_objects,
        all_placements=layout.object_placements,
    )

    # Step 2: Object detail descriptions (parallel)
    fwd_details, bwd_details = await asyncio.gather(
        _describe_objects(profile, layout, fwd_view),
        _describe_objects(profile, layout, bwd_view),
    )

    # Build per-view reference images
    fwd_urls, fwd_mapping = _build_reference_images_for_view(
        profile, fwd_view.object_names,
    )
    bwd_urls, bwd_mapping = _build_reference_images_for_view(
        profile, bwd_view.object_names,
    )

    # Step 3: Final prompt assembly (parallel)
    fwd_prompt_text, bwd_prompt_text = await asyncio.gather(
        _assemble_final_prompt(profile, layout, fwd_view, fwd_details, fwd_mapping),
        _assemble_final_prompt(profile, layout, bwd_view, bwd_details, bwd_mapping),
    )

    shared_layout = LayoutPlan(
        room_shape=layout.room_shape,
        window_placement=layout.window_placement,
        furniture=layout.furniture,
        object_placements=layout.object_placements,
        visual_flow=layout.visual_flow,
        camera_position=layout.camera_position,
        camera_direction=layout.camera_direction_forward,
        camera_direction_back=layout.camera_direction_backward,
        forward_objects=layout.forward_objects,
        backward_objects=layout.backward_objects,
    )

    forward_prompt = ImageGenPrompt(
        layout=shared_layout,
        object_details=fwd_details,
        final_prompt=fwd_prompt_text,
        reference_image_urls=fwd_urls,
        reference_image_mapping=fwd_mapping,
    )
    backward_prompt = ImageGenPrompt(
        layout=shared_layout,
        object_details=bwd_details,
        final_prompt=bwd_prompt_text,
        reference_image_urls=bwd_urls,
        reference_image_mapping=bwd_mapping,
    )

    return forward_prompt, backward_prompt


# ---------------------------------------------------------------------------
# Reference image strategy
# ---------------------------------------------------------------------------

def _build_reference_images_for_view(
    profile: AggregatedProfile,
    visible_names: list[str],
) -> tuple[list[str], dict[int, str]]:
    """Build deduplicated reference image list filtered to this viewpoint's objects.

    Multiple objects from the same source image share one reference image number.
    Returns (urls, mapping) where mapping is {1-indexed position: comma-separated object names}.
    """
    lower_names = {n.lower() for n in visible_names}
    urls: list[str] = []
    url_to_index: dict[str, int] = {}
    mapping: dict[int, str] = {}

    for obj in profile.key_objects:
        if obj.name.lower() not in lower_names:
            continue
        if not obj.source_image_url:
            continue
        if obj.source_image_url in url_to_index:
            idx = url_to_index[obj.source_image_url]
            mapping[idx] = f"{mapping[idx]}, {obj.name}"
        else:
            if len(urls) >= _MAX_REFERENCE_IMAGES:
                break
            urls.append(obj.source_image_url)
            idx = len(urls)
            url_to_index[obj.source_image_url] = idx
            mapping[idx] = obj.name

    return urls, mapping


def _placement_matches_objects(placement: str, names: list[str]) -> bool:
    """Check if an object_placement string matches any of the given object names.

    Object placements are formatted as "object_name: placement description".
    Uses word-token overlap to avoid false positives from short substrings
    (e.g. "cat" matching "catalog").
    """
    prefix = placement.split(":")[0].strip().lower()
    prefix_tokens = set(_tokenize(prefix))
    for name in names:
        name_lower = name.lower()
        # Exact match (case-insensitive)
        if prefix == name_lower:
            return True
        # Significant word-token overlap (> 50% of the shorter token set)
        name_tokens = set(_tokenize(name_lower))
        overlap = prefix_tokens & name_tokens
        shorter = min(len(prefix_tokens), len(name_tokens))
        if shorter > 0 and len(overlap) / shorter > 0.5:
            return True
    return False


def _tokenize(s: str) -> list[str]:
    """Split a name into word tokens by underscores, hyphens, and spaces."""
    return [t for t in re.split(r"[\s_\-]+", s) if t]


# ---------------------------------------------------------------------------
# Step 1: Full-room layout planning (1 VLM call)
# ---------------------------------------------------------------------------

_LAYOUT_PROMPT = """\
You are an expert interior designer planning a FULL room layout for dual-viewpoint \
image generation. The camera will capture TWO images from the SAME position — one \
looking forward, one looking backward (180° opposite). Different objects will be \
visible in each direction, just like turning around in a real room.

**Persona**: {persona}
**Style**: {style}
**Atmosphere**: mood={mood}, lighting={lighting}, time_of_day={time_of_day}
**Window view**: {window_view}
**Room size**: {room_size}
**Color palette**: {colors}

**Key objects that MUST be in the room** (ranked by importance):
{objects_text}

Design the FULL room layout with these constraints:

**Hard constraints**:
1. Distribute objects across the full room — some visible looking forward, others \
visible looking backward. Split them so both views have roughly balanced visual \
importance (not all the best objects in one direction).
2. Choose a fixed camera position (e.g., center of the room) and TWO opposite \
directions — forward and backward (180° apart).
3. Every key object must appear in exactly ONE view (forward OR backward).
4. IMPORTANT — counterfactual objects: If an object cannot realistically exist as a \
physical item inside a room (e.g., wild animals, natural landscapes, bodies of water, \
large vehicles, weather phenomena), represent it as a **framed photograph or artwork \
on the wall** instead of placing it literally in the room.
5. IMPORTANT — people/humans: NEVER place actual human figures in the room. Instead, \
convey their presence through **traces and signs of life** — a chair pulled back from \
the desk, a half-finished cup of coffee, an open notebook with handwriting, shoes by \
the door, a jacket tossed over a chair, etc.

**Styling guidance**:
6. Let the color palette ({colors}) guide your choices — wall tones, furniture finishes, \
and accent pieces should feel harmonious with these colors.
7. **Walls (CRITICAL)**: Walls must NOT be plain white or off-white. Choose a bold, \
specific wall treatment — deep-toned paint (forest green, navy, terracotta, charcoal), \
textured wallpaper, exposed brick, wood paneling, or a statement accent wall. Pick a \
color from the palette ({colors}) and commit to it.
8. **Flooring (CRITICAL)**: Choose a specific, characterful floor — rich dark hardwood, \
warm honey oak, patterned cement tile, herringbone parquet, or stained concrete. Add an \
area rug with color or pattern.
9. Include at least one visible warm light source in EACH view direction.
10. Design one focal point per view direction — each view should have its own visual anchor.
11. Create visual depth with interest at different heights in each direction.

Return:
- room_shape: The shape of the room (e.g., "rectangular", "L-shaped", "open plan")
- window_placement: Where the window is relative to the camera
- furniture: List of ALL major furniture pieces and their positions in the full room
- object_placements: Where EACH key object is placed (e.g., "acoustic_guitar: leaning \
against the wall to the right"). Include ALL objects.
- visual_flow: How the eye moves through each view
- camera_position: Where the camera is (e.g., "center of the room")
- camera_direction_forward: What the forward view sees
- camera_direction_backward: What the backward view sees (180° opposite)
- forward_objects: List of object NAMES visible in the forward view
- backward_objects: List of object NAMES visible in the backward view
"""


_SINGLE_VIEW_LAYOUT_PROMPT = """\
You are an expert interior designer planning a room layout for image generation. \
ALL key objects must be visible from a SINGLE camera viewpoint.

**Persona**: {persona}
**Style**: {style}
**Atmosphere**: mood={mood}, lighting={lighting}, time_of_day={time_of_day}
**Window view**: {window_view}
**Room size**: {room_size}
**Color palette**: {colors}

**Key objects that MUST be in the room** (ranked by importance):
{objects_text}

Design the room layout with these constraints:

**Hard constraints**:
1. ALL key objects must be visible from a single camera viewpoint — arrange them so \
everything fits within one wide-angle view.
2. Choose a fixed camera position (e.g., doorway or corner) and ONE direction.
3. IMPORTANT — counterfactual objects: If an object cannot realistically exist as a \
physical item inside a room (e.g., wild animals, natural landscapes, bodies of water, \
large vehicles, weather phenomena), represent it as a **framed photograph or artwork \
on the wall** instead of placing it literally in the room.
4. IMPORTANT — people/humans: NEVER place actual human figures in the room. Instead, \
convey their presence through **traces and signs of life** — a chair pulled back from \
the desk, a half-finished cup of coffee, an open notebook with handwriting, shoes by \
the door, a jacket tossed over a chair, etc.

**Styling guidance**:
5. Let the color palette ({colors}) guide your choices — wall tones, furniture finishes, \
and accent pieces should feel harmonious with these colors.
6. **Walls (CRITICAL)**: Walls must NOT be plain white or off-white. Choose a bold, \
specific wall treatment — deep-toned paint (forest green, navy, terracotta, charcoal), \
textured wallpaper, exposed brick, wood paneling, or a statement accent wall. Pick a \
color from the palette ({colors}) and commit to it.
7. **Flooring (CRITICAL)**: Choose a specific, characterful floor — rich dark hardwood, \
warm honey oak, patterned cement tile, herringbone parquet, or stained concrete. Add an \
area rug with color or pattern.
8. Include at least one visible warm light source.
9. Design one strong focal point — the view should have a clear visual anchor.
10. Create visual depth with interest at different heights.

Return:
- room_shape: The shape of the room (e.g., "rectangular", "L-shaped", "open plan")
- window_placement: Where the window is relative to the camera
- furniture: List of ALL major furniture pieces and their positions in the room
- object_placements: Where EACH key object is placed (e.g., "acoustic_guitar: leaning \
against the wall to the right"). Include ALL objects.
- visual_flow: How the eye moves through the view
- camera_position: Where the camera is (e.g., "in the doorway")
- camera_direction_forward: What the camera sees
- camera_direction_backward: (leave empty)
- forward_objects: List of ALL object NAMES (everything is in the forward view)
- backward_objects: (leave empty)
"""


async def _plan_layout(
    profile: AggregatedProfile,
    *,
    dual_view: bool = True,
) -> _FullRoomLayoutResponse:
    objects_text = "\n".join(
        f"  {i+1}. {o.name} — {o.description}"
        for i, o in enumerate(profile.key_objects)
    )

    colors = ", ".join(profile.atmosphere.color_palette) or "(varied)"

    template = _LAYOUT_PROMPT if dual_view else _SINGLE_VIEW_LAYOUT_PROMPT
    prompt = template.format(
        persona=profile.persona_summary,
        style=profile.atmosphere.style,
        mood=profile.atmosphere.dominant_mood,
        lighting=profile.atmosphere.dominant_lighting,
        time_of_day=profile.atmosphere.time_of_day,
        window_view=profile.atmosphere.window_view,
        room_size=profile.atmosphere.room_size,
        colors=colors,
        objects_text=objects_text or "(no specific objects)",
    )

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=FLASH_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_FullRoomLayoutResponse,
            temperature=0.6,
        ),
    )

    raw = response.text
    if not raw:
        logger.warning("Empty layout response")
        return _FullRoomLayoutResponse()

    return _FullRoomLayoutResponse.model_validate_json(raw)


# ---------------------------------------------------------------------------
# Step 2: Object detail descriptions (1 VLM call per view)
# ---------------------------------------------------------------------------

_OBJECT_DETAIL_PROMPT = """\
You are describing objects in a room for an image generation prompt. The room is viewed \
from a specific camera angle.

**Camera position**: {camera_position}
**Camera direction**: {camera_direction}
**Room style**: {style}
**Color palette**: {colors}

**Objects and their placements**:
{placements_text}

For each object, describe how it appears FROM THE CAMERA'S PERSPECTIVE. Include:
- name: the object name
- placement: where it sits in the frame (left, right, center, foreground, background)
- detailed_description: vivid, specific visual description as seen from the camera angle. \
Include:
  * **Material and texture**: describe tactile qualities — woven, brushed, weathered, \
polished, knitted, glazed, worn, smooth. Be specific about materials.
  * **Color role**: note whether this object serves as a dominant tone, an accent pop, or \
a neutral/grounding element within the palette ({colors}).
  * **Personal character**: describe signs of use, wear, or personality that make this \
object feel collected over time rather than bought from a catalog. A guitar with finger \
marks, a well-thumbed book, a mug with a faded print.

IMPORTANT: If an object cannot realistically exist as a physical item in a room (e.g., wild \
animals, natural landscapes, bodies of water), describe it as a framed photograph or artwork \
on the wall. For example, describe "jaguar" as "a framed photograph of a jaguar" with details \
about the frame style, print quality, and how it fits the room's aesthetic.

IMPORTANT: If an object is a person or group of people, do NOT describe them as human figures. \
Instead, describe traces of their presence — personal belongings left behind, cultural artifacts, \
a chair pulled back, an open book, a warm drink. The room should feel recently inhabited, not occupied.
"""


async def _describe_objects(
    profile: AggregatedProfile,
    layout: _FullRoomLayoutResponse,
    view: _ViewLayout,
) -> list[ObjectDetail]:
    placements = "\n".join(view.object_placements) if view.object_placements else ""
    if not placements:
        # Fallback: use object descriptions for the objects in this view
        lower_names = {n.lower() for n in view.object_names}
        obj_placements = "\n".join(
            f"  - {o.name}: {o.description}"
            for o in profile.key_objects
            if o.name.lower() in lower_names
        )
        placements = obj_placements

    colors = ", ".join(profile.atmosphere.color_palette) or "(varied)"

    prompt = _OBJECT_DETAIL_PROMPT.format(
        camera_position=layout.camera_position or "center of the room",
        camera_direction=view.camera_direction or "looking into the room",
        style=profile.atmosphere.style,
        colors=colors,
        placements_text=placements or "(no specific objects for this view)",
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
# Step 3: Final prompt assembly (1 VLM call per view)
# ---------------------------------------------------------------------------

_ASSEMBLY_PROMPT = """\
You are writing an image generation prompt for a beautifully styled room scene. The room \
should feel like it was lovingly collected and arranged over years — personal, warm, and \
full of character — not purchased as a matching set.

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
- **Walls and floor are NOT optional** — explicitly describe the wall color/material and floor \
material/color early in the prose. They set the mood for everything else. Walls must not be \
plain white. Use the color palette ({colors}) to drive these choices. Then describe warm \
lighting naturally as part of the scene, keeping the focus on the key objects.
- Include what's visible through the window if applicable to this view
- IMPORTANT: If any key object cannot realistically exist as a physical item in a room \
(e.g., wild animals, natural landscapes, bodies of water, large vehicles), describe it as \
a **framed photograph or artwork on the wall** — NOT as a literal object in the room.
- IMPORTANT: NEVER include actual human figures in the scene. If a key object is a person \
or group of people, represent them through **traces of their presence** — personal belongings, \
cultural artifacts, a chair pulled away from a desk, half-finished drinks, open journals, \
shoes by the door. The room should feel like someone just stepped out, alive with their \
personality but empty of people.
- Do NOT use bullet points or structured format — write flowing prose
- Keep it under 400 words
- IMPORTANT: The final image should look like a **magazine-quality interior photograph** — \
visually stunning, beautifully composed, with rich colors and cinematic lighting. Think \
Architectural Digest or Kinfolk magazine editorial shoot.

Return ONLY the prompt text, nothing else.
"""


async def _assemble_final_prompt(
    profile: AggregatedProfile,
    layout: _FullRoomLayoutResponse,
    view: _ViewLayout,
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
        camera_position=layout.camera_position or "center of the room",
        camera_direction=view.camera_direction or "looking into the room",
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
