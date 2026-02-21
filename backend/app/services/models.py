"""Pydantic models for inter-stage data flow in the VLM pipeline.

Stage 0 models (Post, Profile, ScrapeResult) are defined in
app.services.crawler.scraper and re-exported here for convenience.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field

# Re-export Stage 0 models so consumers can import from one place
from app.services.crawler.scraper import Post, Profile, ScrapeResult

# Re-export Stage 5 output models
from app.services.worldslabs.models import ConvertToSceneResult, ViewerData

__all__ = [
    # Stage 0 (re-exports)
    "Post", "Profile", "ScrapeResult",
    # Stage 1
    "Prominence", "DetectedObject", "SceneInfo", "PeopleInfo",
    "PostAnalysis", "PostAnalysisWithMeta",
    # Stage 2
    "ScoredObject", "RoomAtmosphere", "AggregatedProfile",
    # Stage 3
    "LayoutPlan", "ObjectDetail", "ImageGenPrompt",
    # Stage 4
    "CritiqueScores", "GenerationAttempt", "ImageGenResult", "DualImageGenResult",
    # Stage 5 (re-exports)
    "ConvertToSceneResult", "ViewerData",
]


# ---------------------------------------------------------------------------
# Stage 1 — Per-post VLM analysis
# ---------------------------------------------------------------------------

class Prominence(str, enum.Enum):
    center = "center"
    background = "background"
    minor = "minor"


class DetectedObject(BaseModel):
    name: str
    prominence: Prominence
    description: str = ""


class SceneInfo(BaseModel):
    location_type: str = ""
    mood: list[str] = Field(default_factory=list)
    lighting: str = ""
    color_palette: list[str] = Field(default_factory=list)


class PeopleInfo(BaseModel):
    count: int = 0
    is_selfie: bool = False
    activity: str | None = None


class PostAnalysis(BaseModel):
    """Schema sent to Gemini for structured JSON output."""

    objects: list[DetectedObject] = Field(default_factory=list)
    scene: SceneInfo = Field(default_factory=SceneInfo)
    people: PeopleInfo = Field(default_factory=PeopleInfo)
    emotional_weight: int = Field(default=3, ge=1, le=5)
    frame_worthy: bool = False
    frame_reason: str = ""


class PostAnalysisWithMeta(BaseModel):
    """PostAnalysis enriched with post metadata for Stage 2."""

    analysis: PostAnalysis
    post_index: int
    likes: int = 0
    image_urls: list[str] = Field(default_factory=list)
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 2 — Aggregation
# ---------------------------------------------------------------------------

class ScoredObject(BaseModel):
    name: str
    importance: float = 0.0
    description: str = ""
    source_image_url: str = ""


class RoomAtmosphere(BaseModel):
    dominant_mood: str = ""
    dominant_lighting: str = ""
    color_palette: list[str] = Field(default_factory=list)
    style: str = ""
    window_view: str = ""
    room_size: str = "medium"
    time_of_day: str = "afternoon"


class AggregatedProfile(BaseModel):
    persona_summary: str = ""
    key_objects: list[ScoredObject] = Field(default_factory=list)
    atmosphere: RoomAtmosphere = Field(default_factory=RoomAtmosphere)
    hashtag_themes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 3 — Prompt design
# ---------------------------------------------------------------------------

class LayoutPlan(BaseModel):
    room_shape: str = ""
    window_placement: str = ""
    furniture: list[str] = Field(default_factory=list)
    object_placements: list[str] = Field(default_factory=list)
    visual_flow: str = ""
    camera_position: str = ""
    camera_direction: str = ""
    camera_direction_back: str = ""
    forward_objects: list[str] = Field(default_factory=list)
    backward_objects: list[str] = Field(default_factory=list)


class ObjectDetail(BaseModel):
    name: str
    placement: str = ""
    detailed_description: str = ""


class ImageGenPrompt(BaseModel):
    layout: LayoutPlan = Field(default_factory=LayoutPlan)
    object_details: list[ObjectDetail] = Field(default_factory=list)
    final_prompt: str = ""
    reference_image_urls: list[str] = Field(default_factory=list)
    reference_image_mapping: dict[int, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 4 — Image generation + critique
# ---------------------------------------------------------------------------

class CritiqueScores(BaseModel):
    object_presence: int = Field(default=3, ge=1, le=4)
    object_presence_feedback: str = ""
    atmosphere_match: int = Field(default=3, ge=1, le=4)
    atmosphere_match_feedback: str = ""
    spatial_coherence: int = Field(default=3, ge=1, le=4)
    spatial_coherence_feedback: str = ""
    overall_quality: int = Field(default=3, ge=1, le=4)
    overall_quality_feedback: str = ""

    @property
    def avg_score(self) -> float:
        return (
            self.object_presence
            + self.atmosphere_match
            + self.spatial_coherence
            + self.overall_quality
        ) / 4.0


class GenerationAttempt(BaseModel):
    attempt_number: int
    image_base64: str = ""
    critique: CritiqueScores | None = None
    prompt_used: str = ""


class ImageGenResult(BaseModel):
    final_image_base64: str = ""
    final_critique: CritiqueScores | None = None
    attempts: list[GenerationAttempt] = Field(default_factory=list)
    total_attempts: int = 0


class DualImageGenResult(BaseModel):
    forward: ImageGenResult = Field(default_factory=ImageGenResult)
    backward: ImageGenResult = Field(default_factory=ImageGenResult)
