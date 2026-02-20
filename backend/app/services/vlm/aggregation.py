"""Stage 2: Aggregation of per-post analyses into a unified persona profile.

Combines VLM-based object deduplication, importance scoring,
and room atmosphere derivation.
"""

from __future__ import annotations

import logging
from collections import Counter

from google.genai import types
from pydantic import BaseModel, Field

from app.services.gemini_client import FLASH_MODEL, get_gemini_client
from app.services.models import (
    AggregatedProfile,
    PostAnalysisWithMeta,
    ProfileData,
    Prominence,
    RoomAtmosphere,
    ScoredObject,
)

logger = logging.getLogger(__name__)

_TOP_OBJECTS = 8


# ---------------------------------------------------------------------------
# VLM response schemas (internal)
# ---------------------------------------------------------------------------

class _DedupGroup(BaseModel):
    canonical: str
    variants: list[str]


class _DedupResponse(BaseModel):
    groups: list[_DedupGroup]


class _AggregationVLMResponse(BaseModel):
    persona_summary: str = ""
    style: str = ""
    window_view: str = ""
    time_of_day: str = ""
    hashtag_themes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def aggregate_analyses(
    analyses: list[PostAnalysisWithMeta],
    profile: ProfileData,
) -> AggregatedProfile:
    """Aggregate per-post analyses into a single persona profile.

    Makes 2 VLM calls: object deduplication + persona synthesis.
    """
    # Step 1: VLM-based object deduplication
    all_object_names = _collect_object_names(analyses)
    dedup_map = await _deduplicate_objects(all_object_names)

    # Step 2: Deterministic scoring
    scored_objects = _score_objects(analyses, dedup_map)

    # Step 3: Deterministic atmosphere derivation
    atmosphere = _derive_atmosphere_deterministic(analyses)

    # Step 4: VLM synthesis for persona + atmosphere refinement
    vlm_response = await _synthesize_persona(
        scored_objects, atmosphere, profile, analyses,
    )

    # Merge VLM output into atmosphere
    atmosphere.style = vlm_response.style or atmosphere.style
    atmosphere.window_view = vlm_response.window_view
    atmosphere.time_of_day = vlm_response.time_of_day or atmosphere.time_of_day

    return AggregatedProfile(
        persona_summary=vlm_response.persona_summary,
        key_objects=scored_objects,
        atmosphere=atmosphere,
        hashtag_themes=vlm_response.hashtag_themes,
    )


# ---------------------------------------------------------------------------
# Object deduplication (1 VLM call)
# ---------------------------------------------------------------------------

def _collect_object_names(analyses: list[PostAnalysisWithMeta]) -> list[str]:
    """Get all unique object names across posts."""
    names: set[str] = set()
    for a in analyses:
        for obj in a.analysis.objects:
            names.add(obj.name)
    return sorted(names)


_DEDUP_PROMPT = """\
You are a semantic deduplication expert. Given this list of object names extracted \
from Instagram posts, group together names that refer to the same real-world object \
type. For example, "acoustic_guitar", "guitar", "electric_guitar" should all map to \
"guitar". "orange_cat", "tabby_cat", "cat" should map to "cat".

Object names:
{object_names}

Return groups where each group has a canonical name and its variants. \
Only group names that are genuinely the same type of object. \
If an object has no duplicates, still include it as a group of one.
"""


async def _deduplicate_objects(names: list[str]) -> dict[str, str]:
    """Ask VLM to group semantically similar object names.

    Returns a mapping of raw_name → canonical_name.
    """
    if len(names) <= 1:
        return {n: n for n in names}

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=FLASH_MODEL,
        contents=_DEDUP_PROMPT.format(object_names="\n".join(f"- {n}" for n in names)),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_DedupResponse,
            temperature=0.1,
        ),
    )

    raw = response.text
    if not raw:
        logger.warning("Empty dedup response, using identity mapping")
        return {n: n for n in names}

    dedup = _DedupResponse.model_validate_json(raw)

    mapping: dict[str, str] = {}
    for group in dedup.groups:
        for variant in group.variants:
            mapping[variant] = group.canonical
        mapping[group.canonical] = group.canonical

    # Ensure all original names are mapped
    for n in names:
        if n not in mapping:
            mapping[n] = n

    return mapping


# ---------------------------------------------------------------------------
# Deterministic scoring
# ---------------------------------------------------------------------------

_PROMINENCE_SCORE = {
    Prominence.center: 1.0,
    Prominence.background: 0.5,
    Prominence.minor: 0.2,
}


