"""Coach-level daily appointment schedule page."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import streamlit as st

from ...repositories.appointments import (
    create_appointment,
    get_appointment_by_id,
    get_appointments_for_date,
    get_member_options_for_coach,
    update_appointment,
    update_appointment_status,
)
from ..styles import inject_css
from .shell import render_page_header, render_sidebar, reset_training_state


STATUS_LABELS = {
    "scheduled": "已预约",
    "completed": "已完成",
    "cancelled": "已取消",
}

logger = logging.getLogger(__name__)


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return date.today()


def _as_time(value) -> time:
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        return time(18, 0)


def _conflict_message(conflict) -> str:
    appointment = (conflict or {}).get("appointment") or {}
    return (
        "预约时间冲突："
        f"{appointment.get('member_name') or '其他会员'}已有课程 "
        f"{appointment.get('start_time') or '--:--'}—"
        f"{appointment.get('end_time') or '--:--'}，请调整时间。"
    )


def schedule_page():
    inject_css()
    render_sidebar()

    coach_id = st.session_state.coach_id
    selected_date = _as_date(
        st.session_state.get("schedule_selected_date", date.today())
    )
    st.session_state.schedule_selected_date = selected_date

    render_page_header(
        eyebrow="预约课表",
        title="我的课表",
        subtitle="按日期和时间查看、创建及管理会员预约。",
    )

    previous_col, today_col, next_col = st.columns(3)
    with previous_col:
        if st.button("上一天", use_container_width=True):
            st.session_state.schedule_selected_date = selected_date - timedelta(days=1)
            st.session_state.schedule_date_picker_version += 1
            st.rerun()
    with today_col:
        if st.button("今天", use_container_width=True):
            st.session_state.schedule_selected_date = date.today()
            st.session_state.schedule_date_picker_version += 1
            st.rerun()
    with next_col:
        if st.button("下一天", use_container_width=True):
            st.session_state.schedule_selected_date = selected_date + timedelta(days=1)
            st.session_state.schedule_date_picker_version += 1
            st.rerun()

    picker_version = st.session_state.get("schedule_date_picker_version", 0)
    picked_date = st.date_input(
        "选择日期",
        value=selected_date,
        key=f"schedule_date_picker_{picker_version}",
    )
    if picked_date != selected_date:
        selected_date = picked_date
        st.session_state.schedule_selected_date = picked_date

    save_message = st.session_state.pop("appointment_save_message", "")
    if save_message:
        st.success(save_message)

    member_options = get_member_options_for_coach(coach_id)
    member_name_by_id = {
        member_id: name
        for member_id, name, training_goal, remaining_lessons in member_options
    }
    member_ids = [member[0] for member in member_options]

    with st.expander("新建预约", expanded=False):
        if not member_options:
            st.info("当前教练名下暂无会员，请先添加会员。")
        else:
            form_version = st.session_state.get(
                "appointment_create_form_version", 0
            )
            member_key = f"appointment_create_member_{form_version}"
            date_key = f"appointment_create_date_{form_version}"
            prefill_member_id = st.session_state.get(
                "schedule_prefill_member_id"
            )
            if member_key not in st.session_state:
                st.session_state[member_key] = (
                    prefill_member_id
                    if prefill_member_id in member_ids
                    else member_ids[0]
                )
                st.session_state.schedule_prefill_member_id = None

            with st.form(f"create_appointment_form_{form_version}"):
                create_member_id = st.selectbox(
                    "选择会员",
                    member_ids,
                    format_func=lambda option_id: member_name_by_id[option_id],
                    key=member_key,
                )
                create_date = st.date_input(
                    "预约日期",
                    value=selected_date,
                    key=date_key,
                )
                time_col_1, time_col_2 = st.columns(2)
                with time_col_1:
                    create_start = st.time_input(
                        "开始时间",
                        value=time(18, 0),
                        key=f"appointment_create_start_{form_version}",
                    )
                with time_col_2:
                    create_end = st.time_input(
                        "结束时间",
                        value=time(19, 0),
                        key=f"appointment_create_end_{form_version}",
                    )
                create_note = st.text_area(
                    "备注",
                    key=f"appointment_create_note_{form_version}",
                    height=80,
                )
                create_submitted = st.form_submit_button(
                    "创建预约",
                    type="primary",
                    use_container_width=True,
                )

            if create_submitted:
                try:
                    result = create_appointment(
                        coach_id,
                        create_member_id,
                        create_date.isoformat(),
                        create_start.strftime("%H:%M"),
                        create_end.strftime("%H:%M"),
                        create_note,
                    )
                    if isinstance(result, dict) and result.get("has_conflict"):
                        st.error(_conflict_message(result))
                    else:
                        st.session_state.schedule_selected_date = create_date
                        st.session_state.schedule_date_picker_version += 1
                        st.session_state.appointment_create_form_version += 1
                        st.session_state.appointment_save_message = "预约创建成功。"
                        st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
                except Exception:
                    logger.exception("Appointment creation failed")
                    st.error("预约创建失败，请稍后重试。")

    editing_appointment_id = st.session_state.get("editing_appointment_id")
    if editing_appointment_id is not None:
        editing = get_appointment_by_id(coach_id, editing_appointment_id)
        if not editing:
            st.session_state.editing_appointment_id = None
            st.warning("预约不存在或不属于当前教练。")
        elif member_options:
            st.subheader("编辑 / 改期")
            with st.form(f"edit_appointment_{editing_appointment_id}"):
                edit_member_id = st.selectbox(
                    "会员",
                    member_ids,
                    index=member_ids.index(editing["member_id"]),
                    format_func=lambda option_id: member_name_by_id[option_id],
                    key=f"appointment_edit_member_{editing_appointment_id}",
                )
                edit_date = st.date_input(
                    "预约日期",
                    value=date.fromisoformat(editing["appointment_date"]),
                    key=f"appointment_edit_date_{editing_appointment_id}",
                )
                edit_time_col_1, edit_time_col_2 = st.columns(2)
                with edit_time_col_1:
                    edit_start = st.time_input(
                        "开始时间",
                        value=_as_time(editing["start_time"]),
                        key=f"appointment_edit_start_{editing_appointment_id}",
                    )
                with edit_time_col_2:
                    edit_end = st.time_input(
                        "结束时间",
                        value=_as_time(editing["end_time"]),
                        key=f"appointment_edit_end_{editing_appointment_id}",
                    )
                edit_note = st.text_area(
                    "备注",
                    value=editing.get("note") or "",
                    key=f"appointment_edit_note_{editing_appointment_id}",
                    height=80,
                )
                edit_action_col_1, edit_action_col_2 = st.columns(2)
                with edit_action_col_1:
                    edit_submitted = st.form_submit_button(
                        "保存修改",
                        type="primary",
                        use_container_width=True,
                    )
                with edit_action_col_2:
                    edit_cancelled = st.form_submit_button(
                        "取消编辑",
                        use_container_width=True,
                    )

            if edit_cancelled:
                st.session_state.editing_appointment_id = None
                st.rerun()
            if edit_submitted:
                try:
                    result = update_appointment(
                        coach_id,
                        editing_appointment_id,
                        edit_member_id,
                        edit_date.isoformat(),
                        edit_start.strftime("%H:%M"),
                        edit_end.strftime("%H:%M"),
                        edit_note,
                    )
                    if isinstance(result, dict) and result.get("has_conflict"):
                        st.error(_conflict_message(result))
                    else:
                        st.session_state.schedule_selected_date = edit_date
                        st.session_state.schedule_date_picker_version += 1
                        st.session_state.editing_appointment_id = None
                        st.session_state.appointment_save_message = "预约修改成功。"
                        st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
                except Exception:
                    logger.exception("Appointment update failed")
                    st.error("预约修改失败，请稍后重试。")

    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)
    st.subheader(f"{selected_date.isoformat()} 课程安排")
    appointments = get_appointments_for_date(coach_id, selected_date)
    if not appointments:
        st.info("当天暂无预约课程。")
        return

    for appointment in appointments:
        appointment_id = appointment["id"]
        status = appointment["status"]
        with st.container(border=True):
            if status == "cancelled":
                st.caption("已取消预约（记录已保留）")
                st.markdown(
                    f"**{appointment['start_time']}—{appointment['end_time']} · "
                    f"{appointment['member_name']}**"
                )
            else:
                st.markdown(
                    f"### {appointment['start_time']}—{appointment['end_time']}"
                )
                st.markdown(f"**{appointment['member_name']}**")
            st.caption(
                f"训练目标：{appointment['training_goal'] or '未填写'}　｜　"
                f"剩余课时：{appointment['remaining_lessons']} 节　｜　"
                f"状态：{STATUS_LABELS.get(status, status)}"
            )
            if appointment.get("note"):
                st.markdown(f"**备注：** {appointment['note']}")
            if appointment.get("training_plan_id"):
                st.caption(
                    f"已绑定训练计划 #{appointment['training_plan_id']}"
                )

            action_col_1, action_col_2 = st.columns(2)
            with action_col_1:
                if st.button(
                    "查看会员",
                    key=f"appointment_member_{appointment_id}",
                    use_container_width=True,
                ):
                    st.session_state.selected_member_id = appointment["member_id"]
                    st.session_state.page = "member_detail"
                    st.rerun()
            with action_col_2:
                if st.button(
                    "编辑 / 改期",
                    key=f"appointment_edit_{appointment_id}",
                    use_container_width=True,
                ):
                    st.session_state.editing_appointment_id = appointment_id
                    st.rerun()

            if status == "scheduled":
                scheduled_col_1, scheduled_col_2, scheduled_col_3 = st.columns(3)
                with scheduled_col_1:
                    if st.button(
                        "开始上课",
                        key=f"appointment_start_{appointment_id}",
                        type="primary",
                        use_container_width=True,
                    ):
                        reset_training_state(appointment["member_id"])
                        st.session_state.selected_member_id = appointment["member_id"]
                        st.session_state.active_appointment_id = appointment_id
                        st.session_state.page = "start_training"
                        st.rerun()
                with scheduled_col_2:
                    if st.button(
                        "标记完成",
                        key=f"appointment_complete_{appointment_id}",
                        use_container_width=True,
                    ):
                        try:
                            update_appointment_status(
                                coach_id, appointment_id, "completed"
                            )
                            st.session_state.appointment_save_message = "预约已标记完成。"
                            st.rerun()
                        except Exception:
                            logger.exception("Appointment completion failed")
                            st.error("预约状态更新失败，请重试。")
                with scheduled_col_3:
                    if st.button(
                        "取消预约",
                        key=f"appointment_cancel_{appointment_id}",
                        use_container_width=True,
                    ):
                        try:
                            update_appointment_status(
                                coach_id, appointment_id, "cancelled"
                            )
                            st.session_state.appointment_save_message = "预约已取消。"
                            st.rerun()
                        except Exception:
                            logger.exception("Appointment cancellation failed")
                            st.error("预约状态更新失败，请重试。")
