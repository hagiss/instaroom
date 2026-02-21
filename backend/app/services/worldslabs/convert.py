"""World Labs API client for converting 2D room images to explorable 3D scenes.

Supports Marble 0.1-plus (high quality) and Marble 0.1-mini (fast).
Output: Gaussian splat + collider mesh + thumbnail + panorama.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx

from .config import (
    POLL_INTERVAL_SECONDS,
    POLL_TIMEOUT_SECONDS,
    WORLDLABS_BASE_URL,
    get_api_key,
)
from .models import (
    ConvertToSceneRequest,
    ConvertToSceneResult,
    GenerateWorldRequest,
    GenerateWorldResponse,
    ImagePrompt,
    MultiImagePromptItem,
    OperationStatus,
    PrepareUploadResponse,
    ViewerData,
    World,
    WorldPrompt,
)


class WorldLabsError(Exception):
    """Any error originating from the World Labs integration."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_client() -> httpx.AsyncClient:
    """Create an httpx async client pre-configured for the Marble API."""
    return httpx.AsyncClient(
        base_url=WORLDLABS_BASE_URL,
        headers={"WLT-Api-Key": get_api_key()},
        timeout=httpx.Timeout(60.0, connect=10.0),
    )


async def _upload_image(
    client: httpx.AsyncClient,
    image_bytes: bytes,
    filename: str | None = None,
) -> str:
    """Upload an image and return its ``media_asset_id``.

    1. POST /media-assets:prepare_upload  →  signed URL + asset id
    2. PUT  signed URL                    →  upload the bytes
    """
    if filename is None:
        filename = f"instaroom-{uuid.uuid4().hex[:8]}.png"

    # Derive extension from filename
    extension = filename.rsplit(".", 1)[-1] if "." in filename else "png"

    resp = await client.post(
        "/media-assets:prepare_upload",
        json={"file_name": filename, "kind": "image", "extension": extension},
    )
    resp.raise_for_status()
    upload = PrepareUploadResponse.model_validate(resp.json())

    # Use a bare client for the PUT — the signed URL is a third-party
    # host (e.g. S3/GCS) and we must NOT send the WLT-Api-Key header there.
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as upload_client:
        put_resp = await upload_client.put(
            upload.upload_info.upload_url,
            content=image_bytes,
            headers=upload.upload_info.required_headers,
        )
        put_resp.raise_for_status()

    return upload.media_asset.media_asset_id


async def _submit_generation(
    client: httpx.AsyncClient,
    request: ConvertToSceneRequest,
    media_asset_id: str | None = None,
    media_asset_ids: list[str] | None = None,
) -> str:
    """Submit a world generation job and return its ``operation_id``.

    Supports single-image (media_asset_id) and multi-image (media_asset_ids
    with azimuth 0° forward, 180° backward) modes.
    """
    if media_asset_ids and len(media_asset_ids) >= 2:
        # Multi-image mode: forward (0°) + backward (180°)
        multi_items = [
            MultiImagePromptItem(
                azimuth=0.0,
                content=ImagePrompt(
                    source="media_asset",
                    media_asset_id=media_asset_ids[0],
                ),
            ),
            MultiImagePromptItem(
                azimuth=180.0,
                content=ImagePrompt(
                    source="media_asset",
                    media_asset_id=media_asset_ids[1],
                ),
            ),
        ]
        world_prompt = WorldPrompt(
            type="multi-image",
            multi_image_prompt=multi_items,
            text_prompt=request.text_prompt,
            model=request.model.value,
        )
    elif media_asset_id:
        image_prompt = ImagePrompt(
            source="media_asset", media_asset_id=media_asset_id
        )
        world_prompt = WorldPrompt(
            type="image",
            image_prompt=image_prompt,
            text_prompt=request.text_prompt,
            model=request.model.value,
        )
    elif request.image_url:
        image_prompt = ImagePrompt(source="uri", uri=request.image_url)
        world_prompt = WorldPrompt(
            type="image",
            image_prompt=image_prompt,
            text_prompt=request.text_prompt,
            model=request.model.value,
        )
    else:
        world_prompt = WorldPrompt(
            type="text",
            text_prompt=request.text_prompt,
            model=request.model.value,
        )

    body = GenerateWorldRequest(
        display_name=request.display_name,
        world_prompt=world_prompt,
        tags=request.tags,
        seed=request.seed,
    )

    resp = await client.post(
        "/worlds:generate",
        json=body.model_dump(exclude_none=True),
    )
    resp.raise_for_status()
    return GenerateWorldResponse.model_validate(resp.json()).operation_id


