"""Legacy stub.

The app now uses local SQLite via app.db.
This module is intentionally kept only to avoid import-path breakage.
"""


def get_supabase():
    raise RuntimeError("Supabase is disabled. Use app.db.get_connection() for local SQLite.")
