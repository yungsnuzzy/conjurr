"""
recommendation_store.py
-----------------------
SQLite-backed cache for daily pre-generated recommendations.

Tables
------
cached_recommendations  – One row per user; holds the full JSON result blob.
recommendation_titles   – Individual titles for cross-run deduplication.

Cleanup removes rows older than 7 days automatically on every write.
"""

import os
import sys
import json
import sqlite3
import datetime


# ---------------------------------------------------------------------------
# Path helpers (mirrors usage_tracker.py logic)
# ---------------------------------------------------------------------------

def _get_data_directory() -> str:
    try:
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            data_dir = os.path.join(exe_dir, 'data')
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(script_dir, 'data')
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    except Exception:
        fallback = os.path.join(os.getcwd(), 'data')
        os.makedirs(fallback, exist_ok=True)
        return fallback


DB_PATH = os.path.join(_get_data_directory(), 'recommendations.db')


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS cached_recommendations (
                user_id   TEXT PRIMARY KEY,
                result    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS recommendation_titles (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT    NOT NULL,
                media_type TEXT    NOT NULL,
                title      TEXT    NOT NULL,
                tmdb_id    INTEGER,
                created_at TEXT    NOT NULL,
                UNIQUE(user_id, media_type, title)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_state (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


# Ensure tables exist on import
init_db()


# ---------------------------------------------------------------------------
# Cleanup  (>7 days)
# ---------------------------------------------------------------------------

def cleanup_old(days: int = 7):
    """Delete cached data older than *days* days."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM cached_recommendations WHERE created_at < ?", (cutoff,))
        c.execute("DELETE FROM recommendation_titles WHERE created_at < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Store / retrieve full recommendation blobs
# ---------------------------------------------------------------------------

def store_recommendations(user_id: str, result: dict):
    """Persist the full recommendation result dict for *user_id*.

    Also records individual titles in `recommendation_titles` for
    deduplication across runs.  Duplicate titles (same user + media_type +
    title) are silently ignored (INSERT OR IGNORE).
    """
    now = datetime.datetime.utcnow().isoformat()
    blob = json.dumps(result, default=str)

    conn = _get_conn()
    try:
        c = conn.cursor()
        # Upsert the full blob
        c.execute(
            "INSERT INTO cached_recommendations (user_id, result, created_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET result = excluded.result, created_at = excluded.created_at",
            (str(user_id), blob, now),
        )

        # Record individual titles for dedup
        for media_type, key in [('show', 'ai_shows'), ('movie', 'ai_movies')]:
            items = result.get(key, [])
            for it in items:
                title = it.get('title') if isinstance(it, dict) else it
                tmdb_id = it.get('tmdb_id') if isinstance(it, dict) else None
                if not title:
                    continue
                c.execute(
                    "INSERT OR IGNORE INTO recommendation_titles "
                    "(user_id, media_type, title, tmdb_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(user_id), media_type, title, tmdb_id, now),
                )
        conn.commit()
    finally:
        conn.close()

    # Opportunistic cleanup
    try:
        cleanup_old()
    except Exception:
        pass


def get_cached_recommendations(user_id: str) -> dict | None:
    """Return the cached recommendation dict for *user_id*, or None."""
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT result, created_at FROM cached_recommendations WHERE user_id = ? AND created_at >= ?",
            (str(user_id), (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()),
        )
        row = c.fetchone()
        if not row:
            return None
        result = json.loads(row[0])
        debug = result.get('debug') or {}
        if debug.get('ai_error') or debug.get('error') or not (result.get('ai_shows') or result.get('ai_movies')):
            return None
        result['_cached'] = True
        result['_cached_at'] = row[1]
        return result
    except Exception:
        return None
    finally:
        conn.close()


def get_previously_recommended_titles(user_id: str, media_type: str) -> set[str]:
    """Return set of title strings previously recommended in the last 7 days."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT title FROM recommendation_titles "
            "WHERE user_id = ? AND media_type = ? AND created_at >= ?",
            (str(user_id), media_type, cutoff),
        )
        return {row[0] for row in c.fetchall()}
    except Exception:
        return set()
    finally:
        conn.close()


def get_all_cached_users() -> list[str]:
    """Return list of user_ids that have cached recommendations."""
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id FROM cached_recommendations")
        return [row[0] for row in c.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def delete_cached_recommendations(user_id: str):
    """Remove cached data for a specific user."""
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM cached_recommendations WHERE user_id = ?", (str(user_id),))
        conn.commit()
    finally:
        conn.close()


def delete_all_cached():
    """Wipe all cached recommendations."""
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM cached_recommendations")
        c.execute("DELETE FROM recommendation_titles")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scheduler state helpers (persisted in DB so it survives restarts)
# ---------------------------------------------------------------------------

def set_scheduler_state(key: str, value: str):
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO scheduler_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_scheduler_state(key: str) -> str | None:
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT value FROM scheduler_state WHERE key = ?", (key,))
        row = c.fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()
