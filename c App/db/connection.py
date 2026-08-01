import os
import sqlite3

from flask import g

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "c.db")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
