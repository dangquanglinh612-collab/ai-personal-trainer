"""AI prompt construction, fallback behavior, and plan persistence."""

import json
import os
import re
import urllib.request
from datetime import date, datetime

import streamlit as st

from ..repositories.database import get_conn


def _ensure_member_belongs_to_coach(cursor, coach_id, member_id):
    cursor.execute(
        "SELECT 1 FROM members WHERE coach_id = ? AND id = ? LIMIT 1",
        (coach_id, member_id),
    )
    if cursor.fetchone() is None:
        raise ValueError("会员不存在或不属于当前教练。")


def _member_analysis_fields(member):
    if isinstance(member, dict):
        return {
            "name": member.get("name", "未命名会员"),
            "remaining_lessons": member.get("remaining_lessons", 0),
            "goal": member.get("goal", ""),
            "last_training_date": member.get("last_training_date", ""),
            "phone": member.get("phone", ""),
            "note": member.get("note", ""),
        }

    values = list(member or ()) + [""] * 9
    return {
        "name": values[1] or "未命名会员",
        "remaining_lessons": values[2],
        "goal": values[3],
        "last_training_date": values[4],
        "phone": values[6],
        "note": values[7],
    }


def build_ai_analysis_prompt(member, recent_sessions, exercise_names, extra_note):
    member_info = _member_analysis_fields(member)
    session_lines = []
    for index, session in enumerate(recent_sessions or [], start=1):
        exercise_lines = []
        for exercise in session.get("exercises", []):
            exercise_lines.append(
                "  - {name}｜重量：{weight}｜组数：{sets}｜次数：{reps}｜"
                "RPE（主观强度）：{rpe}｜备注：{note}".format(
                    name=exercise.get("exercise_name") or "未填写",
                    weight=exercise.get("weight") or "未填写",
                    sets=exercise.get("sets") or "未填写",
                    reps=exercise.get("reps") or "未填写",
                    rpe=exercise.get("rpe") or "未填写",
                    note=exercise.get("note") or "无",
                )
            )
        if not exercise_lines:
            exercise_lines.append("  - 本次训练暂无动作明细")
        session_lines.extend([
            f"第 {index} 节｜日期：{session.get('training_date') or '未填写'}",
            *exercise_lines,
            f"  - 会员反馈：{session.get('member_feedback') or '未填写'}",
            f"  - 教练备注：{session.get('coach_note') or '未填写'}",
            f"  - 原始粘贴内容：{session.get('raw_paste_text') or '无'}",
        ])

    sessions_text = "\n".join(session_lines) if session_lines else "暂无训练记录。"
    library_text = "、".join(exercise_names or []) or "动作库暂无数据"
    return f"""你是一个谨慎、专业、实用的私教助理。

会员信息：
- 姓名：{member_info['name']}
- 训练目标：{member_info['goal'] or '未填写'}
- 剩余课时：{member_info['remaining_lessons']}
- 最近训练日期：{member_info['last_training_date'] or '暂无'}
- 联系电话：{member_info['phone'] or '未填写'}
- 会员备注：{member_info['note'] or '无'}

最近训练记录（最多 5 节）：
{sessions_text}

教练补充信息：
{extra_note or '无'}

可用动作库：
{library_text}

请使用中文输出 markdown，面向私教给出具体、实用、克制的判断。不要编造训练记录里没有的数据；
如果训练记录不足，必须明确写出“当前记录较少，分析仅供参考”；下次训练建议尽量使用动作库中的动作；
不做医疗诊断，风险提醒保持保守。严格使用以下结构：

# AI 训练分析

## 1. 近期训练总结

## 2. 会员状态判断

## 3. 风险提醒

## 4. 下次训练建议

## 5. 教练沟通话术
"""


