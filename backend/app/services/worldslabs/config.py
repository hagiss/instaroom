"""Constants and settings for the World Labs Marble API integration."""

from __future__ import annotations

import os
from enum import StrEnum


class MarbleModel(StrEnum):
    """Available Marble generation models."""

    PLUS = "Marble 0.1-plus"
    MINI = "Marble 0.1-mini"


WORLDLABS_BASE_URL = "https://api.worldlabs.ai/marble/v1"

# Polling configuration
POLL_INTERVAL_SECONDS: float = 5.0
POLL_TIMEOUT_SECONDS: float = 600.0

# Default generation prompt
DEFAULT_TEXT_PROMPT = "A cozy room interior, explorable, with depth"

# Default camera for the 3D viewer
DEFAULT_CAMERA_POSITION: list[float] = [0.0, 1.5, 3.0]
DEFAULT_CAMERA_TARGET: list[float] = [0.0, 1.0, 0.0]


def get_api_key() -> str:
    """Read WORLDLABS_API_KEY from the environment.

    Raises RuntimeError if the key is not set so that imports succeed
    without the key (useful for tests).
    """
    key = os.environ.get("WORLDLABS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "WORLDLABS_API_KEY environment variable is not set. "
            "Get one at https://console.worldlabs.ai/"
        )
    return key
