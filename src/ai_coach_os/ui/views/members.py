"""Page handler module."""

from __future__ import annotations

import logging
from datetime import date

import streamlit as st

from ...repositories.appointments import get_next_appointment_for_member
from ...repositories.contracts import CoachContext, CoachReadRepository
from ...repositories.member_data import (
    add_member,
    add_member_lessons,
    create_body_measurement,
    get_body_measurements_for_member,
    get_latest_body_measurement,
    get_today_plan_for_member,
    update_member_contact_note,
)
from ...services.ai import (
    get_latest_training_plan,
    get_training_plan_exercises,
)
from ..helpers import (
    filter_members, format_last_training, get_member_status_line, get_status_badge,
)
from ..styles import inject_css

from .shell import (
    back_to_member_list,
    get_current_member,
    render_page_header,
    render_sidebar,
    reset_training_state,
)


logger = logging.getLogger(__name__)

def member_list_page(repository: CoachReadRepository, coach: CoachContext):
    inject_css()
    render_sidebar()

    coach_id = coach.coach_id

    render_page_header(
        eyebrow="会员目录",
        title="我的会员",
        subtitle="像通讯录一样快速找到会员。优先看到今天有课、待续课和需要关注的人。"
    )

    if st.button("打开我的课表", use_container_width=True):
        st.session_state.page = "schedule"
        st.rerun()

    with st.expander("添加会员", expanded=False):
        with st.form("add_member_form"):
            name = st.text_input("会员姓名")

            remaining_lessons = st.number_input(
                "剩余课时",
                min_value=0,
                value=10,
                step=1
            )

            goal = st.selectbox(
                "训练目标",
                ["减脂", "增肌", "改善体态"]
            )

            submitted = st.form_submit_button("添加会员", use_container_width=True)

            if submitted:
                if not name.strip():
                    st.warning("请输入会员姓名")
                else:
                    add_member(
                        coach_id=coach_id,
                        name=name.strip(),
                        remaining_lessons=remaining_lessons,
                        goal=goal
                    )
                    st.success("会员已添加")
                    st.rerun()

    keyword = st.text_input(
        "搜索会员",
        placeholder="输入姓名、目标或提醒关键词"
    )

    selected_filter = st.radio(
        "筛选",
        ["全部", "今天有课", "待续课", "AI提醒"],
        horizontal=True,
        label_visibility="collapsed"
    )

    all_members = repository.list_members(coach)
    if any(not member.today_plan_available for member in all_members):
        st.caption("当前数据源不提供今日预约摘要。")
        if selected_filter == "今天有课":
            return
    members = filter_members(all_members, keyword, selected_filter)

    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)

    if not members:
        st.info("没有符合条件的会员。")
        return

    for member in members:
        status_line = get_member_status_line(
            remaining_lessons=member.remaining_lessons,
            last_training_date=member.last_training_date,
            ai_reminder=member.ai_reminder,
            today_plan_time=member.today_plan_time
        )

        badge_text, badge_color = get_status_badge(
            remaining_lessons=member.remaining_lessons,
            ai_reminder=member.ai_reminder,
            today_plan_time=member.today_plan_time
        )

        col_info, col_action = st.columns([8, 1.4])

        with col_info:
            st.markdown(
                f"""
                <div class="member-card">
                    <div class="badge badge-{badge_color}">{badge_text}</div>
                    <div class="member-name">{member.name}</div>
                    <div class="member-status">{status_line}</div>
                    <div class="member-meta">{member.remaining_lessons}课 · {member.goal or "未填写"}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with col_action:
            st.write("")
            st.write("")
            if st.button("进入", key=f"enter_member_{member.id}", use_container_width=True):
                st.session_state.selected_member_id = member.id
                st.session_state.page = "member_detail"
                st.rerun()


# =========================
# 页面：会员主页
# =========================

def member_detail_page(repository: CoachReadRepository, coach: CoachContext):
    inject_css()
    render_sidebar()

    coach_id = coach.coach_id
    member = get_current_member(repository, coach)

    if not member:
        st.error("没有找到该会员，或该会员不属于当前教练。")
        if st.button("返回会员列表"):
            back_to_member_list()
        return

    member_id = member.id

    today_plan = get_today_plan_for_member(coach_id, member_id)

    if st.button("返回会员列表"):
        back_to_member_list()

    render_page_header("会员主页", member.name, f"训练目标：{member.goal or '未填写'}")
    st.markdown(f"**剩余课时：{member.remaining_lessons} 节**")

    if today_plan:
        plan_time, status, content = today_plan
        st.markdown(
            f"""
            <div class="notice-card">
                今天 {plan_time if plan_time else ""} 有预约课程：{content if content else "未填写课程内容"}
            </div>
            """,
            unsafe_allow_html=True
        )

    if member.ai_reminder:
        st.markdown(
            f"""
            <div class="notice-card">
                {member.ai_reminder}
            </div>
            """,
            unsafe_allow_html=True
        )

    if member.note:
        st.markdown(f"**会员备注 / 训练注意事项：** {member.note}")

    if st.button("开始上课", type="primary", use_container_width=True):
        reset_training_state(member_id)
        st.session_state.page = "start_training"
        st.rerun()

    st.caption(f"最近训练：{format_last_training(member.last_training_date)}")
    if st.button("训练历史", use_container_width=True):
        st.session_state.page = "training_history"
        st.rerun()

    next_appointment = get_next_appointment_for_member(coach_id, member_id)
    with st.container(border=True):
        st.markdown("**下次预约**")
        if next_appointment:
            st.caption(
                f"{next_appointment['appointment_date']} "
                f"{next_appointment['start_time']}—{next_appointment['end_time']}"
            )
            if st.button(
                "查看课表",
                key=f"member_next_appointment_{member_id}",
                use_container_width=True,
            ):
                st.session_state.schedule_selected_date = date.fromisoformat(
                    next_appointment["appointment_date"]
                )
                st.session_state.schedule_date_picker_version += 1
                st.session_state.page = "schedule"
                st.rerun()
        else:
            st.caption("暂未安排下次课程。")
            if st.button(
                "预约课程",
                key=f"member_create_appointment_{member_id}",
                use_container_width=True,
            ):
                st.session_state.schedule_prefill_member_id = member_id
                st.session_state.page = "schedule"
                st.rerun()

    latest_training_plan = get_latest_training_plan(coach_id, member_id)
    if latest_training_plan:
        (
            latest_plan_id,
            latest_plan_date,
            latest_plan_status,
            latest_plan_source_report_id,
            latest_plan_goal,
            latest_plan_coach_note,
            latest_plan_raw_ai,
            latest_plan_created_at,
            latest_plan_updated_at,
        ) = latest_training_plan
        latest_plan_exercises = get_training_plan_exercises(
            coach_id, latest_plan_id
        )
        with st.container(border=True):
            st.markdown(f"**下次训练计划：{latest_plan_date}**")
            if latest_plan_goal:
                st.caption(latest_plan_goal)
            for plan_exercise in latest_plan_exercises[:3]:
                (
                    plan_exercise_id,
                    exercise_library_id,
                    exercise_name,
                    target_weight,
                    plan_sets,
                    plan_reps,
                    target_rpe,
                    plan_note,
                    sort_order,
                ) = plan_exercise
                exercise_parts = [
                    exercise_name,
                    target_weight,
                    f"{plan_sets}组" if plan_sets else "",
                    f"{plan_reps}次" if plan_reps else "",
                    f"RPE {target_rpe}" if target_rpe else "",
                ]
                st.caption(" · ".join(part for part in exercise_parts if part))
            if st.button(
                "查看完整计划",
                key=f"member_latest_plan_{member_id}",
                use_container_width=True,
            ):
                st.session_state.page = "training_plans"
                st.rerun()
    else:
        st.caption("暂无下次训练计划。")

    with st.expander("AI 助教与训练计划", expanded=False):
        if st.button(
            "查看训练计划",
            key=f"member_training_plans_{member_id}",
            use_container_width=True,
        ):
            st.session_state.page = "training_plans"
            st.rerun()
        if st.button(
            "生成下次训练计划",
            key=f"member_ai_plan_{member_id}",
            use_container_width=True,
        ):
            st.session_state.page = "ai_plan"
            st.rerun()
        if st.button("AI分析", use_container_width=True):
            st.session_state.page = "ai_analysis"
            st.rerun()
        if st.button("预约课程", use_container_width=True):
            st.session_state.schedule_prefill_member_id = member_id
            st.session_state.page = "schedule"
            st.rerun()

    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)
    st.subheader("身体数据")

    measurement_saved_key = f"body_measurement_saved_{member_id}"
    if st.session_state.pop(measurement_saved_key, False):
        st.success("身体数据已保存成功。")

    latest_measurement = get_latest_body_measurement(coach_id, member_id)
    if latest_measurement:
        (
            latest_measurement_id,
            latest_record_date,
            latest_height,
            latest_weight,
            latest_body_fat,
            latest_waist,
            latest_hip,
            latest_note,
            latest_created_at,
        ) = latest_measurement
        with st.container(border=True):
            st.caption(f"最新记录 · {latest_record_date}")
            measurement_col_1, measurement_col_2, measurement_col_3 = st.columns(3)
            measurement_col_1.metric("身高", latest_height or "未填写")
            measurement_col_2.metric("体重", latest_weight or "未填写")
            measurement_col_3.metric("体脂率", latest_body_fat or "未填写")

            optional_measurements = []
            if latest_waist:
                optional_measurements.append(f"腰围：{latest_waist}")
            if latest_hip:
                optional_measurements.append(f"臀围：{latest_hip}")
            if optional_measurements:
                st.caption("　｜　".join(optional_measurements))
            if latest_note:
                st.markdown(f"**备注：** {latest_note}")
    else:
        st.info("暂无身体数据记录，可以先添加初始身高体重。")

    with st.expander("添加 / 更新身体数据", expanded=False):
        with st.form(f"body_measurement_form_{member_id}", clear_on_submit=False):
            measurement_date = st.date_input(
                "记录日期",
                value=date.today(),
                key=f"body_measurement_date_{member_id}",
            )
            measurement_col_1, measurement_col_2 = st.columns(2)
            with measurement_col_1:
                measurement_height = st.text_input(
                    "身高",
                    placeholder="例如：162cm",
                    key=f"body_measurement_height_{member_id}",
                )
                measurement_body_fat = st.text_input(
                    "体脂率（可选）",
                    placeholder="例如：25%",
                    key=f"body_measurement_body_fat_{member_id}",
                )
                measurement_hip = st.text_input(
                    "臀围（可选）",
                    placeholder="例如：95cm",
                    key=f"body_measurement_hip_{member_id}",
                )
            with measurement_col_2:
                measurement_weight = st.text_input(
                    "体重",
                    placeholder="例如：57.5kg",
                    key=f"body_measurement_weight_{member_id}",
                )
                measurement_waist = st.text_input(
                    "腰围（可选）",
                    placeholder="例如：70cm",
                    key=f"body_measurement_waist_{member_id}",
                )
            measurement_note = st.text_area(
                "备注（可选）",
                placeholder="例如：初始记录 / 减脂第 4 周 / 状态良好",
                key=f"body_measurement_note_{member_id}",
                height=90,
            )
            measurement_submitted = st.form_submit_button(
                "保存身体数据",
                use_container_width=True,
            )

            if measurement_submitted:
                try:
                    create_body_measurement(
                        coach_id=coach_id,
                        member_id=member_id,
                        record_date=measurement_date.isoformat(),
                        height=measurement_height.strip(),
                        weight=measurement_weight.strip(),
                        body_fat=measurement_body_fat.strip(),
                        waist=measurement_waist.strip(),
                        hip=measurement_hip.strip(),
                        note=measurement_note.strip(),
                    )
                    st.session_state[measurement_saved_key] = True
                    st.rerun()
                except Exception:
                    logger.exception("Body measurement save failed")
                    st.error("身体数据保存失败，请稍后重试。")

    measurement_history = get_body_measurements_for_member(coach_id, member_id)
    with st.expander("身体数据历史", expanded=False):
        if measurement_history:
            history_rows = []
            for measurement in measurement_history:
                (
                    measurement_id,
                    record_date_value,
                    height_value,
                    weight_value,
                    body_fat_value,
                    waist_value,
                    hip_value,
                    note_value,
                    created_at_value,
                ) = measurement
                history_rows.append({
                    "记录日期": record_date_value,
                    "身高": height_value,
                    "体重": weight_value,
                    "体脂率": body_fat_value,
                    "腰围": waist_value,
                    "臀围": hip_value,
                    "备注": note_value,
                })
            st.dataframe(history_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("暂无身体数据历史。")

    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)

    st.subheader("联系方式与资料")
    st.write(f"联系电话：{member.phone or '未填写'}")

    saved_flag_key = f"member_info_saved_{member_id}"

    if st.session_state.get(saved_flag_key, False):
        st.success("会员信息已保存成功！")
        st.session_state[saved_flag_key] = False

    with st.expander("编辑联系电话和会员备注", expanded=False):
        with st.form(f"edit_member_info_{member_id}"):
            new_phone = st.text_input(
                "联系电话",
                value="" if member.phone == "未填写" else (member.phone or "")
            )

            new_note = st.text_area(
                "会员备注",
                value=member.note or "",
                height=110,
                placeholder="例如：腰椎不舒服，避免高负荷硬拉；喜欢晚上训练；沟通方式偏直接。"
            )

            saved_info = st.form_submit_button("保存会员信息", use_container_width=True)

            if saved_info:
                update_member_contact_note(
                    coach_id=coach_id,
                    member_id=member_id,
                    phone=new_phone.strip(),
                    note=new_note.strip()
                )
                st.session_state[saved_flag_key] = True
                st.rerun()

    with st.expander("续课 / 课时管理", expanded=False):
        with st.form(f"renew_lessons_{member_id}"):
            add_count = st.number_input(
                "续课数量",
                min_value=1,
                max_value=200,
                value=5,
                step=1
            )

            renewed = st.form_submit_button("确认续课", use_container_width=True)

            if renewed:
                add_member_lessons(
                    coach_id=coach_id,
                    member_id=member_id,
                    added_lessons=add_count
                )
                st.success(f"已续课 {add_count} 节")
                st.rerun()



# =========================
# 页面：开始上课
# =========================
