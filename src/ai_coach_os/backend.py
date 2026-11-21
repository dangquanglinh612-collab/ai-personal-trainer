"""Runtime configuration and repository composition."""

import re
from uuid import UUID

from .config import runtime_setting
from .repositories.contracts import CoachContext, CoachReadRepository
from .services.supabase_client import AuthenticatedSupabase, SupabaseRepository, SupabaseSettings


def read_backend(secrets) -> str:
    backend = runtime_setting(secrets, "APP_DATA_BACKEND", "sqlite")
    if backend not in ("sqlite", "supabase"):
        raise ValueError("APP_DATA_BACKEND 必须为 sqlite 或 supabase")
    return backend


def read_supabase_config(secrets) -> tuple[SupabaseSettings, frozenset[str]]:
    settings = SupabaseSettings.from_mapping({
        name: runtime_setting(secrets, name)
        for name in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")
    })
    ref = runtime_setting(secrets, "SUPABASE_TEST_PROJECT_REF", "")
    if not isinstance(ref, str) or not re.fullmatch(r"[a-z0-9]{20}", ref):
        raise ValueError("请配置有效的 SUPABASE_TEST_PROJECT_REF")
    if settings.url != f"https://{ref}.supabase.co":
        raise ValueError("SUPABASE_URL 与 SUPABASE_TEST_PROJECT_REF 不匹配")
    allowed = runtime_setting(secrets, "SUPABASE_ALLOWED_COACH_IDS", "")
    try:
        if not isinstance(allowed, str):
            raise ValueError
        coach_ids = frozenset(str(UUID(item.strip())) for item in allowed.split(","))
    except ValueError:
        raise ValueError("SUPABASE_ALLOWED_COACH_IDS 必须是非空的教练 UUID 列表（逗号分隔）") from None
    return settings, coach_ids


def create_backend(
    backend: str, *,
    sqlite_coach_id: str | None = None,
    authenticated: AuthenticatedSupabase | None = None,
) -> tuple[CoachReadRepository, CoachContext]:
    if backend == "sqlite":
        from .repositories.sqlite_read import SQLiteReadRepository

        return SQLiteReadRepository(), CoachContext(sqlite_coach_id)
    if backend == "supabase":
        if not isinstance(authenticated, AuthenticatedSupabase):
            raise ValueError("创建 Supabase 仓储前必须验证当前教练会话")
        return SupabaseRepository(authenticated), authenticated.coach
    raise ValueError("APP_DATA_BACKEND 必须为 sqlite 或 supabase")