def generate_fallback_ai_analysis(member, recent_sessions, exercise_names, extra_note):
    member_info = _member_analysis_fields(member)
    sessions = recent_sessions or []
    exercise_count = sum(len(item.get("exercises", [])) for item in sessions)
    latest = sessions[0] if sessions else None

    if latest:
        latest_names = [
            item.get("exercise_name", "")
            for item in latest.get("exercises", []) if item.get("exercise_name")
        ]
        recent_summary = (
            f"已读取最近 {len(sessions)} 节训练，共 {exercise_count} 条动作记录。"
            f"最近一次训练日期为 {latest.get('training_date') or '未填写'}；"
            f"记录动作包括{'、'.join(latest_names) if latest_names else '暂无动作明细'}。"
        )
        data_notice = (
            "当前记录较少，分析仅供参考。"
            if len(sessions) < 3
            else "分析仅基于现有训练记录、反馈和备注，不补充未记录的信息。"
        )
    else:
        recent_summary = "当前没有可用训练记录，无法判断动作完成质量、训练量或强度变化。"
        data_notice = "当前记录较少，分析仅供参考。建议先完成并保存至少一次训练记录。"

    rpe_values = []
    for session in sessions:
        for exercise in session.get("exercises", []):
            try:
                rpe_values.append(float(exercise.get("rpe")))
            except (TypeError, ValueError):
                continue
    intensity_note = (
        "现有记录中出现 RPE 9 或以上，下一次训练应先确认恢复情况，并保守控制训练量。"
        if any(value >= 9 for value in rpe_values)
        else "现有记录未显示明确的高强度风险信号；仍需在训练前询问睡眠、疲劳和不适情况。"
    )

    suggested = list(exercise_names or [])[:3]
    suggestion_text = "、".join(suggested) if suggested else "从会员已熟悉的基础动作中选择 2—3 个"
    extra_context = f"教练补充信息提到：{extra_note.strip()}。" if extra_note and extra_note.strip() else "教练暂未补充额外情况。"

    return f"""当前未配置 API Key 或 AI 调用失败，以下为本地模拟分析结果。

# AI 训练分析

## 1. 近期训练总结

{recent_summary} {data_notice}

## 2. 会员状态判断

会员训练目标为“{member_info['goal'] or '未填写'}”，剩余课时为 {member_info['remaining_lessons']}。{extra_context} 当前信息只能用于训练安排参考，不能替代现场观察和沟通。

## 3. 风险提醒

{intensity_note} 如会员反馈持续疼痛、眩晕或明显不适，应暂停相关训练并建议其寻求专业医疗意见；本报告不做医疗诊断。

## 4. 下次训练建议

可优先考虑动作库中的：{suggestion_text}。先用轻到中等强度完成热身组，再根据动作稳定性和会员即时反馈决定是否加量；数据不足时不建议直接追求重量或训练量突破。

## 5. 教练沟通话术

“我看了你最近的训练记录。下次课我们先确认一下这几天的睡眠、疲劳和身体感受，再从熟悉的动作开始，根据当天状态调整重量和组数，重点保证动作稳定。”
"""


def _read_ai_secret(name):
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, "")


class AIConfigurationError(RuntimeError):
    """Raised when no supported AI API key is configured."""


class AIRequestError(RuntimeError):
    """Raised when an AI text request fails or returns no usable content."""


def request_ai_text(prompt: str, temperature: float = 0.1) -> str:
    """Use the existing OpenAI-compatible transport and return raw AI text."""
    deepseek_key = _read_ai_secret("DEEPSEEK_API_KEY")
    openai_key = _read_ai_secret("OPENAI_API_KEY")
    api_key = deepseek_key or openai_key
    if not api_key:
        raise AIConfigurationError("未配置 AI API Key")

    if deepseek_key:
        endpoint = "https://api.deepseek.com/chat/completions"
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    else:
        endpoint = "https://api.openai.com/v1/chat/completions"
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("AI 返回内容为空")
        return content.strip()
    except Exception as exc:
        raise AIRequestError("AI 调用失败") from exc


