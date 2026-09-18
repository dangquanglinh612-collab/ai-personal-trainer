"""Application composition root."""

from __future__ import annotations

import logging
import os

import streamlit as st

from .auth import init_session
from .repositories.database import init_db
from .ui import pages


logger = logging.getLogger(__name__)


def configure_page() -> None:
    st.set_page_config(page_title="AI Coach OS", layout="centered")


def main() -> None:
    configure_page()
    try:
        backend = st.secrets.get("APP_DATA_BACKEND", os.getenv("APP_DATA_BACKEND", "sqlite"))
    except Exception:
        backend = os.getenv("APP_DATA_BACKEND", "sqlite")
    if backend != "sqlite":
        st.error("TASK 10 阶段 A 尚未切换业务后端。请保持 APP_DATA_BACKEND=sqlite；阶段 D 验收后才能启用 Supabase。")
        return
    try:
        init_db()
        init_session()
    except Exception:
        logger.exception("Application initialization failed")
        st.error("系统初始化失败，请稍后重试或联系管理员。")
        return

    if not st.session_state.logged_in:
        try:
            pages.login_page()
        except Exception:
            logger.exception("Login page rendering failed")
            st.error("登录页面加载失败，请重试。")
        return

    routes = {
        "member_list": pages.member_list_page,
        "member_detail": pages.member_detail_page,
        "start_training": pages.start_training_page,
        "training_history": pages.training_history_page,
        "schedule": pages.schedule_page,
        "training_plans": pages.training_plans_page,
        "ai_analysis": pages.ai_analysis_page,
        "ai_plan": pages.ai_plan_page,
    }
    page = routes.get(st.session_state.page)
    if page is None:
        st.session_state.page = "member_list"
        st.rerun()
        return
    try:
        page()
    except Exception:
        logger.exception("Page rendering failed: %s", st.session_state.page)
        st.error("页面加载失败，请重试。其他数据不会受到影响。")
