"""Application-wide paths and runtime defaults."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"
DEFAULT_DB_NAME = os.getenv(
    "AI_COACH_DB_PATH",
    str(PROJECT_ROOT / "ai_coach_os.db"),
)
