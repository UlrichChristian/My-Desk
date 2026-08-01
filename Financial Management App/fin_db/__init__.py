"""fin_db — SQLite store for the Financial Analysis section.

Mirrors the Focus Board ``focus_db`` pattern: raw sqlite3, one connection cached
per request on Flask's ``g`` (key ``fin_db``), schema via ``executescript`` with
``CREATE TABLE IF NOT EXISTS``, and idempotent introspect-and-ALTER migrations.
"""
