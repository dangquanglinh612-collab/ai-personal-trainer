import sys
import types
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import streamlit  # noqa: F401
except ModuleNotFoundError:
    sys.modules["streamlit"] = types.SimpleNamespace(
        secrets={},
        set_page_config=lambda **kwargs: None,
        session_state={},
    )

from ai_coach_os.services.ai import AIConfigurationError, AIRequestError
from ai_coach_os.services.structured_output import (
    EMPTY_EXERCISES_WARNING,
    TrainingParseOutput,
    build_training_structured_prompt,
    clean_json_response,
    generate_training_structured_output,
    normalize_exercise_names,
    parse_json_safely,
    validate_training_parse_output,
)


VALID_PAYLOAD = {
    "exercises": [
        {
            "exercise_name": "罗马尼亚硬拉",
            "weight": "40kg",
            "sets": 4,
            "reps": 10,
            "rpe": 8,
            "note": "",
        }
    ],
    "member_feedback": "",
    "coach_note": "",
}


class StructuredOutputTests(unittest.TestCase):
    def test_normal_json_parses_and_validates(self):
        raw_text = """{
          "exercises": [{
            "exercise_name": "罗马尼亚硬拉",
            "weight": "40kg",
            "sets": 4,
            "reps": 10,
            "rpe": 8,
            "note": ""
          }],
          "member_feedback": "",
          "coach_note": ""
        }"""

        parsed = parse_json_safely(raw_text)
        validated = validate_training_parse_output(parsed.data)

        self.assertTrue(parsed.success)
        self.assertTrue(validated.success)
        self.assertIsInstance(validated.data, TrainingParseOutput)
        self.assertEqual(validated.data.exercises[0].sets, 4)

    def test_markdown_wrapped_json_is_cleaned(self):
        raw_text = """Here is the JSON:
```json
{"exercises": [], "member_feedback": "", "coach_note": ""}
```
No other data."""

        cleaned = clean_json_response(raw_text)
        parsed = parse_json_safely(raw_text)

        self.assertEqual(
            cleaned,
            '{"exercises": [], "member_feedback": "", "coach_note": ""}',
        )
        self.assertTrue(parsed.success)

    def test_non_numeric_sets_fails_schema_validation(self):
        payload = VALID_PAYLOAD | {
            "exercises": [VALID_PAYLOAD["exercises"][0] | {"sets": "四"}]
        }
        result = validate_training_parse_output(payload)
        self.assertFalse(result.success)
        self.assertIn("sets", result.error)

    def test_out_of_range_rpe_fails_schema_validation(self):
        payload = VALID_PAYLOAD | {
            "exercises": [VALID_PAYLOAD["exercises"][0] | {"rpe": 15}]
        }
        result = validate_training_parse_output(payload)
        self.assertFalse(result.success)
        self.assertIn("rpe", result.error)

    def test_missing_exercise_name_fails_schema_validation(self):
        exercise = dict(VALID_PAYLOAD["exercises"][0])
        del exercise["exercise_name"]
        result = validate_training_parse_output(
            VALID_PAYLOAD | {"exercises": [exercise]}
        )
        self.assertFalse(result.success)
        self.assertIn("exercise_name", result.error)

    def test_empty_ai_response_fails_safely(self):
        result = parse_json_safely("")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "AI 返回为空")

    def test_natural_language_is_not_treated_as_json(self):
        result = parse_json_safely("今天练得不错")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "AI 返回内容不是有效 JSON")

    def test_unknown_exercise_is_preserved_with_warning(self):
        output = TrainingParseOutput.model_validate(
            VALID_PAYLOAD
            | {
                "exercises": [
                    VALID_PAYLOAD["exercises"][0]
                    | {"exercise_name": "超级史密斯深蹲"}
                ]
            }
        )
        result = normalize_exercise_names(output, ["罗马尼亚硬拉", "杠铃深蹲"])

        self.assertTrue(result.success)
        self.assertEqual(
            result.data.exercises[0].exercise_name,
            "超级史密斯深蹲",
        )
        self.assertEqual(
            result.warnings,
            ["动作‘超级史密斯深蹲’未在动作库中找到"],
        )

    def test_null_rpe_is_valid(self):
        payload = VALID_PAYLOAD | {
            "exercises": [VALID_PAYLOAD["exercises"][0] | {"rpe": None}]
        }
        result = validate_training_parse_output(payload)
        self.assertTrue(result.success)
        self.assertIsNone(result.data.exercises[0].rpe)

    def test_empty_exercise_list_is_valid_with_warning(self):
        result = validate_training_parse_output(
            {"exercises": [], "member_feedback": "", "coach_note": ""}
        )
        self.assertTrue(result.success)
        self.assertEqual(result.warnings, [EMPTY_EXERCISES_WARNING])

    def test_mild_name_difference_uses_canonical_library_name(self):
        output = TrainingParseOutput.model_validate(
            VALID_PAYLOAD
            | {
                "exercises": [
                    VALID_PAYLOAD["exercises"][0]
                    | {"exercise_name": " romanian deadlift "}
                ]
            }
        )
        result = normalize_exercise_names(output, ["Romanian Deadlift"])
        self.assertTrue(result.success)
        self.assertEqual(
            result.data.exercises[0].exercise_name,
            "Romanian Deadlift",
        )
        self.assertEqual(result.warnings, [])

    def test_prompt_contains_contract_input_and_exercise_library(self):
        prompt = build_training_structured_prompt(
            "臀推60kg 4×12",
            ["臀推", "罗马尼亚硬拉"],
        )
        self.assertIn("臀推60kg 4×12", prompt)
        self.assertIn("罗马尼亚硬拉", prompt)
        self.assertIn("只返回 JSON", prompt)
        self.assertIn("不要做医疗诊断", prompt)

    def test_generate_pipeline_uses_mocked_ai_without_network(self):
        raw_ai_response = """```json
        {"exercises": [{"exercise_name": "臀推", "weight": "60kg",
        "sets": 4, "reps": 12, "rpe": null, "note": ""}],
        "member_feedback": "臀部发力不错", "coach_note": "下次先不加重量"}
        ```"""
        with mock.patch(
            "ai_coach_os.services.structured_output.request_ai_text",
            return_value=raw_ai_response,
        ) as request_ai:
            result = generate_training_structured_output(
                "臀推60kg 4×12，会员说臀部发力不错。",
                ["臀推"],
            )

        self.assertTrue(result.success)
        self.assertEqual(result.data.exercises[0].exercise_name, "臀推")
        self.assertEqual(result.raw_text, raw_ai_response)
        request_ai.assert_called_once()

    def test_generate_without_api_key_fails_without_network(self):
        with mock.patch(
            "ai_coach_os.services.structured_output.request_ai_text",
            side_effect=AIConfigurationError("未配置 AI API Key"),
        ):
            result = generate_training_structured_output(
                "罗马尼亚硬拉40kg做4组10次",
                ["罗马尼亚硬拉"],
            )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "未配置 AI API Key")

    def test_generate_ai_failure_returns_uniform_result(self):
        with mock.patch(
            "ai_coach_os.services.structured_output.request_ai_text",
            side_effect=AIRequestError("connection failed"),
        ):
            result = generate_training_structured_output(
                "罗马尼亚硬拉40kg做4组10次",
                ["罗马尼亚硬拉"],
            )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "AI 调用失败")
        self.assertIsNone(result.data)


if __name__ == "__main__":
    unittest.main()
