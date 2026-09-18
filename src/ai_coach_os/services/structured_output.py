"""Validated AI structured output for training-record parsing."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .ai import AIConfigurationError, AIRequestError, request_ai_text


EMPTY_EXERCISES_WARNING = "没有解析到有效训练动作"


class TrainingExerciseOutput(BaseModel):
    """One exercise extracted from an untrusted AI response."""

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    exercise_name: str
    weight: str = ""
    sets: int | None = Field(default=None, gt=0)
    reps: int | None = Field(default=None, gt=0)
    rpe: int | None = Field(default=None, ge=1, le=10)
    note: str = ""

    @field_validator("exercise_name")
    @classmethod
    def validate_exercise_name(cls, value: str) -> str:
        if not value:
            raise ValueError("动作名称不能为空")
        return value


class TrainingParseOutput(BaseModel):
    """Validated training information extracted from natural language."""

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    exercises: list[TrainingExerciseOutput]
    member_feedback: str = ""
    coach_note: str = ""


class StructuredOutputResult(BaseModel):
    """Uniform success/failure contract for every structured-output stage."""

    success: bool
    data: Any | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    raw_text: str | None = None


def clean_json_response(raw_text: str | None) -> str:
    """Remove common Markdown wrappers and isolate a JSON object when possible."""
    if raw_text is None:
        return ""

    cleaned = str(raw_text).strip()
    if not cleaned:
        return ""

    fenced_match = re.search(
        r"```(?:json)?\s*(.*?)```",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_match:
        cleaned = fenced_match.group(1).strip()
    else:
        cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "").strip()

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        return cleaned[first_brace:last_brace + 1].strip()
    return cleaned


def parse_json_safely(raw_text: str | None) -> StructuredOutputResult:
    """Parse an AI response as a JSON object without leaking decoder errors."""
    original_text = None if raw_text is None else str(raw_text)
    cleaned = clean_json_response(raw_text)
    if not cleaned:
        return StructuredOutputResult(
            success=False,
            error="AI 返回为空",
            raw_text=original_text,
        )

    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return StructuredOutputResult(
            success=False,
            error="AI 返回内容不是有效 JSON",
            raw_text=original_text,
        )

    if not isinstance(parsed, dict):
        return StructuredOutputResult(
            success=False,
            error="AI 返回 JSON 顶层结构必须是对象",
            raw_text=original_text,
        )

    return StructuredOutputResult(
        success=True,
        data=parsed,
        raw_text=original_text,
    )


def _format_validation_error(exc: ValidationError) -> str:
    first_error = exc.errors(include_url=False)[0]
    location = ".".join(str(part) for part in first_error.get("loc", ()))
    detail = first_error.get("msg", "字段不符合要求")
    if location:
        return f"训练解析结构校验失败：{location} - {detail}"
    return f"训练解析结构校验失败：{detail}"


def validate_training_parse_output(parsed_json: Any) -> StructuredOutputResult:
    """Validate parsed JSON against the training parsing business schema."""
    if not isinstance(parsed_json, dict):
        return StructuredOutputResult(
            success=False,
            error="训练解析结构必须是对象",
        )

    try:
        output = TrainingParseOutput.model_validate(parsed_json)
    except ValidationError as exc:
        return StructuredOutputResult(
            success=False,
            error=_format_validation_error(exc),
        )

    warnings = []
    if not output.exercises:
        warnings.append(EMPTY_EXERCISES_WARNING)
    return StructuredOutputResult(
        success=True,
        data=output,
        warnings=warnings,
    )


def normalize_exercise_names(
    output: TrainingParseOutput,
    exercise_names: list[str],
) -> StructuredOutputResult:
    """Normalize mild name differences and warn about unknown exercises."""
    if not isinstance(output, TrainingParseOutput):
        return StructuredOutputResult(
            success=False,
            error="训练解析结果类型不正确",
        )

    canonical_names = {
        name.strip().casefold(): name.strip()
        for name in exercise_names
        if isinstance(name, str) and name.strip()
    }
    normalized_output = output.model_copy(deep=True)
    warnings: list[str] = []

    if not normalized_output.exercises:
        warnings.append(EMPTY_EXERCISES_WARNING)

    for exercise in normalized_output.exercises:
        normalized_key = exercise.exercise_name.strip().casefold()
        canonical_name = canonical_names.get(normalized_key)
        if canonical_name is not None:
            exercise.exercise_name = canonical_name
        else:
            warnings.append(
                f"动作‘{exercise.exercise_name}’未在动作库中找到"
            )

    return StructuredOutputResult(
        success=True,
        data=normalized_output,
        warnings=warnings,
    )


def build_training_structured_prompt(
    raw_text: str,
    exercise_names: list[str],
) -> str:
    """Build the strict JSON-only extraction prompt used by TASK 9."""
    exercise_library = json.dumps(
        [name for name in exercise_names if isinstance(name, str)],
        ensure_ascii=False,
    )
    return f"""你是 AI Coach OS 的训练记录解析器。

