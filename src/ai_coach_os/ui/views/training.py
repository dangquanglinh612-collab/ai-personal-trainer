"""Page handler module."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import streamlit as st

from ...repositories.contracts import CoachContext, CoachReadRepository
from ...repositories.member_data import (
    get_training_photos_for_session,
    parse_training_text,
    save_training_session,
    save_uploaded_training_photos,
    update_training_session,
)
from ..helpers import format_last_training
from ..styles import inject_css
from ...config import PROJECT_ROOT
from ...services.structured_output import generate_training_structured_output
from ..training_draft import (
    apply_training_draft, bind_training_parse_owner, clear_training_parse_state,
    store_training_draft, structured_output_to_training_rows, training_form_has_content,
)

from .shell import (
    back_to_member_detail,
    back_to_member_list,
    get_current_member,
    render_page_header,
    render_sidebar,
)


logger = logging.getLogger(__name__)

def render_training_parser(raw_text, exercise_options, coach_id, member_id):
    """Preview first; update existing widgets only after explicit confirmation."""
    state = st.session_state
    bind_training_parse_owner(state, coach_id, member_id)
    st.caption("AI智能解析适合自然语言训练记录；规则解析适合格式较规整的“动作 + 重量 + 组数 + 次数”。")
    ai_clicked = st.button("AI智能解析", use_container_width=True)
    st.caption("备选：内容格式规整，或 AI 暂不可用时，可使用规则解析。")
    rule_clicked = st.button("使用规则解析")
    if ai_clicked or rule_clicked:
        clear_training_parse_state(state)
        state["training_parse_owner"] = (coach_id, member_id)
        if not raw_text.strip():
            state["training_parse_error"] = "请先粘贴训练内容。"
        else:
            try:
                if ai_clicked:
                    with st.spinner("正在解析训练内容…"):
                        result = generate_training_structured_output(
                            raw_text=raw_text,
                            exercise_names=[name for _, name in exercise_options],
                        )
                    if not result.success:
                        state["training_parse_error"] = f"AI解析失败：{result.error}。可点击“使用规则解析”。"
                    elif not result.data.exercises:
                        state["training_parse_error"] = "AI没有解析到有效训练动作，请检查原文本或使用规则解析。"
                    else:
                        store_training_draft(
                            state, (coach_id, member_id), raw_text,
                            structured_output_to_training_rows(result.data, exercise_options),
                            "AI智能解析", result.data.member_feedback, result.data.coach_note,
                            result.warnings,
                        )
                else:
                    rows = parse_training_text(raw_text, exercise_options)
                    warnings = []
                    if len([line for line in raw_text.splitlines() if line.strip()]) > 10:
                        warnings.append("规则解析最多提取前10行，请核对原文中其余动作。")
                    if rows:
                        store_training_draft(state, (coach_id, member_id), raw_text, rows, "规则解析", warnings=warnings)
                    else:
                        state["training_parse_error"] = "没有解析到有效内容，请检查原文。"
            except Exception:
                logger.exception("Training text parsing failed")
                state["training_parse_error"] = "解析失败，请重试或使用规则解析。训练表单未修改。"

    if state.get("training_parse_error"):
        st.error(state["training_parse_error"])
    if state.get("training_parse_notice"):
        st.info(state["training_parse_notice"])
    draft = state.get("training_parse_draft")
    if not draft:
        return
    st.subheader("AI解析草稿" if state["training_parse_source"] == "AI智能解析" else "规则解析草稿")
    st.caption(f"解析来源：{state['training_parse_source']}。以下内容尚未保存，只是解析结果。")
    for warning in state["training_parse_warnings"]:
        st.warning(warning)
    for i, row in enumerate(draft["rows"], 1):
        st.text(
            f"动作{i}：{row['exercise_name']}\n"
            f"重量：{row['weight']}　组数：{row['sets']}　次数：{row['reps']}　RPE：{row['rpe'] or '请选择'}\n"
            f"备注：{row['note']}"
        )
    st.text(f"会员反馈：{draft['member_feedback']}")
    st.text(f"教练备注：{draft['coach_note']}")
    overwrite = False
    has_content = training_form_has_content(state, member_id)
    if has_content:
        overwrite = st.checkbox(
            "当前训练表单已有内容，继续将覆盖当前动作表单及 AI 提取的反馈、备注。确认覆盖？",
            key="training_parse_overwrite",
        )
    truncate = False
    if len(draft["rows"]) > 10:
        truncate = st.checkbox("确认仅回填前10个动作，其余动作不回填", key="training_parse_truncate")
    changed = raw_text != draft["raw_text"]
    if changed:
        st.warning("原始文本已修改，请重新解析后确认。")
    if st.button(
        "确认并回填训练表单",
        disabled=changed or (has_content and not overwrite) or (len(draft["rows"]) > 10 and not truncate),
    ):
        error = apply_training_draft(
            state, coach_id, member_id, raw_text, overwrite=overwrite, truncate=truncate,
        )
        if error:
            st.warning(error)
        else:
            # The existing form is rendered below, so no early rerun is needed.
            st.info(state["training_parse_notice"])


def start_training_page(repository: CoachReadRepository, coach: CoachContext):
    inject_css()
    render_sidebar()

    member = get_current_member(repository, coach)

    if not member:
        st.error("没有选择会员。")
        if st.button("返回会员列表"):
            back_to_member_list()
        return

    member_id = member.id
    remaining_lessons = member.remaining_lessons
    coach_id = coach.coach_id
    owner = (coach_id, member_id)
    bind_training_parse_owner(st.session_state, coach_id, member_id)
    if st.session_state.get("training_state_owner") != owner:
        st.session_state.pop("current_training_session_id", None)
        st.session_state.pop("current_training_rows", None)
        st.session_state.pop("training_save_message", None)
        st.session_state.pop("training_save_status", None)
        st.session_state.pop("training_photo_warning", None)
        st.session_state.training_state_owner = owner

    if st.button("返回会员主页"):
        back_to_member_detail()

    render_page_header(
        eyebrow="训练记录",
        title=f"开始上课：{member.name}",
        subtitle="记录本次训练动作、训练反馈和教练备注。"
    )

    st.caption(
        f"剩余 {remaining_lessons} 节课 · 目标：{member.goal or '未填写'} · "
        f"最近训练：{format_last_training(member.last_training_date)}"
    )

    date_key = f"training_{member_id}_date"
    raw_key = f"training_{member_id}_raw"
    count_key = f"training_{member_id}_count"
    feedback_key = f"training_{member_id}_feedback"
    coach_note_key = f"training_{member_id}_coach_note"

    training_date = st.date_input("训练日期", value=date.today(), key=date_key)
    # Render parsing before the action widgets so confirmed drafts can fill them.
    paste_section = st.expander("智能粘贴（可选）", expanded=False)
    with paste_section:
        raw_text = st.text_area(
            "智能粘贴训练安排",
            key=raw_key,
            height=140,
            help="可以粘贴类似“罗马尼亚硬拉 40kg 4组 10次 RPE8”的内容，系统会尝试解析到动作列表。",
        )

    try:
        exercise_options = repository.list_exercises(coach)
    except Exception:
        logger.exception("Exercise library query failed")
        exercise_options = None
    if not exercise_options:
        # Preserve hidden form widgets across Streamlit's end-of-run cleanup.
        for key in list(st.session_state):
            if (
                str(key).startswith(f"training_{member_id}_")
                and not str(key).startswith(f"training_{member_id}_photos_")
                and key not in (date_key, raw_key)
            ):
                st.session_state[key] = st.session_state[key]
        st.error("动作库加载失败或为空，请稍后重试。原文及已有训练表单已保留。")
        return

    option_name_by_id = {option.id: option.name for option in exercise_options}
    exercise_ids = [None, *option_name_by_id]
    with paste_section:
        render_training_parser(raw_text, list(option_name_by_id.items()), coach_id, member_id)

    parsed_count = len(st.session_state.get("current_training_rows", []))
    if count_key not in st.session_state:
        st.session_state[count_key] = max(1, min(10, parsed_count or 3))

    st.subheader("动作记录")
    exercise_count = st.number_input(
        "今日动作数", min_value=1, max_value=10, step=1, key=count_key
    )
    exercise_rows = []
    rpe_options = ["请选择"] + [str(value) for value in range(1, 11)]
    for i in range(int(exercise_count)):
        with st.container(border=True):
            st.markdown(f"**动作 {i + 1}**")
            exercise_key = f"training_{member_id}_exercise_{i}"
            if st.session_state.get(exercise_key) not in exercise_ids:
                st.session_state[exercise_key] = None
            selected_id = st.selectbox(
                "动作名称",
                exercise_ids,
                format_func=lambda option_id: option_name_by_id.get(option_id, "请选择动作"),
                key=f"training_{member_id}_exercise_{i}",
            )
            if selected_id is None:
                original_rows = st.session_state.get("current_training_rows", [])
                original_name = original_rows[i]["exercise_name"] if i < len(original_rows) else ""
                if original_name:
                    st.warning(f"请确认解析动作：{original_name}，并从动作库选择。")
            col_weight, col_sets = st.columns(2)
            with col_weight:
                weight = st.text_input("重量", key=f"training_{member_id}_weight_{i}")
            with col_sets:
                sets = st.text_input("组数", key=f"training_{member_id}_sets_{i}")
            col_reps, col_rpe = st.columns(2)
            with col_reps:
                reps = st.text_input("次数", key=f"training_{member_id}_reps_{i}")
            with col_rpe:
                rpe_key = f"training_{member_id}_rpe_{i}"
                if st.session_state.get(rpe_key) not in rpe_options:
                    st.session_state[rpe_key] = "请选择"
                rpe = st.selectbox(
                    "RPE（主观强度）", rpe_options,
                    key=rpe_key,
                )
            with st.expander("动作备注（可选）", expanded=False):
                exercise_note = st.text_input("备注", key=f"training_{member_id}_note_{i}")
        exercise_rows.append({
            "exercise_id": selected_id,
            "exercise_name": option_name_by_id.get(selected_id, ""),
            "weight": weight.strip(),
            "sets": sets.strip(),
            "reps": reps.strip(),
            "rpe": "" if rpe == "请选择" else rpe,
            "note": exercise_note.strip(),
        })

    st.subheader("训练反馈")
    member_feedback = st.text_area("会员反馈", key=feedback_key, height=100)
    with st.expander("教练备注（可选）", expanded=False):
        coach_note = st.text_area("教练备注", key=coach_note_key, height=100)

    with st.expander("训练照片 / 打卡照（可选）", expanded=False):
        st.caption(
            "可上传本次训练相关照片，例如会员打卡照、动作姿势照、体态对比照。"
            "照片会随本次训练记录保存。"
        )
        st.caption("请在会员同意后上传训练照片，避免上传无关或敏感图片。")

        photo_version_key = f"training_{member_id}_photo_upload_version"
        if photo_version_key not in st.session_state:
            st.session_state[photo_version_key] = 0
        photo_version = st.session_state[photo_version_key]

        uploaded_training_photos = st.file_uploader(
            "上传训练照片",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key=f"training_{member_id}_photos_{photo_version}",
        )
        photo_caption = st.text_input(
            "照片备注",
            placeholder="例如：深蹲侧面动作照 / 今日训练打卡照 / 体态对比照",
            key=f"training_{member_id}_photo_caption_{photo_version}",
        )

    current_session_id = st.session_state.get("current_training_session_id")
    st.subheader("保存本次训练")
    st.caption("可选备注和照片可以留空；保存后仍可继续修改本次记录。")
    save_label = "更新本次训练记录" if current_session_id else "保存并结束上课"
    if st.button(save_label, type="primary", use_container_width=True):
        if any(row["exercise_id"] not in option_name_by_id for row in exercise_rows):
            st.error("还有未确认的训练动作，请先从动作库选择正确动作。")
            return
        try:
            training_date_text = training_date.isoformat()
            if current_session_id:
                update_training_session(
                    coach_id, current_session_id, training_date_text, member_feedback.strip(),
                    coach_note.strip(), raw_text, exercise_rows,
                )
                st.session_state.training_save_message = "训练记录已更新成功，本次未重复扣课。"
            else:
                session_id, should_deduct = save_training_session(
                    coach_id, member_id, training_date_text, member_feedback.strip(),
                    coach_note.strip(), raw_text, exercise_rows,
                )
                st.session_state.current_training_session_id = session_id
                if should_deduct:
                    if remaining_lessons > 0:
                        st.session_state.training_save_message = "训练记录已保存成功，本次已扣除 1 节课。"
                    else:
                        st.session_state.training_save_message = "训练记录已保存成功，当前剩余课时为 0，本次未扣课。"
                else:
                    st.session_state.training_save_message = "训练记录已保存成功，该会员当天已有训练记录，本次未重复扣课。"

            st.session_state.pop("training_photo_warning", None)
            if uploaded_training_photos:
                photo_session_id = (
                    current_session_id
                    if current_session_id is not None
                    else session_id
                )
                attempted_photo_count = len(uploaded_training_photos)
                try:
                    saved_photo_ids = save_uploaded_training_photos(
                        coach_id=coach_id,
                        member_id=member_id,
                        session_id=photo_session_id,
                        uploaded_files=uploaded_training_photos,
                        caption=photo_caption.strip(),
                    )
                    saved_photo_count = len(saved_photo_ids)
                    if saved_photo_count:
                        if current_session_id:
                            st.session_state.training_save_message += (
                                f" 已保存 {saved_photo_count} 张新训练照片。"
                            )
                        else:
                            st.session_state.training_save_message += (
                                f" 已保存 {saved_photo_count} 张训练照片。"
                            )
                    if saved_photo_count < attempted_photo_count:
                        st.session_state.training_photo_warning = (
                            "训练记录已保存，但部分照片保存失败，请稍后重新选择失败的照片上传。"
                        )
                except Exception:
                    logger.exception("Training photo save failed")
                    st.session_state.training_photo_warning = (
                        "训练记录已保存，但照片保存失败，请稍后重试。"
                    )
                finally:
                    st.session_state[photo_version_key] = photo_version + 1

            st.session_state.current_training_rows = exercise_rows
            st.session_state.training_save_status = "success"
            st.rerun()
        except Exception:
            logger.exception("Training save failed")
            st.session_state.training_save_status = "error"
            st.session_state.training_save_message = "训练记录保存失败，请重试。"
            st.rerun()

    message = st.session_state.get("training_save_message")
    if message:
        if st.session_state.get("training_save_status") == "success":
            st.success(message)
        else:
            st.error(message)

    photo_warning = st.session_state.get("training_photo_warning")
    if photo_warning:
        st.warning(photo_warning)

    if current_session_id:
        st.caption("本次记录已保存。上方显示的是上次保存结果；继续修改后，请点击“更新本次训练记录”。")
        if st.button("返回会员", key=f"training_{member_id}_back_after_save", use_container_width=True):
            back_to_member_detail()


# =========================
# 页面：训练历史
# =========================

def training_history_page(repository: CoachReadRepository, coach: CoachContext):
    inject_css()
    render_sidebar()

    member = get_current_member(repository, coach)

    if not member:
        st.error("没有选择会员。")
        if st.button("返回会员列表"):
            back_to_member_list()
        return

    if st.button("返回会员主页"):
        back_to_member_detail()

    render_page_header(
        eyebrow="训练历史",
        title=f"训练历史：{member.name}",
        subtitle="查看每节课的动作记录、会员反馈和教练备注。"
    )

    sessions = repository.list_training_history(coach, member.id)
    if not sessions:
        st.info("暂无训练记录，首次训练后，记录会显示在这里。")
        return

    for session in sessions:
        with st.expander(f"{session.training_date} 训练记录"):
            st.markdown(f"**会员反馈：** {session.member_feedback or '未填写'}")
            st.markdown(f"**教练备注：** {session.coach_note or '未填写'}")
            if session.raw_paste_text:
                st.caption("原始粘贴内容")
                st.code(session.raw_paste_text, language=None)

            if session.exercises:
                table_rows = [
                    {
                        "序号": index,
                        "动作": exercise.exercise_name,
                        "重量": exercise.weight,
                        "组数": exercise.sets,
                        "次数": exercise.reps,
                        "RPE": exercise.rpe,
                        "备注": exercise.note,
                    }
                    for index, exercise in enumerate(session.exercises, start=1)
                ]
                st.dataframe(table_rows, use_container_width=True, hide_index=True)
            else:
                st.caption("本节课没有动作明细。")

            session_photos = get_training_photos_for_session(
                coach.coach_id,
                member.id,
                session.id,
            )
            if session_photos:
                st.markdown("**训练照片**")
                photo_columns = st.columns(2)
                project_root = PROJECT_ROOT
                for photo_index, photo in enumerate(session_photos):
                    (
                        photo_id,
                        file_path,
                        original_filename,
                        caption,
                        photo_created_at,
                    ) = photo
                    image_path = Path(file_path)
                    if not image_path.is_absolute():
                        image_path = project_root / image_path

                    with photo_columns[photo_index % 2]:
                        if image_path.is_file():
                            st.image(
                                str(image_path),
                                caption=caption or original_filename or None,
                                use_container_width=True,
                            )
                        else:
                            st.caption(
                                f"照片文件暂不可用：{original_filename or '未命名照片'}"
                            )


# =========================
# 页面：课表占位
# =========================
