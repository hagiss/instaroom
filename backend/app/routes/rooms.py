"""Room endpoints — fetch completed room data for viewer / shareable links."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["rooms"])


@router.get("/rooms/{room_id}")
async def get_room(room_id: str):
    """Get room data by room ID."""
    # TODO: look up room by ID
    raise HTTPException(status_code=404, detail="Room not found")


@router.get("/rooms/by-username/{username}")
async def get_room_by_username(username: str):
    """Get room data by Instagram username. Used for shareable links."""
    # TODO: look up room by username
    raise HTTPException(status_code=404, detail="Room not found")