def generate_ai_analysis(prompt, member=None, recent_sessions=None,
                         exercise_names=None, extra_note=""):
    deepseek_key = _read_ai_secret("DEEPSEEK_API_KEY")
    openai_key = _read_ai_secret("OPENAI_API_KEY")
    api_key = deepseek_key or openai_key
    if not api_key:
        return generate_fallback_ai_analysis(
            member, recent_sessions, exercise_names, extra_note
        )

    if deepseek_key:
        endpoint = "https://api.deepseek.com/chat/completions"
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    else:
        endpoint = "https://api.openai.com/v1/chat/completions"
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"].strip()
        if not content:
            raise ValueError("AI 返回内容为空")
        return content
    except Exception:
        return generate_fallback_ai_analysis(
            member, recent_sessions, exercise_names, extra_note
        )


def save_ai_analysis_report(coach_id, member_id, report_markdown, input_summary):
    conn = get_conn()
    try:
        c = conn.cursor()
        _ensure_member_belongs_to_coach(c, coach_id, member_id)
        c.execute(
            """
            INSERT INTO ai_analysis_reports (
                coach_id, member_id, report_date, report_markdown,
                input_summary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                coach_id, member_id, str(date.today()), report_markdown,
                input_summary or "", datetime.now().isoformat(timespec="seconds"),
            )
        )
        report_id = c.lastrowid
        conn.commit()
        return report_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_ai_analysis_reports(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, report_date, report_markdown, input_summary, created_at
            FROM ai_analysis_reports
            WHERE coach_id = ? AND member_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (coach_id, member_id)
        )
        return c.fetchall()
    finally:
        conn.close()


def get_latest_ai_analysis_report(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, report_date, report_markdown, input_summary, created_at
            FROM ai_analysis_reports
            WHERE coach_id = ? AND member_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (coach_id, member_id)
        )
        return c.fetchone()
    finally:
        conn.close()


def get_latest_training_plan(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, plan_date, status, source_analysis_report_id,
                   plan_goal, coach_note, raw_ai_plan, created_at, updated_at
            FROM training_plans
            WHERE coach_id = ? AND member_id = ?
            ORDER BY plan_date DESC, id DESC
            LIMIT 1
            """,
            (coach_id, member_id)
        )
        return c.fetchone()
    finally:
        conn.close()


def get_training_plan_exercises(coach_id, plan_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT e.id, e.exercise_id, e.exercise_name, e.target_weight,
                   e.sets, e.reps, e.target_rpe, e.note, e.sort_order
            FROM training_plan_exercises e
            INNER JOIN training_plans p ON p.id = e.plan_id
            WHERE e.plan_id = ? AND p.coach_id = ?
            ORDER BY e.sort_order ASC, e.id ASC
            """,
            (plan_id, coach_id)
        )
        return c.fetchall()
    finally:
        conn.close()


def get_training_plans_for_member(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, plan_date, status, source_analysis_report_id,
                   plan_goal, coach_note, raw_ai_plan, created_at, updated_at
            FROM training_plans
            WHERE coach_id = ? AND member_id = ?
            ORDER BY plan_date DESC, id DESC
            """,
            (coach_id, member_id)
        )
        return c.fetchall()
    finally:
        conn.close()


