"""Single-process session storage and the HTTP application's Auth adapter."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from typing import ContextManager, Iterator, Protocol

from ..services.supabase_auth import AuthResult, AuthSnapshot, SupabaseAuth


class SessionExpired(ValueError):
    pass


@dataclass
class _Session:
    snapshot: AuthSnapshot
    expires_at: float
    idle_until: float
    lock: Lock = field(default_factory=Lock, repr=False)


class SessionStore(Protocol):
    """Lease one session exclusively while its snapshot is restored or replaced."""

    def create(self, snapshot: AuthSnapshot) -> str: ...
    def locked(self, session_id: str | None) -> ContextManager[AuthSnapshot | None]: ...
    def save(self, session_id: str, snapshot: AuthSnapshot) -> None: ...
    def remove(self, session_id: str) -> None: ...


class InMemorySessionStore:
    """Process-local storage for single-worker development and acceptance tests."""

    def __init__(self, idle_seconds: int = 1800, lifetime_seconds: int = 28800):
        self._idle_seconds = idle_seconds
        self._lifetime_seconds = lifetime_seconds
        self._sessions: dict[str, _Session] = {}
        self._guard = Lock()

    @staticmethod
    def _expired(session: _Session, now: float) -> bool:
        return now >= min(session.expires_at, session.idle_until)

    def create(self, snapshot: AuthSnapshot) -> str:
        with self._guard:
            now = monotonic()
            for session_id, session in list(self._sessions.items()):
                if self._expired(session, now):
                    del self._sessions[session_id]
            session_id = token_urlsafe(32)
            self._sessions[session_id] = _Session(
                snapshot, now + self._lifetime_seconds, now + self._idle_seconds,
            )
            return session_id

    @contextmanager
    def locked(self, session_id: str | None) -> Iterator[AuthSnapshot | None]:
        with self._guard:
            session = self._sessions.get(session_id) if session_id else None
        if session is None:
            yield None
            return
        with session.lock:
            with self._guard:
                if self._sessions.get(session_id) is not session:
                    session = None
                elif self._expired(session, monotonic()):
                    del self._sessions[session_id]
                    session = None
            yield session.snapshot if session is not None else None

    def save(self, session_id: str, snapshot: AuthSnapshot) -> None:
        with self._guard:
            session = self._sessions.get(session_id)
            now = monotonic()
            if session is None or self._expired(session, now):
                self._sessions.pop(session_id, None)
                raise SessionExpired
            session.snapshot = snapshot
            session.idle_until = now + self._idle_seconds

    def remove(self, session_id: str) -> None:
        with self._guard:
            self._sessions.pop(session_id, None)


class FastAPISession:
    """Manage opaque session IDs while SupabaseAuth owns credentials and refresh."""

    def __init__(self, auth: SupabaseAuth, store: SessionStore):
        self.auth = auth
        self.store = store

    def login(self, email: str, password: str, previous_id: str | None) -> tuple[str, AuthResult]:
        result = self.auth.login(email, password)
        if previous_id:
            with self.store.locked(previous_id):
                self.store.remove(previous_id)
        return self.store.create(result.snapshot), result

    def restore(self, session_id: str | None) -> AuthResult:
        with self.store.locked(session_id) as snapshot:
            if snapshot is None or session_id is None:
                raise SessionExpired
            try:
                result = self.auth.restore(snapshot)
                self.store.save(session_id, result.snapshot)
                return result
            except Exception:
                self.store.remove(session_id)
                raise

    def logout(self, session_id: str | None) -> None:
        with self.store.locked(session_id) as snapshot:
            if snapshot is None or session_id is None:
                return
            self.store.remove(session_id)
            try:
                result = self.auth.restore(snapshot)
                self.auth.logout(result)
            except Exception:
                pass
