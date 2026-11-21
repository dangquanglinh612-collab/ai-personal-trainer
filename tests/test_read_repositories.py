from contextlib import closing
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_coach_os.repositories import database
from ai_coach_os.repositories.contracts import (
    CoachContext,
    CoachReadRepository,
    ExerciseOption,
    MemberDetail,
    MemberSummary,
    TrainingHistoryExercise,
    TrainingHistoryItem,
)
from ai_coach_os.repositories.sqlite_read import SQLiteReadRepository


class SQLiteReadRepositoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db_path = Path(directory.name) / "workspace.db"
        patch = mock.patch.object(database, "DB_NAME", str(db_path))
        patch.start()
        self.addCleanup(patch.stop)
        database.init_db()
        self.repo = SQLiteReadRepository()
        self.coach_a = CoachContext("read-coach-a")
        self.coach_b = CoachContext("read-coach-b")

        today = date.today().isoformat()
        with closing(database.get_conn()) as conn, conn:
            conn.executemany(
                """INSERT INTO members
                   (id, coach_id, name, remaining_lessons, last_training_date, phone, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (101, self.coach_a.coach_id, "First today", 0, None, "", "Private note"),
                    (102, self.coach_a.coach_id, "Later today", 3, "", "", ""),
                    (103, self.coach_a.coach_id, "Unbooked A", 5, "", "", ""),
                    (104, self.coach_a.coach_id, "Unbooked B", 5, "", "", ""),
                    (201, self.coach_b.coach_id, "Other coach", 5, "", "", ""),
                ],
            )
            conn.executemany(
                """INSERT INTO appointments
                   (coach_id, member_id, appointment_date, start_time, end_time, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (self.coach_a.coach_id, 101, today, "20:00", "21:00", "scheduled"),
                    (self.coach_a.coach_id, 101, today, "08:00", "09:00", "completed"),
                    (self.coach_a.coach_id, 101, today, "10:00", "11:00", "scheduled"),
                    (self.coach_a.coach_id, 102, today, "12:00", "13:00", "scheduled"),
                    (self.coach_a.coach_id, 104, today, "09:00", "10:00", "cancelled"),
                ],
            )
            conn.executemany(
                """INSERT INTO training_sessions
                   (id, coach_id, member_id, training_date, member_feedback, raw_paste_text)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (301, self.coach_a.coach_id, 101, "2025-01-03", "", ""),
                    (302, self.coach_a.coach_id, 101, "2025-01-03", "Fine", "Press 5 reps"),
                    (303, self.coach_a.coach_id, 101, "2025-01-01", "", ""),
                    (401, self.coach_b.coach_id, 201, "2025-01-03", "", ""),
                ],
            )
            conn.executemany(
                """INSERT INTO training_session_exercises
                   (id, session_id, exercise_name, weight, sort_order)
                   VALUES (?, ?, ?, ?, ?)""",
                [(501, 302, "Press", "20kg", 1), (502, 302, "Row", "", 0),
                 (503, 302, "Squat", "", 1)],
            )
            conn.executemany(
                "INSERT INTO exercise_library (id, name) VALUES (?, ?)",
                [(62, "Read-contract Catalog A"), (61, "Read-contract Catalog Z")],
            )

    def test_members_preserve_appointment_priority_and_coach_scope(self):
        members = self.repo.list_members(self.coach_a)
        self.assertEqual([member.id for member in members], [101, 102, 104, 103])
        self.assertIsInstance(members[0], MemberSummary)
        self.assertEqual([member.today_plan_time for member in members], ["10:00", "12:00", None, None])
        self.assertTrue(all(member.today_plan_available for member in members))
        self.assertEqual([member.id for member in self.repo.list_members(self.coach_b)], [201])

    def test_member_detail_retains_named_fields_and_hides_other_coaches(self):
        detail = self.repo.get_member(self.coach_a, 101)
        self.assertIsInstance(detail, MemberDetail)
        self.assertEqual(detail.remaining_lessons, 0)
        self.assertIsNone(detail.last_training_date)
        self.assertEqual(detail.phone, "")
        self.assertEqual(detail.note, "Private note")
        self.assertIsNone(detail.created_at)
        self.assertIsNone(detail.avatar_emoji)
        self.assertIsNone(self.repo.get_member(self.coach_b, 101))
        self.assertIsNone(self.repo.get_member(self.coach_a, 999))

    def test_training_history_keeps_session_and_exercise_order(self):
        history = self.repo.list_training_history(self.coach_a, 101)
        self.assertEqual([session.id for session in history], [302, 301, 303])
        first = history[0]
        self.assertIsInstance(first, TrainingHistoryItem)
        self.assertEqual(first.member_feedback, "Fine")
        self.assertEqual(first.raw_paste_text, "Press 5 reps")
        self.assertIsInstance(first.exercises, tuple)
        self.assertIsInstance(first.exercises[0], TrainingHistoryExercise)
        self.assertEqual([exercise.exercise_name for exercise in first.exercises], ["Row", "Press", "Squat"])
        self.assertEqual(first.exercises[1].weight, "20kg")
        self.assertEqual(history[1].exercises, ())
        self.assertEqual(self.repo.list_training_history(self.coach_b, 101), [])

    def test_shared_exercise_options_keep_id_order(self):
        catalog = self.repo.list_exercises(self.coach_a)
        self.assertEqual(catalog, self.repo.list_exercises(self.coach_b))
        self.assertEqual(catalog[-2:], [ExerciseOption(61, "Read-contract Catalog Z"),
                                       ExerciseOption(62, "Read-contract Catalog A")])
        self.assertEqual([exercise.id for exercise in catalog], sorted(exercise.id for exercise in catalog))

    def test_reads_require_coach_context(self):
        self.assertIsInstance(self.repo, CoachReadRepository)
        for operation, args in (
            (self.repo.list_members, ()),
            (self.repo.get_member, (101,)),
            (self.repo.list_training_history, (101,)),
            (self.repo.list_exercises, ()),
        ):
            with self.subTest(operation=operation.__name__), self.assertRaises(TypeError):
                operation(self.coach_a.coach_id, *args)

    def test_legacy_member_filter_still_accepts_query_tuples(self):
        import fitness

        with mock.patch.object(fitness, "DB_NAME", database.DB_NAME), mock.patch.object(
            database, "PROJECT_ROOT", database.PROJECT_ROOT
        ):
            rows = fitness.get_members_with_today_plan(self.coach_a.coach_id)
        self.assertEqual(fitness.filter_members(rows, "today", "今天有课"), rows[:2])


if __name__ == "__main__":
    unittest.main()
