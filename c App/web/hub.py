from flask import Blueprint, current_app, render_template, session, url_for

from db.connection import get_db
from services.auth import login_required
from services.users import get_user_permissions

hub_bp = Blueprint("hub", __name__)


@hub_bp.route("/")
@login_required
def index():
    conn = get_db()
    perms = get_user_permissions(conn, session["username"])

    apps = []
    if "focus" in perms:
        apps.append({
            "key": "focus",
            "name": "Focus Board",
            "icon": "fa-list-check",
            "blurb": "Task tracking, time logging, and personal planning tools.",
            "href": url_for("focus.board"),
        })
    if "financial" in perms:
        fin_href = (
            url_for("financial.home")
            if "financial.home" in current_app.view_functions
            else None
        )
        apps.append({
            "key": "financial",
            "name": "Financial Management",
            "icon": "fa-chart-line",
            "blurb": "Financial reports, budgets, and QuickBooks automations.",
            "href": fin_href,
        })
    if "payroll" in perms:
        apps.append({
            "key": "payroll",
            "name": "Payroll",
            "icon": "fa-money-check-dollar",
            "blurb": "Process payroll periods, pull BambooHR reports, and export summaries.",
            "href": url_for("launcher.launch_payroll"),
        })

    return render_template("hub.html", apps=apps)
