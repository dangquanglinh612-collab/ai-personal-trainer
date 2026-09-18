"""UI-independent presentation helpers."""

from __future__ import annotations

from datetime import date, datetime

def get_member_status_line(remaining_lessons, last_training_date, ai_reminder, today_plan_time):
    if today_plan_time:
        return f"今天 {today_plan_time} 训练"

    if remaining_lessons <= 0:
        return "需要续课"

    if remaining_lessons <= 3:
        return "建议续课"

    if ai_reminder:
        if "未训练" in ai_reminder:
            return ai_reminder
        return "需要关注"

    if last_training_date:
        try:
            last_date = datetime.strptime(last_training_date, "%Y-%m-%d").date()
            days = (date.today() - last_date).days

            if days == 0:
                return "今天已训练"

            if days >= 14:
                return f"{days}天未训练"

            return f"最近训练 {days} 天前"

        except ValueError:
            pass

    return "状态正常"


def get_status_badge(remaining_lessons, ai_reminder, today_plan_time):
    if today_plan_time:
        return "今日有课", "blue"

    if remaining_lessons <= 0:
        return "需续课", "red"

    if remaining_lessons <= 3:
        return "待续课", "yellow"

    if ai_reminder:
        return "AI提醒", "purple"

    return "正常", "green"


def format_last_training(last_training_date):
    if not last_training_date:
        return "暂无"

    try:
        last_date = datetime.strptime(last_training_date, "%Y-%m-%d").date()
        days = (date.today() - last_date).days

        if days == 0:
            return "今天"
        if days == 1:
            return "昨天"
        return f"{days}天前"

    except ValueError:
        return last_training_date


def filter_members(members, keyword, selected_filter):
    keyword = keyword.strip().lower()

    filtered = []

    for member in members:
        (
            member_id,
            name,
            remaining_lessons,
            goal,
            last_training_date,
            ai_reminder,
            today_plan_time,
        ) = member

        if keyword:
            search_text = f"{name} {goal} {ai_reminder}".lower()
            if keyword not in search_text:
                continue

        if selected_filter == "今天有课" and not today_plan_time:
            continue

        if selected_filter == "待续课" and remaining_lessons > 3:
            continue

        if selected_filter == "AI提醒" and not ai_reminder:
            continue

        filtered.append(member)

    return filtered


