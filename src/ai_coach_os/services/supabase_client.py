"""Stage A session-local Supabase adapter; not wired into the SQLite UI yet."""

from dataclasses import dataclass, field
from urllib.parse import urlparse
from uuid import UUID, uuid4


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    publishable_key: str = field(repr=False)

    def __post_init__(self):
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.path or parsed.fragment:
            raise ValueError("SUPABASE_URL 必须是 HTTPS 项目根地址")
        if not self.publishable_key.startswith("sb_publishable_"):
            raise ValueError("请配置 Publishable Key，禁止使用 Secret Key 作为应用客户端")

    @classmethod
    def from_mapping(cls, values):
        url = str(values.get("SUPABASE_URL", "")).rstrip("/")
        key = str(values.get("SUPABASE_PUBLISHABLE_KEY", ""))
        return cls(url, key)


def create_public_client(settings):
    # No global cache, no disk session storage, no background refresh thread.
    from supabase import ClientOptions, create_client
    return create_client(settings.url, settings.publishable_key, options=ClientOptions(
        persist_session=False, auto_refresh_token=False,
    ))


class SupabaseSession:
    """Instantiate per rerun with that browser's session_state, never cache globally."""

    def __init__(self, settings, state, factory=create_public_client):
        self.settings, self.state, self.factory = settings, state, factory

    def _accept(self, client, response):
        session = response.session
        user = client.auth.get_user(session.access_token).user
        user_id = str(UUID(user.id))
        previous = self.state.get("coach_id")
        if previous and previous != user_id:
            self.state.clear()
        self.state.update({"auth_user": {"id": user_id}, "coach_id": user_id,
                           "access_token": session.access_token,
                           "refresh_token": session.refresh_token, "logged_in": True})
        return client

    def login(self, email, password):
        self.state.clear()
        try:
            client = self.factory(self.settings)
            response = client.auth.sign_in_with_password({"email": email, "password": password})
            self._accept(client, response)
            client.table("profiles").upsert(
                {"id": self.state["coach_id"]}, on_conflict="id", ignore_duplicates=True,
            ).execute()
            return client
        except Exception:
            self.state.clear()
            raise ValueError("登录失败，请检查账号、密码或网络连接。") from None

    def restore(self):
        try:
            client = self.factory(self.settings)
            response = client.auth.set_session(self.state["access_token"], self.state["refresh_token"])
            return self._accept(client, response)
        except Exception:
            self.state.clear()
            raise ValueError("登录状态失效，请重新登录。") from None

    def logout(self):
        try:
            self.restore().auth.sign_out()
        except Exception:
            pass
        finally:
            # Includes tokens, plan_* widgets, member forms and TASK 9 drafts.
            self.state.clear()


class SupabaseRepository:
    """Independent stage-A interface. Identity comes from Auth, not page arguments."""

    def __init__(self, client):
        self.client = client
        self.coach_id = str(UUID(client.auth.get_user().user.id))

    def get_members_for_coach(self):
        return self.client.table("members").select("*").eq("coach_id", self.coach_id).order("id").execute().data

    def add_member(self, name, remaining_lessons, goal):
        return self.client.table("members").insert({
            "coach_id": self.coach_id, "name": name,
            "remaining_lessons": remaining_lessons, "goal": goal,
        }).execute().data

    def save_training_session(self, member_id, training_date, member_feedback, coach_note,
                              raw_paste_text, exercise_rows, session_id=None):
        return self.client.rpc("save_training_session_transaction", {
            "p_member_id": member_id, "p_training_date": str(training_date),
            "p_member_feedback": member_feedback, "p_coach_note": coach_note,
            "p_raw_paste_text": raw_paste_text, "p_exercises": exercise_rows,
            "p_session_id": session_id,
        }).execute().data

    def create_appointment(self, member_id, appointment_date, start_time, end_time, note=""):
        # GiST exclusion constraint checks concurrent INSERT/UPDATE and status changes.
        return self.client.table("appointments").insert({
            "coach_id": self.coach_id, "member_id": member_id,
            "appointment_date": str(appointment_date), "start_time": str(start_time),
            "end_time": str(end_time), "note": note,
        }).execute().data

    def upload_photo(self, member_id, session_id, content, extension, original_filename="", caption=""):
        if extension.lower() not in (".jpg", ".jpeg", ".png") or not content:
            raise ValueError("照片格式不支持或文件为空")
        sessions = self.client.table("training_sessions").select("id").eq("id", session_id).eq(
            "member_id", member_id).eq("coach_id", self.coach_id).execute().data
        if not sessions:
            raise ValueError("训练记录不可用")
        path = f"{self.coach_id}/{int(member_id)}/{int(session_id)}/{uuid4()}{extension.lower()}"
        bucket = self.client.storage.from_("training-photos")
        bucket.upload(path, content, file_options={"content-type": "image/png" if extension.lower() == ".png" else "image/jpeg", "upsert": "false"})
        try:
            return self.client.table("training_session_photos").insert({
                "coach_id": self.coach_id, "member_id": member_id, "session_id": session_id,
                "bucket_name": "training-photos", "object_path": path,
                "original_filename": original_filename, "caption": caption,
            }).execute().data
        except Exception:
            try:
                bucket.remove([path])
            except Exception:
                pass  # Orphan reconciliation is documented; training save is unaffected.
            raise ValueError("照片元数据保存失败，请重试。") from None

    def photo_url(self, object_path):
        parts = object_path.split("/")
        if len(parts) != 4 or parts[0] != self.coach_id or any(p in ("", ".", "..") for p in parts):
            raise ValueError("照片路径不属于当前用户")
        return self.client.storage.from_("training-photos").create_signed_url(object_path, 300)["signedURL"]
