"""Page handler module."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import streamlit as st

from ...repositories.member_data import (
    get_exercise_options,
    get_member_by_id,
    get_recent_training_context,
)
from ...services.ai import (
    _plan_text,
    build_ai_plan_prompt,
    generate_ai_training_plan,
    generate_fallback_training_plan,
    get_latest_ai_analysis_report,
    get_training_plan_exercises,
    get_training_plans_for_member,
    normalize_ai_plan_to_rows,
    save_training_plan,
)
from ..styles import inject_css

from .shell import (
    back_to_member_detail,
    back_to_member_list,
    render_page_header,
    render_sidebar,
)


logger = logging.getLogger(__name__)


def training_plans_page():
    inject_css()
    render_sidebar()

    selected_member_id = st.session_state.get("selected_member_id")
    if selected_member_id is None:
        st.warning("请先选择会员。")
        if st.button("返回会员列表"):
            back_to_member_list()
        return

    coach_id = st.session_state.coach_id
    member = get_member_by_id(coach_id, selected_member_id)
    if not member:
        st.error("会员不存在或不属于当前教练。")
        if st.button("返回会员列表"):
            back_to_member_list()
        return

    member_id, name, *_ = member

    if st.button("返回会员主页"):
        back_to_member_detail()

    render_page_header(
        eyebrow="训练计划",
        title=f"训练计划：{name}",
        subtitle="查看教练确认保存的训练内容。训练计划不会自动变成训练记录，也不会自动扣课。",
    )

    plans = get_training_plans_for_member(coach_id, member_id)
    if not plans:
        st.info("暂无训练计划。可以先使用 AI 下次训练计划生成草稿。")
        if st.button(
            "去生成下次训练计划",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.page = "ai_plan"
            st.rerun()
        return

    for plan in plans:
        (
            plan_id,
            plan_date,
            status,
            source_analysis_report_id,
            plan_goal,
            plan_coach_note,
            raw_ai_plan,
            created_at,
            updated_at,
        ) = plan
        with st.expander(f"{plan_date} 下次训练计划"):
            st.caption(f"状态：{status or 'confirmed'}")
            st.markdown(f"**计划目标：** {plan_goal or '未填写'}")
            st.markdown(f"**教练备注：** {plan_coach_note or '未填写'}")
            plan_exercises = get_training_plan_exercises(coach_id, plan_id)
            if plan_exercises:
                st.dataframe(
                    [
                        {
                            "动作": exercise[2],
                            "目标重量": exercise[3],
                            "组数": exercise[4],
                            "次数": exercise[5],
                            "RPE（主观强度）": exercise[6],
                            "备注": exercise[7],
                        }
                        for exercise in plan_exercises
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("该计划暂无动作明细。")


def ai_plan_page():
    inject_css()
    render_sidebar()

    selected_member_id = st.session_state.get("selected_member_id")
    if selected_member_id is None:
        st.warning("请先选择会员。")
        if st.button("返回会员列表"):
            back_to_member_list()
        return

    coach_id = st.session_state.coach_id
    member = get_member_by_id(coach_id, selected_member_id)
    if not member:
        st.error("会员不存在或不属于当前教练。")
        if st.button("返回会员列表"):
            back_to_member_list()
        return

    if st.session_state.get("ai_plan_member_id") != selected_member_id:
        st.session_state.current_ai_plan = {}
        st.session_state.current_ai_plan_rows = []
        st.session_state.ai_plan_extra_note = ""
        st.session_state.current_training_plan_id = None
        st.session_state.ai_plan_save_message = ""
        st.session_state.ai_plan_member_id = selected_member_id

        member_widget_markers = (
            f"ai_plan_extra_note_{selected_member_id}",
            f"ai_plan_date_{selected_member_id}",
            f"ai_plan_goal_editor_{selected_member_id}",
            f"ai_plan_coach_note_editor_{selected_member_id}",
            f"ai_plan_exercise_count_{selected_member_id}",
            f"plan_exercise_select_{selected_member_id}_",
            f"plan_target_weight_{selected_member_id}_",
            f"plan_sets_{selected_member_id}_",
            f"plan_reps_{selected_member_id}_",
            f"plan_target_rpe_{selected_member_id}_",
            f"plan_note_{selected_member_id}_",
        )
        for state_key in list(st.session_state.keys()):
            if any(str(state_key).startswith(marker) for marker in member_widget_markers):
                del st.session_state[state_key]

    (
        member_id,
        name,
        remaining_lessons,
        goal,
        last_training_date,
        ai_reminder,
        phone,
        note,
    ) = member

    if st.button("返回会员主页"):
        back_to_member_detail()

    render_page_header(
        eyebrow="AI 排课草稿",
        title=f"AI 下次训练计划：{name}",
        subtitle=(
            "基于会员档案、最近训练记录、AI 分析报告和动作库，生成下次训练计划草稿。"
            "教练确认后才会保存为正式计划。"
        ),
    )

    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    metric_col_1.metric("剩余课时", f"{remaining_lessons} 节")
    metric_col_2.metric("训练目标", goal or "未填写")
    metric_col_3.metric("最近训练", last_training_date or "暂无")

    recent_sessions = get_recent_training_context(
        coach_id, member_id, limit=5
    )
    latest_ai_report = get_latest_ai_analysis_report(coach_id, member_id)
    exercise_options = get_exercise_options()
    exercise_names = [item[1] for item in exercise_options]

    st.subheader("最近训练摘要")
    if recent_sessions:
        for session in recent_sessions:
            session_date = session.get("training_date") or "日期未填写"
            with st.expander(f"{session_date} 训练记录"):
                exercises = session.get("exercises", [])
                if exercises:
                    st.dataframe(
                        [
                            {
                                "动作": item.get("exercise_name", ""),
                                "重量": item.get("weight", ""),
                                "组数": item.get("sets", ""),
                                "次数": item.get("reps", ""),
                                "RPE（主观强度）": item.get("rpe", ""),
                                "备注": item.get("note", ""),
                            }
                            for item in exercises
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("本次训练暂无动作明细。")
                st.markdown(
                    f"**会员反馈：** {session.get('member_feedback') or '未填写'}"
                )
                st.markdown(
                    f"**教练备注：** {session.get('coach_note') or '未填写'}"
                )
    else:
        st.info("暂无训练记录，也可以先生成一份保守的基础训练计划。")

    st.subheader("最新 AI 分析摘要")
    if latest_ai_report:
        (
            latest_report_id,
            latest_report_date,
            latest_report_markdown,
            latest_report_input_summary,
            latest_report_created_at,
        ) = latest_ai_report
        with st.expander(f"{latest_report_date} AI 分析报告"):
            st.markdown(latest_report_markdown)
    else:
        st.info(
            "暂无 AI 分析报告，也可以生成基础训练计划，但建议先完成 AI 分析会更准确。"
        )

    st.subheader("教练补充要求")
    extra_note_key = f"ai_plan_extra_note_{member_id}"
    if extra_note_key not in st.session_state:
        st.session_state[extra_note_key] = st.session_state.get(
            "ai_plan_extra_note", ""
        )
    extra_note = st.text_area(
        "教练补充要求",
        placeholder=(
            "例如：下次重点练臀腿；最近膝盖有点不舒服；不想安排跑步；"
            "想做低冲击训练；本次控制强度不要太高。"
        ),
        key=extra_note_key,
        label_visibility="collapsed",
        height=110,
    )
    st.session_state.ai_plan_extra_note = extra_note

    plan_date_key = f"ai_plan_date_{member_id}"
    plan_date = st.date_input(
        "计划训练日期",
        value=date.today() + timedelta(days=1),
        key=plan_date_key,
    )

    if not exercise_options:
        st.error("动作库为空，暂时无法生成可编辑训练计划。")
        return

    if st.button(
        "生成下次训练计划",
        type="primary",
        use_container_width=True,
    ):
        try:
            prompt = build_ai_plan_prompt(
                member,
                recent_sessions,
                latest_ai_report,
                exercise_names,
                extra_note,
            )
            ai_plan = generate_ai_training_plan(
                prompt,
                member=member,
                recent_sessions=recent_sessions,
                exercise_names=exercise_names,
                extra_note=extra_note,
            )
            normalized_rows = normalize_ai_plan_to_rows(
                ai_plan, exercise_options
            )
            if not normalized_rows:
                ai_plan = generate_fallback_training_plan(
                    member, recent_sessions, exercise_names, extra_note
                )
                normalized_rows = normalize_ai_plan_to_rows(
                    ai_plan, exercise_options
                )
            if not normalized_rows:
                raise ValueError("未能生成有效动作")

            editor_markers = (
                f"ai_plan_goal_editor_{member_id}",
                f"ai_plan_coach_note_editor_{member_id}",
                f"ai_plan_exercise_count_{member_id}",
                f"plan_exercise_select_{member_id}_",
                f"plan_target_weight_{member_id}_",
                f"plan_sets_{member_id}_",
                f"plan_reps_{member_id}_",
                f"plan_target_rpe_{member_id}_",
                f"plan_note_{member_id}_",
            )
            for state_key in list(st.session_state.keys()):
                if any(
                    str(state_key).startswith(marker)
                    for marker in editor_markers
                ):
                    del st.session_state[state_key]

            st.session_state.current_ai_plan = ai_plan
            st.session_state.current_ai_plan_rows = normalized_rows
            st.session_state.current_training_plan_id = None
            st.session_state.ai_plan_save_message = (
                "训练计划草稿已生成，请检查并确认保存。"
            )
            st.session_state[f"ai_plan_goal_editor_{member_id}"] = _plan_text(
                ai_plan.get("plan_goal")
            )
            st.session_state[
                f"ai_plan_coach_note_editor_{member_id}"
            ] = _plan_text(ai_plan.get("coach_note"))
            st.session_state[
                f"ai_plan_exercise_count_{member_id}"
            ] = len(normalized_rows)
            for row_index, row in enumerate(normalized_rows):
                st.session_state[
                    f"plan_exercise_select_{member_id}_{row_index}"
                ] = row["exercise_id"]
                st.session_state[
                    f"plan_target_weight_{member_id}_{row_index}"
                ] = row["target_weight"]
                st.session_state[
                    f"plan_sets_{member_id}_{row_index}"
                ] = row["sets"]
                st.session_state[
                    f"plan_reps_{member_id}_{row_index}"
                ] = row["reps"]
                st.session_state[
                    f"plan_target_rpe_{member_id}_{row_index}"
                ] = row["target_rpe"] or "请选择"
                st.session_state[
                    f"plan_note_{member_id}_{row_index}"
                ] = row["note"]
        except Exception:
            logger.exception("AI training plan generation failed")
            st.session_state.ai_plan_save_message = ""
            st.error("生成训练计划时遇到问题，请稍后重试。已有训练记录不会受到影响。")

    plan_message = st.session_state.get("ai_plan_save_message", "")
    if plan_message == "训练计划草稿已生成，请检查并确认保存。":
        st.success(plan_message)

    current_plan = st.session_state.get("current_ai_plan") or {}
    current_rows = st.session_state.get("current_ai_plan_rows") or []
    if current_rows:
        if _plan_text(current_plan.get("coach_note")).startswith(
            "当前未配置 API Key 或 AI 调用失败"
        ):
            st.info("当前未配置可用的 API Key，或 AI 服务暂时不可用，已生成本地模拟训练计划。")

        st.subheader("训练计划草稿")
        plan_goal = st.text_input(
            "计划目标",
            key=f"ai_plan_goal_editor_{member_id}",
        )
        plan_coach_note = st.text_area(
            "教练整体备注",
            key=f"ai_plan_coach_note_editor_{member_id}",
            height=100,
        )
        exercise_count = st.number_input(
            "计划动作数量",
            min_value=1,
            max_value=10,
            step=1,
            key=f"ai_plan_exercise_count_{member_id}",
        )

        option_name_by_id = dict(exercise_options)
        exercise_ids = [item[0] for item in exercise_options]
        rpe_options = ["请选择"] + [str(value) for value in range(1, 11)]
        edited_rows = []

        for row_index in range(int(exercise_count)):
            default_row = (
                current_rows[row_index]
                if row_index < len(current_rows)
                else {
                    "exercise_id": exercise_ids[0],
                    "target_weight": "",
                    "sets": "",
                    "reps": "",
                    "target_rpe": "",
                    "note": "",
                }
            )
            select_key = f"plan_exercise_select_{member_id}_{row_index}"
            weight_key = f"plan_target_weight_{member_id}_{row_index}"
            sets_key = f"plan_sets_{member_id}_{row_index}"
            reps_key = f"plan_reps_{member_id}_{row_index}"
            rpe_key = f"plan_target_rpe_{member_id}_{row_index}"
            note_key = f"plan_note_{member_id}_{row_index}"

            if st.session_state.get(select_key) not in exercise_ids:
                st.session_state[select_key] = default_row.get(
                    "exercise_id", exercise_ids[0]
                )
            if weight_key not in st.session_state:
                st.session_state[weight_key] = default_row.get(
                    "target_weight", ""
                )
            if sets_key not in st.session_state:
                st.session_state[sets_key] = default_row.get("sets", "")
            if reps_key not in st.session_state:
                st.session_state[reps_key] = default_row.get("reps", "")
            if rpe_key not in st.session_state:
                st.session_state[rpe_key] = (
                    default_row.get("target_rpe") or "请选择"
                )
            if st.session_state[rpe_key] not in rpe_options:
                st.session_state[rpe_key] = "请选择"
            if note_key not in st.session_state:
                st.session_state[note_key] = default_row.get("note", "")

            with st.container(border=True):
                st.markdown(f"**动作 {row_index + 1}**")
                selected_exercise_id = st.selectbox(
                    "动作名称",
                    exercise_ids,
                    format_func=lambda option_id: option_name_by_id[option_id],
                    key=select_key,
                )
                row_col_1, row_col_2, row_col_3, row_col_4 = st.columns(4)
                with row_col_1:
                    target_weight = st.text_input("目标重量", key=weight_key)
                with row_col_2:
                    plan_sets = st.text_input("组数", key=sets_key)
                with row_col_3:
                    plan_reps = st.text_input("次数", key=reps_key)
                with row_col_4:
                    target_rpe = st.selectbox(
                        "RPE（主观强度）",
                        rpe_options,
                        key=rpe_key,
                    )
                exercise_note = st.text_input("备注", key=note_key)

            edited_rows.append({
                "exercise_id": selected_exercise_id,
                "exercise_name": option_name_by_id[selected_exercise_id],
                "target_weight": target_weight.strip(),
                "sets": plan_sets.strip(),
                "reps": plan_reps.strip(),
                "target_rpe": (
                    "" if target_rpe == "请选择" else target_rpe
                ),
                "note": exercise_note.strip(),
            })

        if st.button(
            "保存为下次训练计划",
            type="primary",
            use_container_width=True,
        ):
            try:
                source_report_id = (
                    latest_ai_report[0] if latest_ai_report else None
                )
                raw_ai_plan = json.dumps(
                    current_plan,
                    ensure_ascii=False,
                )
                plan_id = save_training_plan(
                    coach_id=coach_id,
                    member_id=member_id,
                    plan_date=plan_date.isoformat(),
                    plan_goal=plan_goal.strip(),
                    coach_note=plan_coach_note.strip(),
                    raw_ai_plan=raw_ai_plan,
                    exercise_rows=edited_rows,
                    source_analysis_report_id=source_report_id,
                )
                st.session_state.current_training_plan_id = plan_id
                st.session_state.ai_plan_save_message = (
                    "下次训练计划已保存成功。"
                )
            except Exception:
                logger.exception("Training plan save failed")
                st.session_state.ai_plan_save_message = ""
                st.error("训练计划保存失败，请稍后重试。训练记录和课时不会受到影响。")

    if st.session_state.get("ai_plan_save_message") == "下次训练计划已保存成功。":
        st.success("下次训练计划已保存成功。")
        action_col_1, action_col_2 = st.columns(2)
        with action_col_1:
            if st.button(
                "返回会员主页",
                key=f"ai_plan_back_{member_id}",
                use_container_width=True,
            ):
                back_to_member_detail()
        with action_col_2:
            if st.button(
                "查看训练计划",
                key=f"ai_plan_schedule_{member_id}",
                use_container_width=True,
            ):
                st.session_state.page = "training_plans"
                st.rerun()

    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)
    st.subheader("已保存的训练计划")
    saved_plans = get_training_plans_for_member(coach_id, member_id)
    if not saved_plans:
        st.info("暂无已保存训练计划。")
    else:
        for saved_plan in saved_plans:
            (
                saved_plan_id,
                saved_plan_date,
                saved_status,
                saved_source_report_id,
                saved_plan_goal,
                saved_coach_note,
                saved_raw_ai_plan,
                saved_created_at,
                saved_updated_at,
            ) = saved_plan
            with st.expander(f"{saved_plan_date} 下次训练计划"):
                st.markdown(
                    f"**计划目标：** {saved_plan_goal or '未填写'}"
                )
                st.markdown(
                    f"**教练备注：** {saved_coach_note or '未填写'}"
                )
                saved_exercises = get_training_plan_exercises(
                    coach_id, saved_plan_id
                )
                if saved_exercises:
                    st.dataframe(
                        [
                            {
                                "动作": exercise[2],
                                "目标重量": exercise[3],
                                "组数": exercise[4],
                                "次数": exercise[5],
                                "RPE（主观强度）": exercise[6],
                                "备注": exercise[7],
                            }
                            for exercise in saved_exercises
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("该计划暂无动作明细。")


# =========================
# 页面：AI 分析
# =========================
