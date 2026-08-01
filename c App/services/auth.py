"""Session helpers and route decorators."""

from functools import wraps

from flask import redirect, request, session, url_for


def session_username() -> str | None:
    return session.get("username")


def is_authenticated() -> bool:
    return bool(session_username())


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for("auth.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper
