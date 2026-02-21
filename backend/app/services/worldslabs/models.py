"""Pydantic v2 models for the World Labs Marble API and pipeline I/O."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .config import (
    DEFAULT_CAMERA_POSITION,
    DEFAULT_CAMERA_TARGET,
    DEFAULT_TEXT_PROMPT,
    MarbleModel,
)

# ---------------------------------------------------------------------------
# Pipeline input
# ---------------------------------------------------------------------------


class ConvertToSceneRequest(BaseModel):
    """Input for Stage 5: 2D image → 3D scene conversion."""

    image_bytes: bytes | None = None
    image_url: str | None = None
    text_prompt: str = DEFAULT_TEXT_PROMPT
    model: MarbleModel = MarbleModel.MINI
    display_name: str = "Instaroom scene"
    tags: list[str] = Field(default_factory=lambda: ["instaroom"])
    seed: int | None = None


# ---------------------------------------------------------------------------
# World Labs API models
# ---------------------------------------------------------------------------


# --- prepare_upload ---

class _MediaAsset(BaseModel):
    media_asset_id: str
    file_name: str | None = None

class _UploadInfo(BaseModel):
    upload_url: str
    upload_method: str = "PUT"
    required_headers: dict[str, str] = Field(default_factory=dict)

class PrepareUploadResponse(BaseModel):
    """Response from POST /media-assets:prepare_upload."""

    media_asset: _MediaAsset
    upload_info: _UploadInfo


# --- worlds:generate request ---

class ImagePrompt(BaseModel):
    """Reference to an image used as a generation prompt."""

    source: str  # "uri" or "media_asset"
    uri: str | None = None
    media_asset_id: str | None = None


class WorldPrompt(BaseModel):
    """Prompt bundle sent with a generation request."""

    type: str = "image"
    image_prompt: ImagePrompt | None = None
    text_prompt: str | None = None
    model: str | None = None


class GenerateWorldRequest(BaseModel):
    """Body for POST /worlds:generate."""

    display_name: str = "Instaroom scene"
    world_prompt: WorldPrompt
    tags: list[str] = Field(default_factory=list)
    seed: int | None = None


# --- worlds:generate & operations response ---

class GenerateWorldResponse(BaseModel):
    """Response from POST /worlds:generate (operation object)."""

    operation_id: str


class OperationError(BaseModel):
    """Error detail inside an operation status."""

    code: str | None = None
    message: str | None = None


class OperationResponsePayload(BaseModel):
    """Nested response inside a completed operation."""

    world_id: str
    world_marble_url: str | None = None


class OperationStatus(BaseModel):
    """Response from GET /operations/{id}."""

    operation_id: str
    done: bool = False
    error: OperationError | None = None
    response: OperationResponsePayload | None = None


# --- World asset sub-models ---


class SpzUrls(BaseModel):
    """Gaussian splat download URLs at different resolutions."""

    full_res: str | None = None
    splat_500k: str | None = Field(default=None, alias="500k")
    splat_100k: str | None = Field(default=None, alias="100k")

    model_config = {"populate_by_name": True}


class SplatAssets(BaseModel):
    spz_urls: SpzUrls | None = None


class MeshAssets(BaseModel):
    collider_mesh_url: str | None = None


class ImageryAssets(BaseModel):
    pano_url: str | None = None


class WorldAssets(BaseModel):
    caption: str | None = None
    thumbnail_url: str | None = None
    splats: SplatAssets | None = None
    mesh: MeshAssets | None = None
    imagery: ImageryAssets | None = None


class World(BaseModel):
    """World object returned by GET /worlds/{id}."""

    world_id: str
    display_name: str | None = None
    world_marble_url: str | None = None
    assets: WorldAssets | None = None
    model: str | None = None


# ---------------------------------------------------------------------------
# Pipeline output
# ---------------------------------------------------------------------------


class ViewerData(BaseModel):
    """Data needed by the front-end 3D viewer — matches the rooms API schema."""

    splat_url: str
    collider_url: str | None = None
    panorama_url: str | None = None
    camera_position: list[float] = Field(
        default_factory=lambda: list(DEFAULT_CAMERA_POSITION)
    )
    camera_target: list[float] = Field(
        default_factory=lambda: list(DEFAULT_CAMERA_TARGET)
    )


class ConvertToSceneResult(BaseModel):
    """Complete output of Stage 5."""

    viewer_data: ViewerData
    world_id: str
    world_marble_url: str | None = None
    thumbnail_url: str | None = None
