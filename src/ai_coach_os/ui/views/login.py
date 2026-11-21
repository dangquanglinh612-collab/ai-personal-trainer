"""Page handler module."""

from __future__ import annotations

import streamlit as st

from ...auth import verify_coach
from ..styles import inject_css, inject_login_css

def login_page(authenticate=None):
    inject_css()
    inject_login_css()

    st.markdown(
        """
        <div class="login-brand-card">
            <div class="login-eyebrow">AI 私教工作台</div>
            <div class="login-title">AI Coach OS</div>
            <div class="login-desc">
                让私教更快找到会员、记录训练、沉淀数据，并获得 AI 助教支持。
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.form("login_form"):
        username = st.text_input("教练邮箱" if authenticate else "教练账号")
        password = st.text_input("密码", type="password")
        submit = st.form_submit_button("登录", use_container_width=True)

        if submit:
            if authenticate:
                try:
                    authenticate(username, password)
                except (ValueError, PermissionError) as error:
                    st.error(str(error))
                else:
                    st.rerun()
            elif verify_coach(username, password):
                st.session_state.logged_in = True
                st.session_state.coach_id = username
                st.session_state.page = "member_list"
                st.rerun()
            else:
                st.error("账号或密码错误")

    if authenticate is None:
        st.info("测试账号：wenwen / 123456，numb / 123456")


# =========================
# 页面：会员列表
# =========================
