from fastapi import APIRouter

router = APIRouter(prefix="/generate", tags=["generate"])


@router.post("/")
async def generate_room(username: str):
    """Full pipeline: crawl -> analyze -> generate image -> convert to 3D."""
    # TODO: orchestrate the full pipeline
    return {"username": username, "status": "not_implemented"}
