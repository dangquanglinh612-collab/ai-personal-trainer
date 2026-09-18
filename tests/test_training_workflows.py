import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

try:
    import streamlit  # noqa: F401
except ModuleNotFoundError:
    sys.modules["streamlit"] = types.SimpleNamespace(
        set_page_config=lambda **kwargs: None,
        session_state={},
    )

import fitness
from ai_coach_os import application


class FakeUploadedFile:
    def __init__(self, name, content):
        self.name = name
        self._content = content

    def getvalue(self):
        return self._content


class TrainingWorkflowRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_name = fitness.DB_NAME
        self.old_module_file = fitness.__file__
        fitness.DB_NAME = str(Path(self.temp_dir.name) / "test_ai_coach_os.db")
        fitness.__file__ = str(Path(self.temp_dir.name) / "fitness.py")
        fitness.init_db()

        conn = fitness.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO members (
                coach_id, name, remaining_lessons, goal, last_training_date,
                ai_reminder, phone, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task7_coach_a",
                "回归测试会员",
                3,
                "提升力量",
                "",
                "",
                "",
                "",
                "2026-07-30T10:00:00",
            ),
        )
        self.member_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO members (
                coach_id, name, remaining_lessons, goal, last_training_date,
                ai_reminder, phone, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task7_coach_b",
                "另一位教练的会员",
                5,
                "减脂",
                "",
                "",
                "",
                "",
                "2026-07-30T10:00:00",
            ),
        )
        self.other_coach_member_id = cursor.lastrowid
        conn.commit()
        conn.close()

    def tearDown(self):
        fitness.DB_NAME = self.old_db_name
        fitness.__file__ = self.old_module_file
        self.temp_dir.cleanup()

    def test_schema_and_body_measurement_history_are_isolated(self):
        managed_conn = fitness.get_conn()
        try:
            self.assertEqual(
                managed_conn.execute("PRAGMA foreign_keys").fetchone()[0], 1
            )
        finally:
            managed_conn.close()

        conn = sqlite3.connect(fitness.DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('body_measurements', 'training_session_photos')
            ORDER BY name
            """
        )
        self.assertEqual(
            [row[0] for row in cursor.fetchall()],
            ["body_measurements", "training_session_photos"],
        )
        conn.close()

        first_id = fitness.create_body_measurement(
            "task7_coach_a",
            self.member_id,
            "2026-07-29",
            "162cm",
            "58kg",
            note="初始记录",
        )
        second_id = fitness.create_body_measurement(
            "task7_coach_a",
            self.member_id,
            "2026-07-30",
            "162cm",
            "57.5kg",
            body_fat="25%",
            waist="70cm",
        )

        history = fitness.get_body_measurements_for_member(
            "task7_coach_a", self.member_id
        )
        self.assertEqual([row[0] for row in history], [second_id, first_id])
        self.assertEqual(
            fitness.get_latest_body_measurement(
                "task7_coach_a", self.member_id
            )[0],
            second_id,
        )
        self.assertIsNone(
            fitness.get_latest_body_measurement(
                "task7_coach_b", self.member_id
            )
        )

    def test_training_update_and_same_day_save_do_not_double_deduct(self):
        training_date = "2026-07-30"
        first_session_id, first_deducted = fitness.save_training_session(
            "task7_coach_a",
            self.member_id,
            training_date,
            "状态良好",
            "动作稳定",
            "",
            [],
        )
        self.assertTrue(first_deducted)

        fitness.update_training_session(
            "task7_coach_a",
            first_session_id,
            training_date,
            "更新后的反馈",
            "更新后的备注",
            "",
            [],
        )
        member_after_update = fitness.get_member_by_id(
            "task7_coach_a", self.member_id
        )
        self.assertEqual(member_after_update[2], 2)

        self.assertTrue(
            fitness.has_training_session_on_date(
                "task7_coach_a", self.member_id, training_date
            )
        )
        second_session_id, second_deducted = fitness.save_training_session(
            "task7_coach_a",
            self.member_id,
            training_date,
            "同日第二条记录",
            "",
            "",
            [],
        )
        self.assertIsInstance(second_session_id, int)
        self.assertFalse(second_deducted)
        member_after_same_day_save = fitness.get_member_by_id(
            "task7_coach_a", self.member_id
        )
        self.assertEqual(member_after_same_day_save[2], 2)

    def test_atomic_training_save_rolls_back_when_member_update_fails(self):
        with mock.patch(
            "ai_coach_os.repositories.member_data._update_member_after_training",
            side_effect=RuntimeError("simulated deduction failure"),
        ):
            with self.assertRaises(RuntimeError):
                fitness.save_training_session(
                    "task7_coach_a",
                    self.member_id,
                    "2026-07-30",
                    "状态良好",
                    "动作稳定",
                    "",
                    [],
                )

        conn = fitness.get_conn()
        try:
            session_count = conn.execute(
                """
                SELECT COUNT(*) FROM training_sessions
                WHERE coach_id = ? AND member_id = ?
                """,
                ("task7_coach_a", self.member_id),
            ).fetchone()[0]
            remaining_lessons = conn.execute(
                "SELECT remaining_lessons FROM members WHERE id = ?",
                (self.member_id,),
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(session_count, 0)
        self.assertEqual(remaining_lessons, 3)

    def test_training_and_member_writes_reject_cross_coach_ids(self):
        exercise = fitness.get_exercise_options()[0]
        session_id, _ = fitness.save_training_session(
            "task7_coach_a",
            self.member_id,
            "2026-07-30",
            "",
            "",
            "",
            [{"exercise_id": exercise[0], "exercise_name": exercise[1]}],
        )
        self.assertEqual(
            fitness.get_exercises_for_session("task7_coach_b", session_id),
            [],
        )
        with self.assertRaises(ValueError):
            fitness.update_training_session(
                "task7_coach_b",
                session_id,
                "2026-07-30",
                "",
                "",
                "",
                [],
            )
        with self.assertRaises(ValueError):
            fitness.create_body_measurement(
                "task7_coach_b", self.member_id, "2026-07-30", "", ""
            )
        with self.assertRaises(ValueError):
            fitness.save_ai_analysis_report(
                "task7_coach_b", self.member_id, "报告", ""
            )
        with self.assertRaises(ValueError):
            fitness.create_training_session(
                "task7_coach_b", self.member_id, "2026-07-30", "", "", "", []
            )

    def test_logout_state_cleanup_removes_member_data_only(self):
        state = {
            "logged_in": True,
            "coach_id": "wenwen",
            "selected_member_id": self.member_id,
            f"training_{self.member_id}_feedback": "上一个会员的反馈",
            f"ai_plan_extra_note_{self.member_id}": "上一个会员的计划草稿",
            f"body_measurement_weight_{self.member_id}": "57kg",
            "schedule_prefill_member_id": self.member_id,
            "unrelated_theme_preference": "light",
        }

        fitness.clear_user_session_state(state)

        self.assertEqual(state, {"unrelated_theme_preference": "light"})

    def test_initialization_error_is_logged_and_shown_as_generic_message(self):
        with (
            mock.patch.object(application.st, "set_page_config"),
            mock.patch.object(
                application.st, "error", create=True
            ) as show_error,
            mock.patch.object(
                application,
                "init_db",
                side_effect=RuntimeError("sensitive database detail"),
            ),
        ):
            application.main()

        show_error.assert_called_once_with(
            "系统初始化失败，请稍后重试或联系管理员。"
        )
        self.assertNotIn("sensitive database detail", show_error.call_args.args[0])

    def test_training_photos_are_linked_and_coach_isolated(self):
        session_id = fitness.create_training_session(
            "task7_coach_a",
            self.member_id,
            "2026-07-30",
            "",
            "",
            "",
            [],
        )
        uploaded_files = [
            FakeUploadedFile("深蹲动作.jpg", b"test-jpg-content"),
            FakeUploadedFile("not_allowed.zip", b"not-an-image"),
        ]
        saved_ids = fitness.save_uploaded_training_photos(
            "task7_coach_a",
            self.member_id,
            session_id,
            uploaded_files,
            "深蹲侧面动作照",
        )

        self.assertEqual(len(saved_ids), 1)
        photos = fitness.get_training_photos_for_session(
            "task7_coach_a", self.member_id, session_id
        )
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0][3], "深蹲侧面动作照")
        self.assertTrue(
            (Path(self.temp_dir.name) / photos[0][1]).is_file()
        )
        self.assertEqual(
            fitness.get_training_photos_for_session(
                "task7_coach_b", self.member_id, session_id
            ),
            [],
        )

    def test_analysis_context_and_fallback_work(self):
        fitness.create_training_session(
            "task7_coach_a",
            self.member_id,
            "2026-07-30",
            "状态良好",
            "下次可小幅加重",
            "",
            [],
        )
        member = fitness.get_member_by_id("task7_coach_a", self.member_id)
        recent_sessions = fitness.get_recent_training_context(
            "task7_coach_a", self.member_id, limit=5
        )
        prompt = fitness.build_ai_analysis_prompt(
            member,
            recent_sessions,
            fitness.get_exercise_library_names(),
            "",
        )
        report = fitness.generate_fallback_ai_analysis(
            member,
            recent_sessions,
            fitness.get_exercise_library_names(),
            "",
        )

        self.assertEqual(len(recent_sessions), 1)
        self.assertIn("下次训练建议", prompt)
        self.assertIn("下次训练建议", report)

    def test_ai_plan_fallback_save_update_and_isolation(self):
        report_id = fitness.save_ai_analysis_report(
            "task7_coach_a",
            self.member_id,
            "# AI 训练分析\n\n下次训练建议保守加量。",
            "回归测试",
        )
        latest_report = fitness.get_latest_ai_analysis_report(
            "task7_coach_a", self.member_id
        )
        self.assertEqual(latest_report[0], report_id)
        self.assertIsNone(
            fitness.get_latest_ai_analysis_report(
                "task7_coach_b", self.member_id
            )
        )

        member = fitness.get_member_by_id(
            "task7_coach_a", self.member_id
        )
        recent_sessions = fitness.get_recent_training_context(
            "task7_coach_a", self.member_id, limit=5
        )
        exercise_options = fitness.get_exercise_options()
        exercise_names = [item[1] for item in exercise_options]
        prompt = fitness.build_ai_plan_prompt(
            member,
            recent_sessions,
            latest_report,
            exercise_names,
            "本次控制强度",
        )
        self.assertIn("只返回可解析 JSON", prompt)
        self.assertIn("下次训练建议保守加量", prompt)

        with mock.patch.dict(
            fitness.os.environ,
            {"DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": ""},
            clear=False,
        ):
            ai_plan = fitness.generate_ai_training_plan(
                prompt,
                member=member,
                recent_sessions=recent_sessions,
                exercise_names=exercise_names,
                extra_note="本次控制强度",
            )
        self.assertIsInstance(ai_plan, dict)
        self.assertGreaterEqual(len(ai_plan["exercises"]), 3)
        self.assertLessEqual(len(ai_plan["exercises"]), 5)
        self.assertTrue(
            ai_plan["coach_note"].startswith(
                "当前未配置 API Key 或 AI 调用失败"
            )
        )

        normalized_rows = fitness.normalize_ai_plan_to_rows(
            ai_plan, exercise_options
        )
        self.assertEqual(len(normalized_rows), len(ai_plan["exercises"]))
        self.assertTrue(
            all(row["exercise_id"] for row in normalized_rows)
        )

        conn = fitness.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT remaining_lessons FROM members WHERE id = ?",
            (self.member_id,),
        )
        lessons_before = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM training_sessions WHERE member_id = ?",
            (self.member_id,),
        )
        sessions_before = cursor.fetchone()[0]
        conn.close()

        plan_id = fitness.save_training_plan(
            "task7_coach_a",
            self.member_id,
            "2026-07-31",
            ai_plan["plan_goal"],
            ai_plan["coach_note"],
            fitness.json.dumps(ai_plan, ensure_ascii=False),
            normalized_rows,
            source_analysis_report_id=report_id,
        )
        latest_plan = fitness.get_latest_training_plan(
            "task7_coach_a", self.member_id
        )
        self.assertEqual(latest_plan[0], plan_id)
        self.assertEqual(latest_plan[2], "confirmed")
        self.assertEqual(latest_plan[3], report_id)
        self.assertEqual(
            fitness.get_training_plans_for_member(
                "task7_coach_b", self.member_id
            ),
            [],
        )
        self.assertEqual(
            len(fitness.get_training_plan_exercises("task7_coach_a", plan_id)),
            len(normalized_rows),
        )
        self.assertEqual(
            fitness.get_training_plan_exercises("task7_coach_b", plan_id),
            [],
        )
        with self.assertRaises(ValueError):
            fitness.update_training_plan(
                "task7_coach_b",
                plan_id,
                "2026-08-01",
                "越权修改",
                "",
                "{}",
                [],
            )

        updated_rows = normalized_rows[:2]
        fitness.update_training_plan(
            "task7_coach_a",
            plan_id,
            "2026-08-01",
            "更新后的训练目标",
            "更新后的教练备注",
            "{}",
            updated_rows,
        )
        self.assertEqual(
            len(fitness.get_training_plan_exercises("task7_coach_a", plan_id)), 2
        )
        self.assertEqual(
            fitness.get_latest_training_plan(
                "task7_coach_a", self.member_id
            )[1],
            "2026-08-01",
        )

        conn = fitness.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT remaining_lessons FROM members WHERE id = ?",
            (self.member_id,),
        )
        self.assertEqual(cursor.fetchone()[0], lessons_before)
        cursor.execute(
            "SELECT COUNT(*) FROM training_sessions WHERE member_id = ?",
            (self.member_id,),
        )
        self.assertEqual(cursor.fetchone()[0], sessions_before)
        conn.close()

    def test_unknown_ai_exercise_uses_library_default(self):
        exercise_options = fitness.get_exercise_options()
        rows = fitness.normalize_ai_plan_to_rows(
            {
                "exercises": [
                    {
                        "exercise_name": "动作库不存在的动作",
                        "target_weight": {"unexpected": "value"},
                        "sets": None,
                        "reps": 12,
                        "target_rpe": "99",
                        "note": "",
                    }
                ]
            },
            exercise_options,
        )
        self.assertEqual(rows[0]["exercise_id"], exercise_options[0][0])
        self.assertIn("AI 原始动作", rows[0]["note"])
        self.assertEqual(rows[0]["target_rpe"], "")

    def test_appointment_workflow_conflicts_statuses_and_isolation(self):
        conn = sqlite3.connect(fitness.DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'appointments'"
        )
        self.assertEqual(cursor.fetchone()[0], "appointments")
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_appointments_coach_date'"
        )
        self.assertEqual(
            cursor.fetchone()[0], "idx_appointments_coach_date"
        )
        cursor.execute(
            "SELECT remaining_lessons FROM members WHERE id = ?",
            (self.member_id,),
        )
        lessons_before = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM training_sessions WHERE member_id = ?",
            (self.member_id,),
        )
        sessions_before = cursor.fetchone()[0]
        conn.close()

        appointment_date = (date.today() + timedelta(days=2)).isoformat()
        first_id = fitness.create_appointment(
            "task7_coach_a",
            self.member_id,
            appointment_date,
            "18:00",
            "19:00",
            "普通预约",
        )
        self.assertIsInstance(first_id, int)

        adjacent_id = fitness.create_appointment(
            "task7_coach_a",
            self.member_id,
            appointment_date,
            "19:00",
            "20:00",
            "时间衔接",
        )
        self.assertIsInstance(adjacent_id, int)

        conflict = fitness.create_appointment(
            "task7_coach_a",
            self.member_id,
            appointment_date,
            "18:30",
            "19:30",
        )
        self.assertTrue(conflict["has_conflict"])
        self.assertEqual(conflict["appointment"]["id"], first_id)

        with self.assertRaises(ValueError):
            fitness.create_appointment(
                "task7_coach_a",
                self.member_id,
                appointment_date,
                "19:00",
                "18:00",
            )

        edit_conflict = fitness.update_appointment(
            "task7_coach_a",
            adjacent_id,
            self.member_id,
            appointment_date,
            "18:30",
            "19:30",
            "冲突改期",
        )
        self.assertTrue(edit_conflict["has_conflict"])
        self.assertTrue(
            fitness.update_appointment(
                "task7_coach_a",
                adjacent_id,
                self.member_id,
                appointment_date,
                "20:00",
                "21:00",
                "成功改期",
            )
        )

        fitness.update_appointment_status(
            "task7_coach_a", first_id, "cancelled"
        )
        replacement_id = fitness.create_appointment(
            "task7_coach_a",
            self.member_id,
            appointment_date,
            "18:00",
            "19:00",
            "占用已取消时段",
        )
        self.assertIsInstance(replacement_id, int)
        self.assertEqual(
            fitness.get_appointment_by_id(
                "task7_coach_a", first_id
            )["status"],
            "cancelled",
        )

        fitness.update_appointment_status(
            "task7_coach_a", replacement_id, "completed"
        )
        self.assertEqual(
            fitness.get_appointment_by_id(
                "task7_coach_a", replacement_id
            )["status"],
            "completed",
        )

        other_coach_id = fitness.create_appointment(
            "task7_coach_b",
            self.other_coach_member_id,
            appointment_date,
            "18:00",
            "19:00",
        )
        self.assertIsInstance(other_coach_id, int)
        self.assertIsNone(
            fitness.get_appointment_by_id(
                "task7_coach_a", other_coach_id
            )
        )
        with self.assertRaises(ValueError):
            fitness.update_appointment_status(
                "task7_coach_a", other_coach_id, "cancelled"
            )

        coach_a_appointments = fitness.get_appointments_for_date(
            "task7_coach_a", appointment_date
        )
        self.assertEqual(len(coach_a_appointments), 3)
        self.assertTrue(
            all(
                appointment["coach_id"] == "task7_coach_a"
                for appointment in coach_a_appointments
            )
        )
        next_appointment = fitness.get_next_appointment_for_member(
            "task7_coach_a", self.member_id
        )
        self.assertEqual(next_appointment["id"], adjacent_id)
        upcoming = fitness.get_upcoming_appointments_for_coach(
            "task7_coach_a", limit=10
        )
        self.assertEqual([item["id"] for item in upcoming], [adjacent_id])

        member_options = fitness.get_member_options_for_coach(
            "task7_coach_a"
        )
        self.assertIn(self.member_id, [row[0] for row in member_options])
        self.assertNotIn(
            self.other_coach_member_id, [row[0] for row in member_options]
        )

        today_id = fitness.create_appointment(
            "task7_coach_a",
            self.member_id,
            date.today().isoformat(),
            "09:00",
            "10:00",
            "今日预约",
        )
        self.assertIsInstance(today_id, int)
        member_directory_rows = fitness.get_members_with_today_plan(
            "task7_coach_a"
        )
        member_directory_row = next(
            row for row in member_directory_rows if row[0] == self.member_id
        )
        self.assertEqual(member_directory_row[6], "09:00")
        self.assertEqual(
            fitness.get_today_plan_for_member(
                "task7_coach_a", self.member_id
            ),
            ("09:00", "scheduled", "今日预约"),
        )

        conn = fitness.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT remaining_lessons FROM members WHERE id = ?",
            (self.member_id,),
        )
        self.assertEqual(cursor.fetchone()[0], lessons_before)
        cursor.execute(
            "SELECT COUNT(*) FROM training_sessions WHERE member_id = ?",
            (self.member_id,),
        )
        self.assertEqual(cursor.fetchone()[0], sessions_before)
        conn.close()

    def test_concurrent_overlapping_appointments_only_create_one(self):
        appointment_date = (date.today() + timedelta(days=3)).isoformat()
        start_barrier = threading.Barrier(2)

        def create_overlapping_appointment(note):
            start_barrier.wait(timeout=5)
            return fitness.create_appointment(
                "task7_coach_a",
                self.member_id,
                appointment_date,
                "18:00",
                "19:00",
                note,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    create_overlapping_appointment,
                    ("并发预约 A", "并发预约 B"),
                )
            )

        self.assertEqual(sum(isinstance(result, int) for result in results), 1)
        self.assertEqual(
            sum(
                isinstance(result, dict) and result.get("has_conflict")
                for result in results
            ),
            1,
        )
        appointments = fitness.get_appointments_for_date(
            "task7_coach_a", appointment_date
        )
        self.assertEqual(len(appointments), 1)


if __name__ == "__main__":
    unittest.main()
