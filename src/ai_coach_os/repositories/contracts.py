"""Read contracts shared by the application and its data adapters."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CoachContext:
    coach_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.coach_id, str) or not self.coach_id.strip():
            raise ValueError("A coach ID is required")


def require_coach(coach: CoachContext) -> str:
    if not isinstance(coach, CoachContext):
        raise TypeError("A CoachContext is required")
    return coach.coach_id


@dataclass(frozen=True)
class MemberSummary:
    id: int
    name: str
    remaining_lessons: int
    goal: str | None
    last_training_date: str | None
    ai_reminder: str | None
    # None means no scheduled appointment when the summary is available.
    today_plan_time: str | None = None
    today_plan_available: bool = True


@dataclass(frozen=True)
class MemberDetail:
    id: int
    name: str
    remaining_lessons: int
    goal: str | None
    last_training_date: str | None
    ai_reminder: str | None
    phone: str | None
    note: str | None
    created_at: str | None = None
    avatar_emoji: str | None = None


@dataclass(frozen=True)
class ExerciseOption:
    id: int
    name: str


@dataclass(frozen=True)
class TrainingHistoryExercise:
    exercise_name: str
    weight: str | None
    sets: str | None
    reps: str | None
    rpe: str | None
    note: str | None
    sort_order: int | None


@dataclass(frozen=True)
class TrainingHistoryItem:
    id: int
    training_date: str
    member_feedback: str | None
    coach_note: str | None
    raw_paste_text: str | None
    created_at: str | None
    exercises: tuple[TrainingHistoryExercise, ...] = ()


@runtime_checkable
class CoachReadRepository(Protocol):
    """Read member data within a coach scope and expose the shared catalog."""

    def list_members(self, coach: CoachContext) -> list[MemberSummary]: ...

    def get_member(self, coach: CoachContext, member_id: int) -> MemberDetail | None: ...

    def list_training_history(
        self, coach: CoachContext, member_id: int
    ) -> list[TrainingHistoryItem]: ...

    def list_exercises(self, coach: CoachContext) -> list[ExerciseOption]: ...
