"""Run the actual ASGI routes with synthetic Auth and repository data for Chrome."""

import sys
from pathlib import Path
from unittest.mock import patch

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_coach_os.repositories.contracts import (  # noqa: E402
    CoachContext, MemberDetail, MemberSummary, TrainingHistoryExercise, TrainingHistoryItem,
)
from ai_coach_os.services.supabase_auth import AuthenticatedSupabase, AuthResult, AuthSnapshot  # noqa: E402
from ai_coach_os.web.app import create_app  # noqa: E402


class FixtureAuth:
    def login(self, email, password):
        if email not in {"a@example.invalid", "b@example.invalid"} or password != "local-fixture":
            raise ValueError("Fixture rejected")
        return self.restore(AuthSnapshot("fixture", email, 4_000_000_000, "fixture-access", "fixture-refresh"))

    def restore(self, snapshot):
        return AuthResult(AuthenticatedSupabase(object(), CoachContext(snapshot.user_id)), snapshot)

    def logout(self, result):
        pass


class FixtureRepository:
    saved = {}

    def __init__(self, authenticated):
        self.coach = authenticated.coach

    def get_member(self, coach, member_id):
        own_id = 101 if self.coach.coach_id == "a@example.invalid" else 202
        if coach != self.coach or member_id != own_id:
            return None
        name = "Member A" if own_id == 101 else "Member B"
        return MemberDetail(
            member_id, name, 0, "力量", "2026-11-14", "复查练习", "000-000",
            "<img src=x onerror=alert(1)>", "2026-11-01T08:00:00Z", "A" if own_id == 101 else "B",
        )

    def list_members(self, coach):
        member_id = 101 if self.coach.coach_id == "a@example.invalid" else 202
        member = self.get_member(coach, member_id)
        return [MemberSummary(member.id, member.name, member.remaining_lessons,
                              member.goal, member.last_training_date, member.ai_reminder)]

    def list_training_history(self, coach, member_id):
        assert self.get_member(coach, member_id)
        return [*self.saved.get(member_id, ()), TrainingHistoryItem(
            1, "2026-11-14", "会员反馈样例", "教练备注样例", None, None,
            (TrainingHistoryExercise("深蹲", "30 kg", "3", "8", "7", "动作备注样例", 1),),
        )]

    def save_training_session(self, member_id, training_date, member_feedback, coach_note,
                              raw_paste_text, exercise_rows):
        assert self.get_member(self.coach, member_id)
        records = self.saved.setdefault(member_id, [])
        record = TrainingHistoryItem(
            len(records) + 2, str(training_date), member_feedback, coach_note, None, None,
            tuple(TrainingHistoryExercise(**row, sort_order=i) for i, row in enumerate(exercise_rows)),
        )
        first = all(row.training_date != record.training_date for row in records)
        records.insert(0, record)
        return {"session_id": record.id, "should_deduct_lesson": first}


if __name__ == "__main__":
    port = int(sys.argv[1])
    host = "127.0.0.1"
    app = create_app(auth=FixtureAuth(), repository_factory=FixtureRepository,
                     origin=f"http://{host}:{port}")
    with patch("ai_coach_os.services.supabase_auth.create_public_client",
               side_effect=AssertionError("No live Supabase client in browser tests")):
        uvicorn.run(app, host=host, port=port, access_log=False)
