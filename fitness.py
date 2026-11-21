"""Stable Streamlit entry point and backward-compatible public API.

The implementation lives in ``src/ai_coach_os``. Keeping this small module at
the repository root preserves the existing ``streamlit run fitness.py`` command
and the public helpers used by the regression suite.
"""

from __future__ import annotations

import json
import os
import sys
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_coach_os import application
from ai_coach_os import auth as _auth
from ai_coach_os.repositories import appointments as _appointments
from ai_coach_os.repositories import database as _database
from ai_coach_os.repositories import member_data as _member_data
from ai_coach_os.repositories.contracts import MemberSummary as _MemberSummary
from ai_coach_os.services import ai as _ai
from ai_coach_os.ui import helpers as _helpers
from ai_coach_os.ui import pages as _pages
from ai_coach_os.ui import styles as _styles


DB_NAME = _database.DB_NAME
_LEGACY_TEST_MODULES = (json, os)
_PUBLIC_MODULES: tuple[ModuleType, ...] = (
    _database,
    _appointments,
    _member_data,
    _auth,
    _ai,
    _helpers,
    _styles,
    _pages,
)


def _sync_runtime_configuration() -> None:
    """Apply legacy runtime overrides to the modular implementation."""

    _database.DB_NAME = DB_NAME
    _database.PROJECT_ROOT = Path(__file__).resolve().parent


def _proxy(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        _sync_runtime_configuration()
        return function(*args, **kwargs)

    return wrapped


def __getattr__(name: str) -> Any:
    """Expose the former single-file helpers without duplicating business code."""

    for module in _PUBLIC_MODULES:
        value = module.__dict__.get(name)
        if value is not None:
            return _proxy(value) if callable(value) else value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    exported = {
        name
        for module in _PUBLIC_MODULES
        for name in module.__dict__
        if not name.startswith("__")
    }
    return sorted(set(globals()) | exported)


def filter_members(members, keyword, selected_filter):
    """Keep accepting the rows returned by the legacy member query."""
    rows = list(members)
    summaries = [_MemberSummary(*row) for row in rows]
    matched = set(_helpers.filter_members(summaries, keyword, selected_filter))
    return [row for row, summary in zip(rows, summaries) if summary in matched]


def main() -> None:
    _sync_runtime_configuration()
    application.main()


if __name__ == "__main__":
    main()