async def _poll_operation(client: httpx.AsyncClient, operation_id: str) -> str:
    """Poll an operation until completion and return the ``world_id``.

    Raises ``TimeoutError`` after ``POLL_TIMEOUT_SECONDS`` and
    ``RuntimeError`` if the API reports an error.
    """
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS

    while True:
        resp = await client.get(f"/operations/{operation_id}")
        resp.raise_for_status()
        status = OperationStatus.model_validate(resp.json())

        if status.done:
            if status.error:
                raise RuntimeError(
                    f"World generation failed: "
                    f"{status.error.code} — {status.error.message}"
                )
            if status.response is None:
                raise RuntimeError(
                    "Operation completed but response payload is missing"
                )
            return status.response.world_id

        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"World generation timed out after {POLL_TIMEOUT_SECONDS}s "
                f"(operation {operation_id})"
            )

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _get_world(client: httpx.AsyncClient, world_id: str) -> World:
    """Fetch the full world object including asset URLs."""
    resp = await client.get(f"/worlds/{world_id}")
    resp.raise_for_status()
    return World.model_validate(resp.json())


def _build_result(world: World) -> ConvertToSceneResult:
    """Map a ``World`` response to the pipeline output models."""
    # Pick best available splat URL: full_res > 500k > 100k
    splat_url: str | None = None
    if world.assets and world.assets.splats and world.assets.splats.spz_urls:
        spz = world.assets.splats.spz_urls
        splat_url = spz.full_res or spz.splat_500k or spz.splat_100k

    if not splat_url:
        raise WorldLabsError(
            f"World {world.world_id} has no splat download URLs"
        )

    collider_url = (
        world.assets.mesh.collider_mesh_url
        if world.assets and world.assets.mesh else None
    )
    panorama_url = (
        world.assets.imagery.pano_url
        if world.assets and world.assets.imagery else None
    )
    thumbnail_url = (
        world.assets.thumbnail_url
        if world.assets else None
    )

    viewer_data = ViewerData(
        splat_url=splat_url,
        collider_url=collider_url,
        panorama_url=panorama_url,
    )

    return ConvertToSceneResult(
        viewer_data=viewer_data,
        world_id=world.world_id,
        world_marble_url=world.world_marble_url,
        thumbnail_url=thumbnail_url,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def convert_to_3d_scene(
    request: ConvertToSceneRequest,
) -> ConvertToSceneResult:
    """Convert 2D room image(s) into an explorable 3D Gaussian Splatting scene.

    This is the main entry-point for Stage 5 of the Instaroom pipeline.
    Supports single-image (``image_bytes`` or ``image_url``) and multi-image
    (``image_bytes_list`` with forward + backward views at 0° and 180° azimuth).
    """
    has_multi = request.image_bytes_list and len(request.image_bytes_list) >= 2
    has_single = request.image_bytes or request.image_url

    if not has_multi and not has_single:
        raise ValueError(
            "Provide image_bytes, image_url, or image_bytes_list "
            "in ConvertToSceneRequest"
        )

    try:
        async with _build_client() as client:
            media_asset_id: str | None = None
            media_asset_ids: list[str] | None = None

            if has_multi:
                # Multi-image: upload both in parallel
                view_labels = ("fwd", "bwd")
                upload_tasks = [
                    _upload_image(client, img_bytes, f"instaroom-{view_labels[i]}.png")
                    for i, img_bytes in enumerate(request.image_bytes_list[:2])
                ]
                media_asset_ids = await asyncio.gather(*upload_tasks)
            elif request.image_bytes:
                media_asset_id = await _upload_image(client, request.image_bytes)

            # Submit generation
            operation_id = await _submit_generation(
                client, request, media_asset_id, media_asset_ids,
            )

            # Poll until done
            world_id = await _poll_operation(client, operation_id)

            # Fetch world with asset URLs
            world = await _get_world(client, world_id)

        return _build_result(world)

    except WorldLabsError:
        raise
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise WorldLabsError(f"HTTP error communicating with World Labs: {exc}") from exc
    except TimeoutError as exc:
        raise WorldLabsError(str(exc)) from exc
    except RuntimeError as exc:
        raise WorldLabsError(str(exc)) from exc