def build_ai_plan_prompt(member, recent_sessions, latest_ai_report,
                         exercise_names, extra_note):
    member_info = _member_analysis_fields(member)
    session_lines = []
    for index, session in enumerate(recent_sessions or [], start=1):
        session_lines.append(
            f"第 {index} 节｜日期：{session.get('training_date') or '未填写'}"
        )
        exercises = session.get("exercises", [])
        if exercises:
            for exercise in exercises:
                session_lines.append(
                    "  - {name}｜重量：{weight}｜组数：{sets}｜次数：{reps}｜"
                    "RPE（主观强度）：{rpe}｜动作备注：{note}".format(
                        name=exercise.get("exercise_name") or "未填写",
                        weight=exercise.get("weight") or "未填写",
                        sets=exercise.get("sets") or "未填写",
                        reps=exercise.get("reps") or "未填写",
                        rpe=exercise.get("rpe") or "未填写",
                        note=exercise.get("note") or "无",
                    )
                )
        else:
            session_lines.append("  - 本次训练暂无动作明细")
        session_lines.append(
            f"  - 会员反馈：{session.get('member_feedback') or '未填写'}"
        )
        session_lines.append(
            f"  - 教练备注：{session.get('coach_note') or '未填写'}"
        )

    sessions_text = "\n".join(session_lines) if session_lines else "暂无训练记录。"
    if isinstance(latest_ai_report, dict):
        latest_report_text = latest_ai_report.get("report_markdown", "")
    elif latest_ai_report:
        latest_report_text = latest_ai_report[2]
    else:
        latest_report_text = ""
    latest_report_text = latest_report_text or "暂无 AI 分析报告。"
    library_text = "、".join(exercise_names or []) or "动作库暂无数据"
    output_example = json.dumps(
        {
            "plan_goal": "本次训练计划目标",
            "coach_note": "给教练看的整体备注",
            "exercises": [
                {
                    "exercise_name": "动作名称",
                    "target_weight": "目标重量",
                    "sets": "组数",
                    "reps": "次数",
                    "target_rpe": "目标RPE",
                    "note": "动作备注",
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    return f"""你是一个谨慎、专业、实用的私教排课助理。

会员信息：
- 姓名：{member_info['name']}
- 训练目标：{member_info['goal'] or '未填写'}
- 剩余课时：{member_info['remaining_lessons']}
- 最近训练日期：{member_info['last_training_date'] or '暂无'}
- 会员备注：{member_info['note'] or '无'}

最近训练记录（最多 5 节）：
{sessions_text}

最新 AI 分析报告：
{latest_report_text}

教练补充要求：
{extra_note or '无'}

可用动作库：
{library_text}

只返回可解析 JSON，不要返回 markdown、代码围栏或解释文字。JSON 结构必须是：
{output_example}

约束：
- exercises 建议 3 到 6 个，最多不超过 10 个。
- exercise_name 必须尽量来自动作库，不要编造动作库中没有的动作。
- 数据不足时保守安排，不做医疗诊断。
- 如反馈中出现疼痛或不适，降低强度或避开相关动作。
- 长期未训练时不要突然安排高强度。
- 减脂目标可安排力量训练与动作库已有的低冲击有氧。
- 增肌目标可渐进超负荷，但不要过度激进。
- 改善体态目标优先核心、臀腿后侧、背部控制和动作质量。
- 建议目标 RPE 为 6 到 8，最终由教练确认和修改。
"""


def generate_fallback_training_plan(member, recent_sessions,
                                    exercise_names, extra_note):
    member_info = _member_analysis_fields(member)
    available_names = [str(name) for name in (exercise_names or []) if name]
    goal = member_info.get("goal", "") or ""

    if "改善体态" in goal or "体态" in goal:
        preferred_names = [
            "罗马尼亚硬拉", "臀推", "坐姿划船", "高位下拉", "平板支撑"
        ]
        plan_goal = "改善动作控制，加强臀腿后侧、背部与核心稳定"
    elif "减脂" in goal:
        preferred_names = [
            "跑步机快走", "椭圆机", "深蹲", "坐姿划船", "平板支撑"
        ]
        plan_goal = "完成中等强度全身训练，并加入低冲击有氧"
    elif "增肌" in goal:
        preferred_names = [
            "深蹲", "罗马尼亚硬拉", "卧推", "坐姿划船", "高位下拉"
        ]
        plan_goal = "在动作稳定的前提下完成适度渐进训练"
    else:
        preferred_names = [
            "深蹲", "罗马尼亚硬拉", "坐姿划船", "高位下拉", "平板支撑"
        ]
        plan_goal = "完成保守、均衡且便于现场调整的全身训练"

    selected_names = []
    for preferred_name in preferred_names:
        if preferred_name in available_names and preferred_name not in selected_names:
            selected_names.append(preferred_name)
    for available_name in available_names:
        if available_name not in selected_names:
            selected_names.append(available_name)
        if len(selected_names) >= 5:
            break
    selected_names = selected_names[:5]

    risk_text = "训练前再次确认会员近期恢复、疼痛与不适情况。"
    combined_context = " ".join([
        str(extra_note or ""),
        str(member_info.get("note") or ""),
        " ".join(
            str(session.get("member_feedback") or "")
            for session in (recent_sessions or [])
        ),
    ])
    has_discomfort = any(
        keyword in combined_context
        for keyword in ("疼", "痛", "不适", "疲劳", "膝盖", "腰")
    )
    is_long_inactive = False
    try:
        last_training = date.fromisoformat(
            str(member_info.get("last_training_date") or "")
        )
        is_long_inactive = (date.today() - last_training).days > 14
    except ValueError:
        pass

    target_rpe = "6" if has_discomfort or is_long_inactive else "7"
    if has_discomfort:
        risk_text = "现有信息提到疼痛、不适或疲劳，请降低强度并避开诱发不适的动作。"
    elif is_long_inactive:
        risk_text = "会员已有一段时间未训练，请从低到中等强度恢复，不要突然增加重量或训练量。"

    exercises = []
    for exercise_name in selected_names:
        is_cardio = exercise_name in {"跑步机快走", "椭圆机"}
        exercises.append({
            "exercise_name": exercise_name,
            "target_weight": "按当天状态调整" if not is_cardio else "",
            "sets": "1" if is_cardio else "3",
            "reps": "15-20分钟" if is_cardio else "10-12",
            "target_rpe": "6" if is_cardio else target_rpe,
            "note": "先完成热身组，动作稳定后再决定是否加量。",
        })

    extra_text = (
        f" 教练补充要求：{extra_note.strip()}"
        if extra_note and extra_note.strip()
        else ""
    )
    return {
        "plan_goal": plan_goal,
        "coach_note": (
            "当前未配置 API Key 或 AI 调用失败，以下为本地模拟训练计划。"
            f"{risk_text}{extra_text}"
        ),
        "exercises": exercises,
    }


def generate_ai_training_plan(prompt, member=None, recent_sessions=None,
                              exercise_names=None, extra_note=""):
    deepseek_key = _read_ai_secret("DEEPSEEK_API_KEY")
    openai_key = _read_ai_secret("OPENAI_API_KEY")
    api_key = deepseek_key or openai_key
    if not api_key:
        return generate_fallback_training_plan(
            member, recent_sessions, exercise_names, extra_note
        )

    if deepseek_key:
        endpoint = "https://api.deepseek.com/chat/completions"
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    else:
        endpoint = "https://api.openai.com/v1/chat/completions"
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace < 0 or last_brace <= first_brace:
            raise ValueError("AI 返回内容不是 JSON")
        ai_plan = json.loads(content[first_brace:last_brace + 1])
        if not isinstance(ai_plan, dict) or not isinstance(
            ai_plan.get("exercises"), list
        ):
            raise ValueError("AI 训练计划结构不完整")
        return ai_plan
    except Exception:
        return generate_fallback_training_plan(
            member, recent_sessions, exercise_names, extra_note
        )


def _plan_text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def normalize_ai_plan_to_rows(ai_plan, exercise_options):
    if not exercise_options:
        return []

    safe_plan = ai_plan if isinstance(ai_plan, dict) else {}
    raw_exercises = safe_plan.get("exercises", [])
    if not isinstance(raw_exercises, list):
        raw_exercises = []

    option_name_by_id = dict(exercise_options)
    option_id_by_name = {
        str(name).strip().casefold(): exercise_id
        for exercise_id, name in exercise_options
    }
    default_exercise_id, default_exercise_name = exercise_options[0]
    rows = []

    for raw_exercise in raw_exercises[:10]:
        exercise = raw_exercise if isinstance(raw_exercise, dict) else {}
        original_name = _plan_text(exercise.get("exercise_name"))
        matched_id = option_id_by_name.get(original_name.casefold())
        note = _plan_text(exercise.get("note"))
        if matched_id is None:
            matched_id = default_exercise_id
            matched_name = default_exercise_name
            if original_name:
                mismatch_note = f"AI 原始动作：{original_name}"
                note = f"{mismatch_note}；{note}" if note else mismatch_note
        else:
            matched_name = option_name_by_id[matched_id]

        target_rpe = _plan_text(exercise.get("target_rpe"))
        if target_rpe not in {str(value) for value in range(1, 11)}:
            target_rpe = ""
        rows.append({
            "exercise_id": matched_id,
            "exercise_name": matched_name,
            "target_weight": _plan_text(exercise.get("target_weight")),
            "sets": _plan_text(exercise.get("sets")),
            "reps": _plan_text(exercise.get("reps")),
            "target_rpe": target_rpe,
            "note": note,
        })

    return rows


def _insert_training_plan_exercises(cursor, plan_id, exercise_rows):
    for sort_order, row in enumerate(exercise_rows or []):
        cursor.execute(
            """
            INSERT INTO training_plan_exercises (
                plan_id, exercise_id, exercise_name, target_weight,
                sets, reps, target_rpe, note, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                row.get("exercise_id"),
                row.get("exercise_name", ""),
                row.get("target_weight", ""),
                row.get("sets", ""),
                row.get("reps", ""),
                row.get("target_rpe", ""),
                row.get("note", ""),
                sort_order,
            )
        )


def save_training_plan(coach_id, member_id, plan_date, plan_goal,
                       coach_note, raw_ai_plan, exercise_rows,
                       source_analysis_report_id=None):
    conn = get_conn()
    try:
        c = conn.cursor()
        _ensure_member_belongs_to_coach(c, coach_id, member_id)
        if source_analysis_report_id is not None:
            c.execute(
                """
                SELECT 1 FROM ai_analysis_reports
                WHERE id = ? AND coach_id = ? AND member_id = ?
                LIMIT 1
                """,
                (source_analysis_report_id, coach_id, member_id),
            )
            if c.fetchone() is None:
                raise ValueError("AI 分析报告不存在或不属于当前教练和会员。")

        now = datetime.now().isoformat(timespec="seconds")
        c.execute(
            """
            INSERT INTO training_plans (
                coach_id, member_id, plan_date, status,
                source_analysis_report_id, plan_goal, coach_note,
                raw_ai_plan, created_at, updated_at
            )
            VALUES (?, ?, ?, 'confirmed', ?, ?, ?, ?, ?, ?)
            """,
            (
                coach_id,
                member_id,
                str(plan_date),
                source_analysis_report_id,
                plan_goal,
                coach_note,
                raw_ai_plan,
                now,
                now,
            )
        )
        plan_id = c.lastrowid
        _insert_training_plan_exercises(c, plan_id, exercise_rows)
        conn.commit()
        return plan_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_training_plan(coach_id, plan_id, plan_date, plan_goal, coach_note,
                         raw_ai_plan, exercise_rows):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            UPDATE training_plans
            SET plan_date = ?, plan_goal = ?, coach_note = ?,
                raw_ai_plan = ?, updated_at = ?
            WHERE id = ? AND coach_id = ?
            """,
            (
                str(plan_date),
                plan_goal,
                coach_note,
                raw_ai_plan,
                datetime.now().isoformat(timespec="seconds"),
                plan_id,
                coach_id,
            )
        )
        if c.rowcount != 1:
            raise ValueError("训练计划不存在或不属于当前教练。")
        c.execute(
            "DELETE FROM training_plan_exercises WHERE plan_id = ?",
            (plan_id,)
        )
        _insert_training_plan_exercises(c, plan_id, exercise_rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
