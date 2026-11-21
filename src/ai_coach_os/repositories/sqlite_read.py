"""SQLite implementation of the coach workspace read contract."""

from . import member_data
from .contracts import (
    CoachContext,
    ExerciseOption,
    MemberDetail,
    MemberSummary,
    TrainingHistoryExercise,
    TrainingHistoryItem,
    require_coach,
)


class SQLiteReadRepository:
    def list_members(self, coach: CoachContext) -> list[MemberSummary]:
        coach_id = require_coach(coach)
        return [
            MemberSummary(*row)
            for row in member_data.get_members_with_today_plan(coach_id)
        ]

    def get_member(self, coach: CoachContext, member_id: int) -> MemberDetail | None:
        coach_id = require_coach(coach)
        row = member_data.get_member_by_id(coach_id, member_id)
        return MemberDetail(*row) if row is not None else None

    def list_training_history(
        self, coach: CoachContext, member_id: int,
    ) -> list[TrainingHistoryItem]:
        coach_id = require_coach(coach)
        history = []
        for row in member_data.get_training_sessions_for_member(coach_id, member_id):
            exercises = tuple(
                TrainingHistoryExercise(*exercise)
                for exercise in member_data.get_exercises_for_session(coach_id, row[0])
            )
            history.append(TrainingHistoryItem(*row, exercises=exercises))
        return history

    def list_exercises(self, coach: CoachContext) -> list[ExerciseOption]:
        require_coach(coach)
        return [ExerciseOption(*row) for row in member_data.get_exercise_options()]
