"""Supabase authentication for callers that own their session state."""

from dataclasses import dataclass, field
import re
from time import time
from uuid import UUID

from ..repositories.contracts import CoachContext


_REFRESH_MARGIN_SECONDS = 30


class CoachNotAllowed(PermissionError):
    pass


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    publishable_key: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.url, str) or not self.url:
            raise ValueError("缺少 SUPABASE_URL")
        if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", self.url):
            raise ValueError("SUPABASE_URL 必须是 Supabase 的 HTTPS 项目根地址")
        if not isinstance(self.publishable_key, str) or not self.publishable_key:
            raise ValueError("缺少 SUPABASE_PUBLISHABLE_KEY")
        if not re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", self.publishable_key):
            raise ValueError("SUPABASE_PUBLISHABLE_KEY 必须是 Publishable Key")

    @classmethod
    def from_mapping(cls, values):
        url = values.get("SUPABASE_URL")
        if isinstance(url, str):
            url = url.removesuffix("/")
        key = values.get("SUPABASE_PUBLISHABLE_KEY")
        return cls(url, key)


def create_public_client(settings):
    # No global cache, no disk session storage, no background refresh thread.
    from supabase import ClientOptions, create_client
    return create_client(settings.url, settings.publishable_key, options=ClientOptions(
        persist_session=False, auto_refresh_token=False,
    ))


@dataclass(frozen=True)
class AuthenticatedSupabase:
    client: object = field(repr=False)
    coach: CoachContext


@dataclass(frozen=True)
class AuthSnapshot:
    project_url: str
    user_id: str
    expires_at: int
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


@dataclass(frozen=True)
class AuthResult:
    authenticated: AuthenticatedSupabase
    snapshot: AuthSnapshot


class SupabaseAuth:
    """Create one authenticated client and its matching snapshot per operation."""

    def __init__(self, settings, allowed_coach_ids, factory=create_public_client):
        self.settings = settings
        self.allowed_coach_ids = frozenset(allowed_coach_ids)
        self.factory = factory

    def _accept(self, client, response, expected_user_id=None) -> AuthResult:
        session = response.session
        if not session or not session.access_token or not session.refresh_token or session.expires_at <= time():
            raise ValueError("Supabase 会话无效或已过期")
        user = client.auth.get_user(session.access_token).user
        user_id = str(UUID(user.id))
        if user.is_anonymous or user_id not in self.allowed_coach_ids:
            raise CoachNotAllowed("此账号未获准进入教练工作台。")
        if expected_user_id is not None and expected_user_id != user_id:
            raise ValueError("Supabase 会话身份已变化")
        return AuthResult(
            authenticated=AuthenticatedSupabase(client, CoachContext(user_id)),
            snapshot=AuthSnapshot(
                project_url=self.settings.url,
                user_id=user_id,
                expires_at=session.expires_at,
                access_token=session.access_token,
                refresh_token=session.refresh_token,
            ),
        )

    def login(self, email: str, password: str) -> AuthResult:
        try:
            client = self.factory(self.settings)
            response = client.auth.sign_in_with_password({"email": email, "password": password})
            return self._accept(client, response)
        except CoachNotAllowed:
            raise CoachNotAllowed("此账号未获准进入教练工作台。") from None
        except Exception:
            raise ValueError("登录失败，请检查账号、密码或网络连接。") from None

    def restore(self, snapshot: AuthSnapshot) -> AuthResult:
        try:
            if snapshot.project_url != self.settings.url:
                raise ValueError("Supabase 会话项目不匹配")
            expected_user_id = str(UUID(snapshot.user_id))
            if expected_user_id not in self.allowed_coach_ids:
                raise CoachNotAllowed("此账号未获准进入教练工作台。")
            if not snapshot.access_token or not snapshot.refresh_token:
                raise ValueError("Supabase 会话令牌缺失")
            client = self.factory(self.settings)
            if snapshot.expires_at <= time() + _REFRESH_MARGIN_SECONDS:
                response = client.auth.refresh_session(snapshot.refresh_token)
            else:
                response = client.auth.set_session(snapshot.access_token, snapshot.refresh_token)
            return self._accept(client, response, expected_user_id)
        except CoachNotAllowed:
            raise CoachNotAllowed("此账号未获准进入教练工作台。") from None
        except Exception:
            raise ValueError("登录状态失效，请重新登录。") from None

    def logout(self, result: AuthResult) -> None:
        if result.snapshot.project_url != self.settings.url:
            raise ValueError("Supabase 会话项目不匹配")
        try:
            result.authenticated.client.auth.admin.sign_out(result.snapshot.access_token, "local")
        except Exception:
            raise ValueError("无法撤销 Supabase 会话。") from None
