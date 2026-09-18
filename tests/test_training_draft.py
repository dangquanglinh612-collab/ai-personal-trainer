"""TASK 9 offline integration checks, including the existing training page."""

import copy
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    import streamlit
except ModuleNotFoundError:
    sys.modules["streamlit"] = types.SimpleNamespace(
        secrets={}, session_state={}, set_page_config=lambda **kwargs: None,
    )

from ai_coach_os import auth
from ai_coach_os.repositories import database
from ai_coach_os.repositories.member_data import parse_training_text
from ai_coach_os.services.structured_output import StructuredOutputResult, TrainingParseOutput
from ai_coach_os.ui import training_draft as draft
from ai_coach_os.ui.views import shell, training


OPTIONS = [(11, "罗马尼亚硬拉"), (22, "臀推"), (33, "Bench Press")]
RAW = "罗马尼亚硬拉40kg 4组10次，臀推60kg 4组12次"


class Rerun(BaseException):
    pass


class State(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__dict__["rendered"] = set()

    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value

    def __setitem__(self, key, value):
        if key in self.rendered:
            raise RuntimeError(f"Cannot modify instantiated widget: {key}")
        super().__setitem__(key, value)


class FakeUI:
    def __init__(self, state):
        self.session_state = state
        self.clicked = set()
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __getattr__(self, name):
        if name in ("caption", "error", "warning", "info", "text", "subheader", "markdown", "metric", "success"):
            return lambda *args, **kwargs: self.messages.append((name, args))
        if name in ("container", "spinner", "expander"):
            return lambda *args, **kwargs: self
        raise AttributeError(name)

    def columns(self, spec):
        return [self] * (spec if isinstance(spec, int) else len(spec))

    def button(self, label, **kwargs):
        return label in self.clicked and not kwargs.get("disabled", False)

    def widget(self, key, default):
        if key not in self.session_state:
            self.session_state[key] = default
        self.session_state.rendered.add(key)
        return self.session_state[key]

    def text_area(self, label, *, key, **kwargs):
        return self.widget(key, "")

    text_input = text_area

    def date_input(self, label, *, key, value):
        return self.widget(key, value)

    def number_input(self, label, *, key, **kwargs):
        return self.widget(key, 3)

    def selectbox(self, label, options, *, key, **kwargs):
        return self.widget(key, options[0])

    def checkbox(self, label, *, key):
        return self.widget(key, False)

    def file_uploader(self, label, *, key, **kwargs):
        return self.widget(key, [])

    def rerun(self):
        raise Rerun()


class TrainingDraftTests(unittest.TestCase):
    def setUp(self):
        self.state = State(coach_id="wenwen", training_state_owner=("wenwen", 1))
        self.state["training_1_raw"] = RAW
        self.ui = FakeUI(self.state)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in (training, shell, auth):
            self.stack.enter_context(mock.patch.object(module, "st", self.ui))
        for name in ("inject_css", "render_sidebar", "render_page_header"):
            self.stack.enter_context(mock.patch.object(training, name))
        self.stack.enter_context(mock.patch.object(training, "get_current_member", return_value=(1, "王五", 5, "", "", "", "", "")))
        self.library = self.stack.enter_context(mock.patch.object(training, "get_exercise_options", return_value=OPTIONS))
        self.save = self.stack.enter_context(mock.patch.object(training, "save_training_session", return_value=(123, True)))
        self.update = self.stack.enter_context(mock.patch.object(training, "update_training_session"))
        self.ai = self.stack.enter_context(mock.patch.object(training, "generate_training_structured_output", return_value=self.result()))

    def result(self, exercises=None):
        return StructuredOutputResult(success=True, data=TrainingParseOutput(
            exercises=exercises if exercises is not None else [
                {"exercise_name": "罗马尼亚硬拉", "weight": "40kg", "sets": 4, "reps": 10, "rpe": 8},
                {"exercise_name": "臀推", "weight": "60kg", "sets": 4, "reps": 12},
            ], member_feedback="腰有一点紧", coach_note="下次不加重量",
        ))

    def run_page(self, *buttons):
        self.state.rendered.clear()
        self.ui.clicked = set(buttons)
        try:
            training.start_training_page()
        except Rerun:
            pass
        finally:
            self.state.rendered.clear()

    def existing_form(self):
        self.state.update({"training_1_weight_0": "原有重量", "training_1_feedback": "手动反馈"})

    def test_ai_preview_then_confirm_multiple_rows(self):
        self.run_page("AI智能解析")
        self.assertNotIn("current_training_rows", self.state)
        self.assertEqual(len(self.state["training_parse_draft"]["rows"]), 2)
        self.run_page("确认并回填训练表单")
        self.assertEqual(self.state["training_1_count"], 2)
        for field, value in {"exercise": 11, "weight": "40kg", "sets": "4", "reps": "10", "rpe": "8"}.items():
            self.assertEqual(self.state[f"training_1_{field}_0"], value)
        self.assertEqual(self.state["training_1_exercise_1"], 22)
        self.save.assert_not_called()

    def test_feedback_and_coach_note_confirmed(self):
        self.run_page("AI智能解析")
        self.assertEqual(self.state["training_1_feedback"], "")
        self.run_page("确认并回填训练表单")
        self.assertEqual(self.state["training_1_feedback"], "腰有一点紧")
        self.assertEqual(self.state["training_1_coach_note"], "下次不加重量")

    def test_unknown_action_placeholder_blocks_save(self):
        self.ai.return_value = self.result([{"exercise_name": "超级史密斯深蹲"}])
        self.run_page("AI智能解析")
        self.assertIn("未匹配", "".join(self.state["training_parse_warnings"]))
        self.run_page("确认并回填训练表单")
        self.assertIsNone(self.state["training_1_exercise_0"])
        self.assertEqual(self.state["current_training_rows"][0]["exercise_name"], "超级史密斯深蹲")
        self.run_page("保存并结束上课")
        self.save.assert_not_called()
        self.assertTrue(any("还有未确认" in str(msg) for msg in self.ui.messages))
        self.state["training_1_exercise_0"] = 22
        self.run_page("保存并结束上课")
        self.save.assert_called_once()

    def test_missing_values_stay_empty(self):
        self.ai.return_value = self.result([{"exercise_name": "臀推", "sets": 4}])
        self.run_page("AI智能解析")
        self.run_page("确认并回填训练表单")
        self.assertEqual(self.state["training_1_weight_0"], "")
        self.assertEqual(self.state["training_1_reps_0"], "")
        self.assertEqual(self.state["training_1_rpe_0"], "请选择")

    def test_ai_failures_keep_form_and_raw_without_fallback(self):
        self.existing_form()
        for error in ("未配置 AI API Key", "AI 调用失败", "AI 返回内容不是有效 JSON", "训练解析结构校验失败"):
            with self.subTest(error=error), mock.patch.object(training, "parse_training_text") as rule:
                self.ai.return_value = StructuredOutputResult(success=False, error=error)
                self.run_page("AI智能解析")
                self.assertIn(error, self.state["training_parse_error"])
                self.assertEqual(self.state["training_1_weight_0"], "原有重量")
                self.assertEqual(self.state["training_1_raw"], RAW)
                rule.assert_not_called()

    def test_empty_exercises_cannot_clear_form(self):
        self.existing_form()
        self.ai.return_value = self.result([])
        self.run_page("AI智能解析")
        self.assertIn("没有解析到有效", self.state["training_parse_error"])
        self.assertEqual(self.state["training_1_weight_0"], "原有重量")
        self.assertNotIn("training_parse_draft", self.state)

    def test_over_ten_requires_explicit_confirmation(self):
        self.ai.return_value = self.result([{"exercise_name": "臀推"}] * 11)
        self.run_page("AI智能解析")
        self.assertEqual(len(self.state["training_parse_draft"]["rows"]), 11)
        self.assertIn("11", "".join(self.state["training_parse_warnings"]))
        self.run_page("确认并回填训练表单")
        self.assertNotIn("current_training_rows", self.state)
        self.state["training_parse_truncate"] = True
        self.run_page("确认并回填训练表单")
        self.assertEqual(len(self.state["current_training_rows"]), 10)

    def test_member_change_removes_draft(self):
        self.run_page("AI智能解析")
        with mock.patch.object(training, "get_current_member", return_value=(2, "李梅", 5, "", "", "", "", "")):
            self.run_page()
        self.assertNotIn("training_parse_draft", self.state)
        self.assertEqual(self.state["training_parse_owner"], ("wenwen", 2))

    def test_logout_then_different_coach_has_no_draft_or_form(self):
        self.run_page("AI智能解析")
        with self.assertRaises(Rerun):
            auth.logout()
        self.state["coach_id"] = "numb"
        self.assertFalse(any(str(key).startswith("training_") for key in self.state))
        self.assertNotIn("current_training_rows", self.state)

    def test_parse_and_fill_never_call_database_writers(self):
        self.run_page("AI智能解析")
        self.run_page("确认并回填训练表单")
        self.save.assert_not_called()
        self.update.assert_not_called()

    def test_rule_parser_known_input(self):
        rows = parse_training_text("臀推 60kg 4×12 RPE8", OPTIONS)
        self.assertEqual((rows[0]["exercise_id"], rows[0]["weight"], rows[0]["sets"], rows[0]["reps"], rows[0]["rpe"]), (22, "60kg", "4", "12", "8"))

    def test_rule_unknown_never_uses_first_action(self):
        rows = parse_training_text("未知动作 30kg 3×10", OPTIONS)
        self.assertIsNone(rows[0]["exercise_id"])
        self.assertEqual(rows[0]["exercise_name"], "未知动作 30kg 3×10")
        self.assertIn("人工选择", rows[0]["note"])

    def test_rule_fallback_is_explicit_and_preserves_feedback(self):
        self.existing_form()
        self.run_page("使用规则解析")
        self.ai.assert_not_called()
        self.assertEqual(self.state["training_parse_source"], "规则解析")
        self.state["training_parse_overwrite"] = True
        self.run_page("确认并回填训练表单")
        self.assertEqual(self.state["training_1_feedback"], "手动反馈")

    def test_existing_form_requires_overwrite_confirmation(self):
        self.existing_form()
        self.run_page("AI智能解析")
        self.run_page("确认并回填训练表单")
        self.assertEqual(self.state["training_1_weight_0"], "原有重量")
        self.state["training_parse_overwrite"] = True
        self.run_page("确认并回填训练表单")
        self.assertEqual(self.state["training_1_weight_0"], "40kg")

    def test_changed_raw_text_blocks_stale_draft(self):
        self.run_page("AI智能解析")
        self.state["training_1_raw"] = "新的文本"
        self.run_page("确认并回填训练表单")
        self.assertNotIn("current_training_rows", self.state)

    def test_library_failure_keeps_form_and_raw(self):
        self.existing_form()
        self.library.side_effect = RuntimeError("database unavailable")
        with self.assertLogs(training.logger, level="ERROR"):
            self.run_page("AI智能解析")
        self.assertEqual(self.state["training_1_weight_0"], "原有重量")
        self.assertEqual(self.state["training_1_raw"], RAW)
        self.ai.assert_not_called()

    def test_empty_input_never_calls_ai(self):
        self.state["training_1_raw"] = "  "
        self.run_page("AI智能解析")
        self.ai.assert_not_called()
        self.assertEqual(self.state["training_parse_error"], "请先粘贴训练内容。")

    def test_safe_name_normalization_and_ambiguous_name(self):
        output = self.result([{"exercise_name": " bench   PRESS "}]).data
        row = draft.structured_output_to_training_rows(output, OPTIONS)[0]
        self.assertEqual((row["exercise_id"], row["exercise_name"]), (33, "Bench Press"))
        row = draft.structured_output_to_training_rows(output, OPTIONS + [(44, "bench press")])[0]
        self.assertIsNone(row["exercise_id"])

    def test_rerun_preserves_draft_and_new_session_clears_it(self):
        self.run_page("AI智能解析")
        saved = copy.deepcopy(self.state["training_parse_draft"])
        self.run_page()
        self.assertEqual(self.state["training_parse_draft"], saved)
        shell.reset_training_state(1)
        self.assertNotIn("training_parse_draft", self.state)

    def test_unexpected_ai_exception_is_safe(self):
        self.existing_form()
        self.ai.side_effect = RuntimeError("unexpected")
        with self.assertLogs(training.logger, level="ERROR"):
            self.run_page("AI智能解析")
        self.assertIn("解析失败", self.state["training_parse_error"])
        self.assertEqual(self.state["training_1_weight_0"], "原有重量")

    def test_update_still_requires_final_save_click(self):
        self.state["current_training_session_id"] = 100
        self.run_page("AI智能解析")
        self.run_page("确认并回填训练表单")
        self.update.assert_not_called()
        self.run_page("更新本次训练记录")
        self.update.assert_called_once()
        self.assertEqual(self.update.call_args.args[:2], ("wenwen", 100))
        self.save.assert_not_called()

    def database_after_parse(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "draft_test.db")
            with mock.patch.object(database, "DB_NAME", path):
                database.init_db()
                conn = sqlite3.connect(path)
                try:
                    member_id = conn.execute(
                        "INSERT INTO members (coach_id, name, remaining_lessons) VALUES (?, ?, ?)",
                        ("wenwen", "王五", 5),
                    ).lastrowid
                    conn.commit()
                    self.run_page("AI智能解析")
                    self.run_page("确认并回填训练表单")
                    return (
                        conn.execute("SELECT COUNT(*) FROM training_sessions").fetchone()[0],
                        conn.execute("SELECT remaining_lessons FROM members WHERE id = ?", (member_id,)).fetchone()[0],
                    )
                finally:
                    conn.close()

    def test_parse_and_confirm_create_no_training_sessions(self):
        self.assertEqual(self.database_after_parse()[0], 0)

    def test_parse_and_confirm_do_not_deduct_lessons(self):
        self.assertEqual(self.database_after_parse()[1], 5)

    def test_manual_edits_after_fill_are_used_for_final_save(self):
        self.run_page("AI智能解析")
        self.run_page("确认并回填训练表单")
        self.state["training_1_weight_0"] = "42kg"
        self.run_page("保存并结束上课")
        self.assertEqual(self.save.call_args.args[-1][0]["weight"], "42kg")

    def test_new_parse_resets_previous_overwrite_consent(self):
        self.existing_form()
        self.run_page("AI智能解析")
        self.state["training_parse_overwrite"] = True
        self.run_page("AI智能解析")
        self.assertFalse(self.state["training_parse_overwrite"])


if __name__ == "__main__":
    unittest.main()