def _score_objects(
    analyses: list[PostAnalysisWithMeta],
    dedup_map: dict[str, str],
) -> list[ScoredObject]:
    """Score objects by importance and return the top N.

    importance = frequency×0.3 + avg_prominence×0.25 + avg_emotional_weight×0.25 + normalized_likes×0.2
    """
    # Collect per-object stats
    object_stats: dict[str, dict] = {}  # canonical_name → stats

    max_likes = max((a.likes for a in analyses), default=1) or 1

    for a in analyses:
        for obj in a.analysis.objects:
            canonical = dedup_map.get(obj.name, obj.name)
            if canonical not in object_stats:
                object_stats[canonical] = {
                    "count": 0,
                    "prominences": [],
                    "emotional_weights": [],
                    "likes": [],
                    "descriptions": [],
                    "best_prominence": 0.0,
                    "best_image_url": "",
                }
            stats = object_stats[canonical]
            stats["count"] += 1
            prom_score = _PROMINENCE_SCORE.get(obj.prominence, 0.2)
            stats["prominences"].append(prom_score)
            stats["emotional_weights"].append(a.analysis.emotional_weight)
            stats["likes"].append(a.likes)
            if obj.description:
                stats["descriptions"].append(obj.description)

            # Track which image shows this object most prominently
            if prom_score > stats["best_prominence"] and a.image_urls:
                stats["best_prominence"] = prom_score
                stats["best_image_url"] = a.image_urls[0]

    if not object_stats:
        return []

    max_count = max(s["count"] for s in object_stats.values()) or 1

    scored: list[ScoredObject] = []
    for name, stats in object_stats.items():
        freq = stats["count"] / max_count
        avg_prom = sum(stats["prominences"]) / len(stats["prominences"])
        avg_emo = (sum(stats["emotional_weights"]) / len(stats["emotional_weights"])) / 5.0
        avg_likes = (sum(stats["likes"]) / len(stats["likes"])) / max_likes

        importance = freq * 0.3 + avg_prom * 0.25 + avg_emo * 0.25 + avg_likes * 0.2

        description = stats["descriptions"][0] if stats["descriptions"] else ""

        scored.append(ScoredObject(
            name=name,
            importance=round(importance, 4),
            description=description,
            source_image_url=stats["best_image_url"],
        ))

    scored.sort(key=lambda x: x.importance, reverse=True)
    return scored[:_TOP_OBJECTS]


# ---------------------------------------------------------------------------
# Deterministic atmosphere
# ---------------------------------------------------------------------------

def _derive_atmosphere_deterministic(
    analyses: list[PostAnalysisWithMeta],
) -> RoomAtmosphere:
    """Derive room atmosphere from Counter-based aggregation."""
    moods: Counter[str] = Counter()
    lightings: Counter[str] = Counter()
    locations: Counter[str] = Counter()
    colors: Counter[str] = Counter()

    for a in analyses:
        scene = a.analysis.scene
        for m in scene.mood:
            moods[m] += 1
        if scene.lighting:
            lightings[scene.lighting] += 1
        if scene.location_type:
            locations[scene.location_type] += 1
        for c in scene.color_palette:
            colors[c] += 1

    dominant_mood = moods.most_common(1)[0][0] if moods else "warm"
    dominant_lighting = lightings.most_common(1)[0][0] if lightings else "natural"
    top_colors = [c for c, _ in colors.most_common(5)]

    return RoomAtmosphere(
        dominant_mood=dominant_mood,
        dominant_lighting=dominant_lighting,
        color_palette=top_colors,
    )


# ---------------------------------------------------------------------------
# VLM persona synthesis (1 VLM call)
# ---------------------------------------------------------------------------

_SYNTHESIS_PROMPT = """\
You are a creative interior designer and persona analyst. Based on the following data \
about an Instagram user, synthesize a cohesive persona profile for designing their ideal room.

**User bio**: {bio}
**Username**: {username}
**Follower count**: {followers}

**Top objects found across their posts** (ranked by importance):
{objects_text}

**Dominant atmosphere from their posts**:
- Mood: {mood}
- Lighting: {lighting}
- Top location types: {locations}
- Color palette: {colors}

**Most common hashtag themes**: {hashtags}

Return:
- persona_summary: A 2-3 sentence summary of who this person is and what their ideal room would feel like. Be specific and vivid.
- style: An interior design style label (e.g., "scandinavian_minimal", "bohemian_eclectic", "industrial_modern", "cozy_vintage")
- window_view: What should be visible through the room's window (e.g., "city_skyline", "ocean", "forest", "garden", "mountains", "urban_street")
- time_of_day: When this room feels most alive (e.g., "morning", "afternoon", "golden_hour", "evening", "night")
- hashtag_themes: Top 5 thematic keywords summarizing this person's interests
"""


async def _synthesize_persona(
    scored_objects: list[ScoredObject],
    atmosphere: RoomAtmosphere,
    profile: ProfileData,
    analyses: list[PostAnalysisWithMeta],
) -> _AggregationVLMResponse:
    """Use VLM to create a persona summary and refine atmosphere."""
    # Collect hashtag stats
    hashtag_counter: Counter[str] = Counter()
    location_counter: Counter[str] = Counter()
    for a in analyses:
        for h in a.hashtags:
            hashtag_counter[h] += 1
        if a.analysis.scene.location_type:
            location_counter[a.analysis.scene.location_type] += 1

    objects_text = "\n".join(
        f"  {i+1}. {o.name} (importance: {o.importance:.2f}) — {o.description}"
        for i, o in enumerate(scored_objects)
    )
    top_hashtags = [h for h, _ in hashtag_counter.most_common(10)]
    top_locations = [loc for loc, _ in location_counter.most_common(5)]

    prompt = _SYNTHESIS_PROMPT.format(
        bio=profile.biography or "(no bio)",
        username=profile.username,
        followers=profile.follower_count,
        objects_text=objects_text or "(none detected)",
        mood=atmosphere.dominant_mood,
        lighting=atmosphere.dominant_lighting,
        locations=", ".join(top_locations) or "(varied)",
        colors=", ".join(atmosphere.color_palette) or "(varied)",
        hashtags=", ".join(top_hashtags) or "(none)",
    )

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=FLASH_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_AggregationVLMResponse,
            temperature=0.5,
        ),
    )

    raw = response.text
    if not raw:
        logger.warning("Empty synthesis response, using defaults")
        return _AggregationVLMResponse()

    return _AggregationVLMResponse.model_validate_json(raw)
