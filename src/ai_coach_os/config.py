"""Application-wide paths and runtime defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"
DEFAULT_DB_NAME = os.getenv(
    "AI_COACH_DB_PATH",
    str(PROJECT_ROOT / "ai_coach_os.db"),
)


def runtime_setting(secrets: Mapping, name: str, default=None):
    try:
        return secrets.get(name, os.getenv(name, default))
    except FileNotFoundError as error:
        if getattr(error, "error_id", "no-secrets-found") != "no-secrets-found":
            raise ValueError("无法读取 Streamlit secrets，请检查配置文件。") from None
        return os.getenv(name, default)
    except Exception:
        raise ValueError("无法读取 Streamlit secrets，请检查配置文件。") from None
