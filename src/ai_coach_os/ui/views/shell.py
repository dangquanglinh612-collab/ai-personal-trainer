"""Shared navigation and page-state helpers."""

from __future__ import annotations

import streamlit as st

from ...auth import logout
from ...repositories.contracts import CoachContext, CoachReadRepository, MemberDetail
from ..training_draft import clear_training_parse_state

def render_page_header(eyebrow, title, subtitle):
    st.markdown(
        f"""
        <div class="page-header">
            <div class="page-eyebrow">{eyebrow}</div>
            <div class="page-title">{title}</div>
            <div class="page-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_sidebar():
    st.sidebar.markdown("### AI Coach OS")
    st.sidebar.success(f"当前教练：{st.session_state.coach_id}")

    if st.sidebar.button(
        "我的课表",
        key="sidebar_schedule",
        use_container_width=True,
    ):
        st.session_state.page = "schedule"
        st.rerun()

    if st.sidebar.button(
        "会员目录",
        key="sidebar_members",
        use_container_width=True,
    ):
        st.session_state.page = "member_list"
        st.session_state.selected_member_id = None
        st.rerun()

    st.sidebar.markdown("---")

    if st.sidebar.button("退出登录", use_container_width=True):
        logout()


def back_to_member_list():
    st.session_state.page = "member_list"
    st.session_state.selected_member_id = None
    st.rerun()


def back_to_member_detail():
    st.session_state.page = "member_detail"
    st.rerun()


def get_current_member(
    repository: CoachReadRepository, coach: CoachContext
) -> MemberDetail | None:
    member_id = st.session_state.get("selected_member_id")
    if member_id is None:
        return None
    return repository.get_member(coach, member_id)


def reset_training_state(member_id):
    clear_training_parse_state(st.session_state)
    for key in (
        "current_training_session_id", "current_training_rows",
        "training_save_message", "training_save_status", "training_photo_warning",
        "training_state_owner", "active_appointment_id",
    ):
        st.session_state.pop(key, None)

    prefix = f"training_{member_id}_"
    for key in list(st.session_state.keys()):
        if str(key).startswith(prefix):
            del st.session_state[key]


# =========================
# 页面：登录
# =========================
