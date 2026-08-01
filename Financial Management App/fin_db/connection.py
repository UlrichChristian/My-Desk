import os
import sqlite3

from flask import g

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "financial.db")


def get_db() -> sqlite3.Connection:
    if "fin_db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        from fin_db.init_db import migrate_schema
        migrate_schema(conn)
        g.fin_db = conn
    return g.fin_db


def close_db(e=None):
    db = g.pop("fin_db", None)
    if db is not None:
        db.close()
