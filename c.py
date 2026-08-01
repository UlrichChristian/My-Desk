"""
c.app — personal workspace hub.
Run:  python c.py  →  http://127.0.0.1:5002  (override with C_APP_PORT)
"""

import os
import sys
from datetime import datetime

# Make c App importable as a package root
_APP_DIR       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "c App")
_FOCUS_APP_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Focus Board")
_FIN_APP_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Financial Management App")
sys.path.insert(0, _APP_DIR)

from flask import Flask

from db.connection import close_db
from db.init_db import init_db

# Add domain apps AFTER c App modules are cached so prod_* / fin_* names resolve correctly
sys.path.insert(1, _FOCUS_APP_DIR)
sys.path.insert(2, _FIN_APP_DIR)

from focus_db.connection import close_db as close_focus_db
from focus_db.init_db import init_db as focus_init_db

from fin_db.connection import close_db as close_fin_db
from fin_db.init_db import init_db as fin_init_db


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(_APP_DIR, "templates"),
        static_folder=os.path.join(_APP_DIR, "static"),
    )
    app.secret_key = os.environ.get("C_APP_SECRET_KEY") or os.urandom(32)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    app.jinja_env.cache_size = 0

    init_db()
    focus_init_db()
    fin_init_db()

    app.teardown_appcontext(close_db)
    app.teardown_appcontext(close_focus_db)
    app.teardown_appcontext(close_fin_db)

    @app.context_processor
    def inject_globals():
        return {"now_hour": datetime.now().hour}

    from web.auth import auth_bp
    from web.hub import hub_bp
    from web.launcher import launcher_bp
    from focus_web.routes import focus_bp
    from fin_web.routes import financial_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(hub_bp)
    app.register_blueprint(launcher_bp)
    app.register_blueprint(focus_bp)
    app.register_blueprint(financial_bp)

    return app


app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    port = int(os.environ.get("C_APP_PORT") or os.environ.get("PORT") or "5002")
    print(f"My Desk running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
