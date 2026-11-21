"""Map Supabase authentication results to Streamlit's per-browser state."""

from .supabase_auth import AuthResult, AuthSnapshot, SupabaseAuth, create_public_client


class SupabaseSession:
    """Keep the Streamlit session API and its existing state keys."""

    def __init__(self, settings, state, allowed_coach_ids, factory=create_public_client):
        self.state = state
        self.auth = SupabaseAuth(settings, allowed_coach_ids, factory)
        self._result: AuthResult | None = None

    @property
    def authenticated(self):
        return self._result.authenticated if self._result is not None else None

    def _clear(self):
        self._result = None
        backend = self.state.get("_app_backend")
        self.state.clear()
        if backend is not None:
            self.state["_app_backend"] = backend

    def _store(self, result: AuthResult):
        snapshot = result.snapshot
        self.state.update({
            "auth_user": {"id": snapshot.user_id},
            "auth_project": snapshot.project_url,
            "coach_id": snapshot.user_id,
            "auth_expires_at": snapshot.expires_at,
            "access_token": snapshot.access_token,
            "refresh_token": snapshot.refresh_token,
            "logged_in": True,
        })
        self._result = result
        return result.authenticated

    def login(self, email, password):
        self._clear()
        return self._store(self.auth.login(email, password))

    def restore(self):
        try:
            snapshot = AuthSnapshot(
                project_url=self.state["auth_project"],
                user_id=self.state["auth_user"]["id"],
                expires_at=self.state["auth_expires_at"],
                access_token=self.state["access_token"],
                refresh_token=self.state["refresh_token"],
            )
        except (KeyError, TypeError):
            self._clear()
            raise ValueError("登录状态失效，请重新登录。") from None
        try:
            return self._store(self.auth.restore(snapshot))
        except Exception:
            self._clear()
            raise

    def logout(self):
        try:
            if self._result is not None:
                self.auth.logout(self._result)
        except ValueError:
            pass
        finally:
            self._clear()
