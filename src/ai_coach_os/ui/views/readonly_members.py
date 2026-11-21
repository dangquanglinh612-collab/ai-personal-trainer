"""Read-only member views for the Supabase workspace."""

import streamlit as st

from ...repositories.contracts import CoachContext, CoachReadRepository
from ..styles import inject_css
from .shell import back_to_member_list, get_current_member, render_page_header


def _open_member(member_id: int) -> None:
    st.session_state.selected_member_id = member_id
    st.session_state.page = "member_detail"


def member_list_page(repository: CoachReadRepository, coach: CoachContext) -> None:
    inject_css()
    render_page_header("会员目录", "我的会员", "选择会员，查看只读详情。")
    try:
        with st.spinner("正在加载会员目录…"):
            members = repository.list_members(coach)
    except Exception:
        st.error("无法加载会员目录，请检查网络连接后重试。")
        return

    if not members:
        st.info("暂无会员。")
        return
    for member in members:
        with st.container(border=True):
            st.text(member.name)
            st.text(f"剩余课时：{member.remaining_lessons} 节")
            st.button("查看详情", key=f"readonly_member_{member.id}",
                      on_click=_open_member, args=(member.id,))


def member_detail_page(repository: CoachReadRepository, coach: CoachContext) -> None:
    inject_css()
    render_page_header("会员目录", "会员详情", "当前页面仅供查看。")
    if st.button("返回会员列表"):
        back_to_member_list()
        return
    try:
        with st.spinner("正在加载会员详情…"):
            member = get_current_member(repository, coach)
    except ValueError:
        st.warning("会员编号无效，请返回会员列表重新选择。")
        return
    except Exception:
        st.error("无法加载会员详情，请检查网络连接后重试。")
        return
    if member is None:
        st.info("未找到会员，或当前账号无权查看。")
        return

    with st.container(border=True):
        for label, value in (
            ("会员姓名", member.name),
            ("头像标识", member.avatar_emoji),
            ("入会时间", member.created_at),
            ("剩余课时", member.remaining_lessons),
            ("训练目标", member.goal),
            ("最近训练日期", member.last_training_date),
            ("AI 提醒", member.ai_reminder),
            ("联系电话", member.phone),
            ("备注", member.note),
        ):
            st.markdown(f"**{label}**")
            st.text("未填写" if value is None or value == "" else str(value))
