"""Session and coach authentication operations."""

from datetime import date

import streamlit as st

from .repositories.database import get_conn


USER_SESSION_STATE_KEYS = {
    "logged_in",
    "coach_id",
    "page",
    "selected_member_id",
    "current_training_session_id",
    "current_training_rows",
    "training_save_message",
    "training_save_status",
    "training_photo_warning",
    "training_state_owner",
    "current_ai_analysis",
    "ai_analysis_member_id",
    "ai_analysis_extra_note",
    "ai_analysis_save_message",
    "current_ai_plan",
    "current_ai_plan_rows",
    "ai_plan_member_id",
    "ai_plan_extra_note",
    "current_training_plan_id",
    "ai_plan_save_message",
    "schedule_selected_date",
    "schedule_prefill_member_id",
    "editing_appointment_id",
    "active_appointment_id",
    "appointment_save_message",
    "appointment_create_form_version",
    "schedule_date_picker_version",
}

USER_SESSION_STATE_PREFIXES = (
    "training_",
    "ai_analysis_",
    "ai_plan_",
    "body_measurement_",
    "appointment_",
    "schedule_",
)


def verify_coach(username, password):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
        SELECT username FROM coaches
        WHERE username = ? AND password = ?
        """, (username, password))
        return c.fetchone() is not None
    finally:
        conn.close()


def init_session():
    defaults = {
        "logged_in": False,
        "coach_id": None,
        "page": "member_list",
        "selected_member_id": None,
        "current_ai_analysis": "",
        "ai_analysis_member_id": None,
        "ai_analysis_extra_note": "",
        "ai_analysis_save_message": "",
        "current_ai_plan": {},
        "current_ai_plan_rows": [],
        "ai_plan_member_id": None,
        "ai_plan_extra_note": "",
        "current_training_plan_id": None,
        "ai_plan_save_message": "",
        "schedule_selected_date": date.today(),
        "schedule_prefill_member_id": None,
        "editing_appointment_id": None,
        "active_appointment_id": None,
        "appointment_save_message": "",
        "appointment_create_form_version": 0,
        "schedule_date_picker_version": 0,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_user_session_state(session_state=None):
    state = st.session_state if session_state is None else session_state
    for key in list(state.keys()):
        key_text = str(key)
        if (
            key_text in USER_SESSION_STATE_KEYS
            or key_text.startswith(USER_SESSION_STATE_PREFIXES)
        ):
            del state[key]


def logout():
    clear_user_session_state()
    st.session_state.logged_in = False
    st.session_state.coach_id = None
    st.session_state.page = "member_list"
    st.session_state.selected_member_id = None
    st.rerun()


