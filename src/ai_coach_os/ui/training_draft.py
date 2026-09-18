"""Training draft conversion and state updates; no database writes or widgets."""

from ..services.structured_output import TrainingParseOutput


def clear_training_parse_state(state):
    for key in list(state):
        if str(key).startswith("training_parse_"):
            del state[key]


def bind_training_parse_owner(state, coach_id, member_id):
    owner = (coach_id, member_id)
    if state.get("training_parse_owner") != owner:
        clear_training_parse_state(state)
        state["training_parse_owner"] = owner


def structured_output_to_training_rows(output: TrainingParseOutput, exercise_options):
    # Collapse repeated whitespace, but do not merge distinct words or fuzzy-match.
    def name_key(name):
        return " ".join(name.split()).casefold()

    matches = {}
    for exercise_id, name in exercise_options:
        matches.setdefault(name_key(name), []).append((exercise_id, name))
    rows = []
    for exercise in output.exercises:
        candidates = matches.get(name_key(exercise.exercise_name), [])
        exercise_id, name = candidates[0] if len(candidates) == 1 else (None, exercise.exercise_name)
        rows.append({
            "exercise_id": exercise_id,
            "exercise_name": name,
            "weight": exercise.weight,
            "sets": "" if exercise.sets is None else str(exercise.sets),
            "reps": "" if exercise.reps is None else str(exercise.reps),
            "rpe": "" if exercise.rpe is None else str(exercise.rpe),
            "note": exercise.note,
        })
    return rows


def store_training_draft(state, owner, raw_text, rows, source, feedback="", coach_note="", warnings=()):
    clear_training_parse_state(state)
    messages = list(warnings)
    for row in rows:
        if row["exercise_id"] is None:
            messages.append(f"动作‘{row['exercise_name']}’：动作库未匹配，需要人工选择。")
    if len(rows) > 10:
        messages.append(f"解析到 {len(rows)} 个动作，当前页面最多支持10个，请确认后仅回填前10个动作。")
    state["training_parse_owner"] = owner
    state["training_parse_draft"] = {
        "rows": rows, "raw_text": raw_text,
        "member_feedback": feedback, "coach_note": coach_note,
    }
    state["training_parse_source"] = source
    state["training_parse_warnings"] = list(dict.fromkeys(messages))


def training_form_has_content(state, member_id):
    if state.get("current_training_rows"):
        return True
    prefix = f"training_{member_id}_"
    for field in ("feedback", "coach_note"):
        if state.get(prefix + field):
            return True
    for i in range(10):
        for field in ("exercise", "weight", "sets", "reps", "rpe", "note"):
            if state.get(f"{prefix}{field}_{i}") not in (None, "", "请选择"):
                return True
    return False


def apply_training_draft(state, coach_id, member_id, raw_text, *, overwrite=False, truncate=False):
    """Validate confirmations before changing any existing form state."""
    draft = state.get("training_parse_draft")
    if state.get("training_parse_owner") != (coach_id, member_id) or not draft:
        return "解析草稿已失效，请重新解析。"
    if draft["raw_text"] != raw_text:
        return "原始文本已修改，请重新解析后确认。"
    if not draft["rows"]:
        return "没有解析到有效训练动作，未修改训练表单。"
    if len(draft["rows"]) > 10 and not truncate:
        return "请确认仅回填前10个动作。"
    if training_form_has_content(state, member_id) and not overwrite:
        return "当前训练表单已有内容，请先确认覆盖。"
    rows = [dict(row) for row in draft["rows"][:10]]
    prefix = f"training_{member_id}_"
    for i in range(10):
        for field in ("exercise", "weight", "sets", "reps", "rpe", "note"):
            state.pop(f"{prefix}{field}_{i}", None)
    state["current_training_rows"] = rows
    state[prefix + "count"] = len(rows)
    for i, row in enumerate(rows):
        state[f"{prefix}exercise_{i}"] = row["exercise_id"]
        for field in ("weight", "sets", "reps", "note"):
            state[f"{prefix}{field}_{i}"] = row[field]
        state[f"{prefix}rpe_{i}"] = row["rpe"] or "请选择"
    # Rule parsing extracts only exercises; keep existing feedback and coach notes.
    if state.get("training_parse_source") == "AI智能解析":
        state[prefix + "feedback"] = draft["member_feedback"]
        state[prefix + "coach_note"] = draft["coach_note"]
    state.pop("training_save_message", None)
    clear_training_parse_state(state)
    state["training_parse_owner"] = (coach_id, member_id)
    state["training_parse_notice"] = "解析结果已回填，请核对训练表单；回填操作本身不会保存训练。"
    return None
