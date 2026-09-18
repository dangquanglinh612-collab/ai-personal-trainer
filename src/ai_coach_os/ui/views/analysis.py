"""Page handler module."""

from __future__ import annotations

import logging

import streamlit as st

from ...repositories.member_data import (
    get_exercise_library_names,
    get_member_by_id,
    get_recent_training_context,
)
from ...services.ai import (
    build_ai_analysis_prompt,
    generate_ai_analysis,
    get_ai_analysis_reports,
    save_ai_analysis_report,
)
from ..styles import inject_css

from .shell import (
    back_to_member_detail,
    back_to_member_list,
    render_page_header,
    render_sidebar,
)


logger = logging.getLogger(__name__)

def ai_analysis_page():
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

    if st.session_state.get("ai_analysis_member_id") != selected_member_id:
        st.session_state.current_ai_analysis = ""
        st.session_state.ai_analysis_extra_note = ""
        st.session_state.ai_analysis_save_message = ""
        st.session_state.ai_analysis_member_id = selected_member_id
        st.session_state.pop(f"ai_analysis_extra_note_{selected_member_id}", None)

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
        eyebrow="AI 助教",
        title=f"AI 分析：{name}",
        subtitle="基于会员档案、最近训练记录、会员反馈和教练备注，生成训练分析与下次训练建议。"
    )

    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    with metric_col_1:
        st.metric("剩余课时", f"{remaining_lessons} 节")
    with metric_col_2:
        st.metric("训练目标", goal or "未填写")
    with metric_col_3:
        st.metric("最近训练", last_training_date or "暂无")

    recent_sessions = get_recent_training_context(coach_id, member_id, limit=5)
    exercise_names = get_exercise_library_names()

    st.subheader("最近训练摘要")
    if not recent_sessions:
        st.info("暂无训练记录。\n\n请先完成至少一次“开始上课”并保存训练记录，AI 分析会更准确。")
    else:
        for session in recent_sessions:
            training_date_value = session.get("training_date") or "日期未填写"
            with st.expander(f"{training_date_value} 训练记录"):
                exercises = session.get("exercises", [])
                if exercises:
                    table_rows = [
                        {
                            "动作": item.get("exercise_name", ""),
                            "重量": item.get("weight", ""),
                            "组数": item.get("sets", ""),
                            "次数": item.get("reps", ""),
                            "RPE（主观强度）": item.get("rpe", ""),
                            "备注": item.get("note", ""),
                        }
                        for item in exercises
                    ]
                    st.dataframe(table_rows, use_container_width=True, hide_index=True)
                else:
                    st.caption("本次训练暂无动作明细。")

                st.markdown(f"**会员反馈：** {session.get('member_feedback') or '未填写'}")
                st.markdown(f"**教练备注：** {session.get('coach_note') or '未填写'}")
                if session.get("raw_paste_text"):
                    st.caption("原始粘贴内容")
                    st.code(session["raw_paste_text"], language=None)

    st.subheader("教练补充信息")
    note_key = f"ai_analysis_extra_note_{member_id}"
    if note_key not in st.session_state:
        st.session_state[note_key] = st.session_state.get("ai_analysis_extra_note", "")
    extra_note = st.text_area(
        "教练补充信息",
        placeholder="例如：最近睡眠差、工作压力大、膝盖有点不舒服、想重点练臀腿、不喜欢跑步。",
        key=note_key,
        label_visibility="collapsed",
        height=120,
    )
    st.session_state.ai_analysis_extra_note = extra_note

    if st.button("生成 AI 训练分析", type="primary", use_container_width=True):
        try:
            prompt = build_ai_analysis_prompt(
                member, recent_sessions, exercise_names, extra_note
            )
            report_markdown = generate_ai_analysis(
                prompt,
                member=member,
                recent_sessions=recent_sessions,
                exercise_names=exercise_names,
                extra_note=extra_note,
            )
            input_summary = (
                f"最近训练记录 {len(recent_sessions)} 节；"
                f"教练补充信息：{extra_note.strip() or '无'}"
            )
            save_ai_analysis_report(
                coach_id, member_id, report_markdown, input_summary
            )
            st.session_state.current_ai_analysis = report_markdown
            st.session_state.ai_analysis_save_message = "AI 训练分析已生成并保存。"
        except Exception:
            logger.exception("AI analysis generation or save failed")
            st.session_state.ai_analysis_save_message = ""
            st.error("生成或保存 AI 训练分析时遇到问题，请稍后重试。已有训练记录不会受到影响。")

    if st.session_state.get("ai_analysis_save_message"):
        st.success(st.session_state.ai_analysis_save_message)

    current_report = st.session_state.get("current_ai_analysis", "")
    if current_report:
        if current_report.startswith("当前未配置 API Key 或 AI 调用失败"):
            st.info("当前未配置可用的 API Key，或 AI 服务暂时不可用，已生成本地模拟分析。")
        st.subheader("AI 训练分析结果")
        with st.container(border=True):
            st.markdown(current_report)

        if st.button(
            "根据分析生成下次训练计划",
            use_container_width=True,
        ):
            st.session_state.page = "ai_plan"
            st.rerun()

    st.subheader("历史 AI 分析报告")
    reports = get_ai_analysis_reports(coach_id, member_id)
    if not reports:
        st.info("暂无历史 AI 分析报告。")
    else:
        for report_id, report_date, report_markdown, input_summary, created_at in reports:
            with st.expander(f"{report_date} AI 分析报告"):
                st.markdown(report_markdown)


# =========================
