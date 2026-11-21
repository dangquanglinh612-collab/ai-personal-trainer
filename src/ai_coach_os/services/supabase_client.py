"""Supabase repositories and compatibility imports for authentication."""

from uuid import uuid4

from ..repositories.contracts import (
    CoachContext,
    ExerciseOption,
    MemberDetail,
    MemberSummary,
    TrainingHistoryExercise,
    TrainingHistoryItem,
    require_coach,
)
from .streamlit_session import SupabaseSession as SupabaseSession
from .supabase_auth import (
    AuthenticatedSupabase as AuthenticatedSupabase,
    CoachNotAllowed as CoachNotAllowed,
    SupabaseSettings as SupabaseSettings,
    create_public_client as create_public_client,
)

_MEMBER_FIELDS = "id,name,remaining_lessons,goal,last_training_date,ai_reminder"
_HISTORY_FIELDS = (
    "id,training_date,member_feedback,coach_note,raw_paste_text,created_at,"
    "training_session_exercises(exercise_name,weight,sets,reps,rpe,note,sort_order)"
)


class SupabaseRepository:
    """Authenticated reads and existing Stage A operations."""

    def __init__(self, authenticated: AuthenticatedSupabase):
        self.client = authenticated.client
        self.coach_id = authenticated.coach.coach_id

    def _require_owner(self, coach: CoachContext) -> str:
        if require_coach(coach) != self.coach_id:
            raise PermissionError("教练上下文与当前登录用户不一致。")
        return self.coach_id

    def _member_query(self, columns: str):
        return self.client.table("members").select(columns).eq("coach_id", self.coach_id)

    def list_members(self, coach: CoachContext) -> list[MemberSummary]:
        self._require_owner(coach)
        rows = self._member_query(_MEMBER_FIELDS).order("id", desc=True).execute().data
        return [MemberSummary(**row, today_plan_available=False) for row in rows]

    def get_member(self, coach: CoachContext, member_id: int) -> MemberDetail | None:
        self._require_owner(coach)
        if type(member_id) is not int or not 0 < member_id < 2**63:
            raise ValueError("会员编号无效。")
        rows = (
            self._member_query(f"{_MEMBER_FIELDS},phone,note,created_at,avatar_emoji")
            .eq("id", member_id)
            .limit(1)
            .execute().data
        )
        return MemberDetail(**rows[0]) if rows else None

    def list_training_history(
        self, coach: CoachContext, member_id: int,
    ) -> list[TrainingHistoryItem]:
        coach_id = self._require_owner(coach)
        child_relation = "training_session_exercises"
        rows = (
            self.client.table("training_sessions")
            .select(_HISTORY_FIELDS)
            .eq("coach_id", coach_id)
            .eq("member_id", member_id)
            .order("training_date", desc=True)
            .order("id", desc=True)
            .order("sort_order", nullsfirst=True, foreign_table=child_relation)
            .order("id", foreign_table=child_relation)
            .execute().data
        )
        history = []
        for row in rows:
            exercises = tuple(TrainingHistoryExercise(**item) for item in row[child_relation])
            session = {key: value for key, value in row.items() if key != child_relation}
            history.append(TrainingHistoryItem(**session, exercises=exercises))
        return history

    def list_exercises(self, coach: CoachContext) -> list[ExerciseOption]:
        self._require_owner(coach)
        rows = (
            self.client.table("exercise_library")
            .select("id,name")
            .order("id")
            .execute().data
        )
        return [ExerciseOption(**row) for row in rows]

    def get_members_for_coach(self):
        return self._member_query("*").order("id").execute().data

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
