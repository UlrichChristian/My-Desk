from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from db.connection import get_db
from services import users as user_accounts

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    conn = get_db()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        next_url = request.form.get("next") or ""
        user = user_accounts.authenticate(conn, username=username, password=password)
        if user is None:
            flash("Sign-in failed — check the name and password.", "error")
            return redirect(url_for("auth.login", next=next_url))
        session["username"] = user["username"]
        session["display_name"] = user["display_name"] or user["username"]
        first_name = (user["display_name"] or user["username"]).split()[0]
        flash(f"Welcome back, {first_name}.", "success")
        return redirect(next_url or url_for("hub.index"))
    accounts = user_accounts.list_users(conn)
    return render_template("login.html", accounts=accounts, next=request.args.get("next", ""))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))
