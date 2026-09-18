"""Public page-handler exports.

Individual page bodies live in ``ui.views`` so each workflow can evolve
independently while the application retains one routing import.
"""

from .views.analysis import ai_analysis_page
from .views.login import login_page
from .views.members import member_detail_page, member_list_page
from .views.plans import ai_plan_page, training_plans_page
from .views.schedule import schedule_page
from .views.training import start_training_page, training_history_page
from .views.shell import (
    back_to_member_detail,
    back_to_member_list,
    get_current_member,
    render_page_header,
    render_sidebar,
    reset_training_state,
)

__all__ = [
    "ai_analysis_page",
    "ai_plan_page",
    "login_page",
    "member_detail_page",
    "member_list_page",
    "schedule_page",
    "start_training_page",
    "training_history_page",
    "training_plans_page",
]
