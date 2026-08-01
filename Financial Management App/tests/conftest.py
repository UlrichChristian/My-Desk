"""Shared fixtures for Financial Management App unit tests.

Uses an in-memory SQLite DB with the real schema so tests never touch
``financial.db``.
"""

from __future__ import annotations

import sqlite3

import pytest

from fin_db.init_db import migrate_schema


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    yield connection
    connection.close()
