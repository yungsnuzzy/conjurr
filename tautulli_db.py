import os
import sqlite3
from typing import List, Dict, Optional


def _connect(db_path: str) -> sqlite3.Connection:
    if not db_path or not os.path.exists(db_path):
        raise FileNotFoundError(f"Tautulli DB not found: {db_path}")
    # Use read-only mode when possible
    uri = f"file:{db_path}?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True)
    except Exception:
        # Fallback to normal connect
        return sqlite3.connect(db_path)


def _get_columns(conn: sqlite3.Connection, table: str) -> set:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info('{table}')")
    cols = {row[1] for row in cur.fetchall()}
    return cols


def db_get_users(db_path: str) -> List[Dict]:
    conn = _connect(db_path)
    cur = conn.cursor()
    cols = _get_columns(conn, 'users')
    # Common columns in Tautulli users table
    col_user_id = 'user_id' if 'user_id' in cols else 'id'
    display_cols = [c for c in ('friendly_name', 'username', 'email') if c in cols]
    is_active_col = 'is_active' if 'is_active' in cols else None
    sel_cols = [col_user_id] + display_cols + ([is_active_col] if is_active_col else [])
    cur.execute(f"SELECT {', '.join(sel_cols)} FROM users")
    users = []
    for row in cur.fetchall():
        rec = {}
        idx = 0
        rec['user_id'] = row[idx]; idx += 1
        # Map out any available display columns to explicit fields
        collected = {}
        for c in display_cols:
            collected[c] = row[idx]
            idx += 1
        # Preserve explicit fields when present
        if 'username' in collected:
            rec['username'] = collected.get('username')
        if 'email' in collected:
            rec['email'] = collected.get('email')
        # Compute a friendly display name, preferring friendly_name -> username -> email -> user_id
        friendly = None
        for key in ('friendly_name', 'username', 'email'):
            if key in collected and collected.get(key):
                friendly = collected.get(key)
                break
        rec['friendly_name'] = friendly or str(rec['user_id'])
        if is_active_col:
            rec['is_active'] = bool(row[idx])
        else:
            rec['is_active'] = True
        users.append(rec)
    conn.close()
    # Return only active users if that flag exists
    return [u for u in users if u.get('is_active', True)]


def _select_history(conn: sqlite3.Connection, user_id: str, after: Optional[int] = None, limit: Optional[int] = None):
    sh_cols = _get_columns(conn, 'session_history')
    sm_cols = _get_columns(conn, 'session_history_metadata')
    # Required columns
    if 'user_id' not in sh_cols or 'media_type' not in sh_cols:
        return []

    # Build selectable fields
    title_expr = 'sm.title' if 'title' in sm_cols else 'NULL'
    gp_expr = None
    for c in ('grandparent_title', 'series_name', 'show_title', 'parent_title'):
        if c in sm_cols:
            gp_expr = f"sm.{c}"
            break
    # Determine best available date
    date_expr = None
    if 'last_viewed_at' in sm_cols:
        date_expr = 'sm.last_viewed_at'
    elif 'stopped' in sh_cols:
        date_expr = 'sh.stopped'
    elif 'started' in sh_cols:
        date_expr = 'sh.started'
    else:
        date_expr = 'NULL'

    select_fields = [
        'sh.media_type as media_type',
        f'{title_expr} as title',
        (f'{gp_expr} as grandparent_title' if gp_expr else 'NULL as grandparent_title'),
        f'{date_expr} as dt'
    ]
    sql = (
        f"SELECT {', '.join(select_fields)} "
        "FROM session_history sh "
        "LEFT JOIN session_history_metadata sm ON sm.rating_key = sh.rating_key "
        "WHERE sh.user_id = ? "
        f"ORDER BY {date_expr} DESC"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    cur = conn.cursor()
    cur.execute(sql, [user_id])
    rows = cur.fetchall()
    out = []
    for media_type, title, grandparent_title, dt in rows:
        rec = {
            'media_type': media_type,
            'title': title,
            'grandparent_title': grandparent_title,
        }
        # Normalize dt to float when possible
        try:
            rec['date'] = float(dt) if dt is not None else None
        except Exception:
            rec['date'] = dt
        # Apply 'after' filter here if provided
        if after is not None:
            try:
                if rec['date'] is None or float(rec['date']) < float(after):
                    continue
            except Exception:
                # If unparseable, skip filter
                pass
        out.append(rec)
    return out


def db_get_user_watch_history(db_path: str, user_id: str, after: Optional[int] = None, limit: Optional[int] = 1000):
    conn = _connect(db_path)
    try:
        return _select_history(conn, user_id, after=after, limit=limit)
    finally:
        conn.close()


def db_get_user_watch_history_all(db_path: str, user_id: str):
    conn = _connect(db_path)
    try:
        return _select_history(conn, user_id, after=None, limit=None)
    finally:
        conn.close()


def db_get_all_library_titles(db_path: str, media_type: str) -> List[str]:
    """Best-effort extraction of full library item titles for a media type from the Tautulli DB.

    Tautulli's schema can vary a bit by version. We attempt several strategies:
      1. If table 'library_media_info' exists, use it (preferred) filtering by a type column.
      2. Fallback: If only watched metadata exists (session_history_metadata), we return the
         union of watched titles (this is incomplete for availability, but better than empty).
    Returns a sorted, de-duplicated list. May be partial if fallback path used.
    """
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        titles = set()
        partial = False
        if 'library_media_info' in tables:
            cols = _get_columns(conn, 'library_media_info')
            # Determine type column
            type_col = None
            for cand in ('section_type', 'media_type'):
                if cand in cols:
                    type_col = cand
                    break
            if 'title' in cols:
                if type_col:
                    try:
                        cur.execute(f"SELECT DISTINCT title FROM library_media_info WHERE {type_col}=?", (media_type,))
                    except Exception:
                        cur.execute("SELECT DISTINCT title FROM library_media_info")
                else:
                    cur.execute("SELECT DISTINCT title FROM library_media_info")
                for (t,) in cur.fetchall():
                    if t:
                        titles.add(t)
        # Fallback: use watched metadata (incomplete)
        if not titles and 'session_history_metadata' in tables:
            partial = True
            sh_cols = _get_columns(conn, 'session_history_metadata')
            if 'title' in sh_cols or 'grandparent_title' in sh_cols:
                q_parts = []
                if media_type == 'movie' and 'title' in sh_cols:
                    q_parts.append('title')
                if media_type == 'show':
                    # For shows, grandparent_title often carries series name
                    if 'grandparent_title' in sh_cols:
                        q_parts.append('grandparent_title')
                    elif 'series_name' in sh_cols:
                        q_parts.append('series_name')
                if q_parts:
                    # Build SELECT DISTINCT over first available column
                    col = q_parts[0]
                    try:
                        cur.execute(f"SELECT DISTINCT {col} FROM session_history_metadata")
                        for (t,) in cur.fetchall():
                            if t:
                                titles.add(t)
                    except Exception:
                        pass
        # Attach partial flag in global for caller (cannot import flask.g here cleanly)
        # Caller will interpret via length/flag; we just return titles.
        out = sorted(titles)
        # Encode partial marker by appending a sentinel if needed (caller can strip)
        if partial:
            try:
                out.append('__PARTIAL__')  # sentinel; caller will remove from display
            except Exception:
                pass
        return out
    finally:
        conn.close()
