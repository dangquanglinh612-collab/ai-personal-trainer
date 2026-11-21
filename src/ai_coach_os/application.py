"""Application composition root."""

from __future__ import annotations

import logging
from functools import partial

import streamlit as st

from .auth import init_session
from .backend import create_backend, read_backend, read_supabase_config
from .repositories.database import init_db
from .services.supabase_client import CoachNotAllowed, SupabaseSession
from .ui import pages
from .ui.views import readonly_members


logger = logging.getLogger(__name__)


def configure_page() -> None:
    st.set_page_config(page_title="AI Coach OS", layout="centered")


def main() -> None:
    configure_page()
    try:
        backend = read_backend(st.secrets)
        if backend == "supabase":
            settings, coach_ids = read_supabase_config(st.secrets)
    except ValueError as error:
        st.error(str(error))
        return
    except Exception:
        st.error("无法读取应用配置，请检查 secrets 和环境变量。")
        return

    if st.session_state.get("_app_backend") != backend:
        st.session_state.clear()
        st.session_state["_app_backend"] = backend
    if backend == "supabase":
        run_supabase(settings, coach_ids)
        return
    run_sqlite()


def run_supabase(settings, coach_ids) -> None:
    state = st.session_state
    session = SupabaseSession(settings, state, coach_ids)
    if not state.get("logged_in"):
        pages.login_page(session.login)
        return
    try:
        authenticated = session.restore()
    except (ValueError, CoachNotAllowed) as error:
        st.error(str(error))
        pages.login_page(session.login)
        return

    if st.button("退出登录"):
        session.logout()
        st.rerun()
        return
    try:
        repository, coach = create_backend("supabase", authenticated=authenticated)
    except Exception:
        st.error("无法加载 Supabase 会员工作台，请检查测试项目和账号权限。")
        return
    if state.get("page") == "member_detail":
        readonly_members.member_detail_page(repository, coach)
    else:
        readonly_members.member_list_page(repository, coach)


def run_sqlite() -> None:
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

    try:
        repository, coach = create_backend("sqlite", sqlite_coach_id=st.session_state.coach_id)
        routes = {
            "member_list": partial(pages.member_list_page, repository, coach),
            "member_detail": partial(pages.member_detail_page, repository, coach),
            "start_training": partial(pages.start_training_page, repository, coach),
            "training_history": partial(pages.training_history_page, repository, coach),
            "schedule": pages.schedule_page,
            "training_plans": partial(pages.training_plans_page, repository, coach),
            "ai_analysis": partial(pages.ai_analysis_page, repository, coach),
            "ai_plan": partial(pages.ai_plan_page, repository, coach),
        }
        page = routes.get(st.session_state.page)
        if page is None:
            st.session_state.page = "member_list"
            st.rerun()
            return
        page()
    except Exception:
        logger.exception("Page rendering failed: %s", st.session_state.page)
        st.error("页面加载失败，请重试。其他数据不会受到影响。")