你的任务：把教练输入的自然语言训练记录转换成固定 JSON。

允许使用的动作库：
{exercise_library}

教练输入：
{raw_text}

你必须只返回以下 JSON：
{{
  "exercises": [
    {{
      "exercise_name": "",
      "weight": "",
      "sets": null,
      "reps": null,
      "rpe": null,
      "note": ""
    }}
  ],
  "member_feedback": "",
  "coach_note": ""
}}

规则：
1. 只返回 JSON。
2. 不要 Markdown。
3. 不要解释。
4. 不要输出额外文字。
5. 不要添加输入中不存在的数据。
6. 不确定的字段填 null 或空字符串。
7. 动作名称优先匹配动作库。
8. 不要自行编造重量。
9. 不确定 RPE 时填 null。
10. 会员表达的疼痛、感受、疲劳等放 member_feedback。
11. 教练表达的观察、提醒、下次注意事项放 coach_note。
12. 不要做训练建议。
13. 不要做医疗诊断。"""


def _merge_warnings(*warning_groups: list[str]) -> list[str]:
    merged: list[str] = []
    for warning_group in warning_groups:
        for warning in warning_group:
            if warning not in merged:
                merged.append(warning)
    return merged


def generate_training_structured_output(
    raw_text: str,
    exercise_names: list[str],
) -> StructuredOutputResult:
    """Run AI extraction, JSON parsing, schema validation, and normalization."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return StructuredOutputResult(
            success=False,
            error="训练文本不能为空",
            raw_text=None if raw_text is None else str(raw_text),
        )

    prompt = build_training_structured_prompt(raw_text, exercise_names)
    try:
        ai_raw_text = request_ai_text(prompt, temperature=0.1)
    except AIConfigurationError:
        return StructuredOutputResult(
            success=False,
            error="未配置 AI API Key",
        )
    except AIRequestError:
        return StructuredOutputResult(
            success=False,
            error="AI 调用失败",
        )
    except Exception:
        return StructuredOutputResult(
            success=False,
            error="AI 调用失败",
        )

    parsed_result = parse_json_safely(ai_raw_text)
    if not parsed_result.success:
        return parsed_result

    validation_result = validate_training_parse_output(parsed_result.data)
    if not validation_result.success:
        return StructuredOutputResult(
            success=False,
            error=validation_result.error,
            warnings=validation_result.warnings,
            raw_text=ai_raw_text,
        )

    normalization_result = normalize_exercise_names(
        validation_result.data,
        exercise_names,
    )
    if not normalization_result.success:
        return StructuredOutputResult(
            success=False,
            error=normalization_result.error,
            warnings=normalization_result.warnings,
            raw_text=ai_raw_text,
        )

    return StructuredOutputResult(
        success=True,
        data=normalization_result.data,
        warnings=_merge_warnings(
            validation_result.warnings,
            normalization_result.warnings,
        ),
        raw_text=ai_raw_text,
    )
