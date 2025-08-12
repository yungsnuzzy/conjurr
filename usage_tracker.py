import os
import sqlite3
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'usage.db')


def init_usage_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                date TEXT NOT NULL,
                model TEXT NOT NULL,
                calls INTEGER NOT NULL DEFAULT 0,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                candidates_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (date, model)
            )
            """
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _today():
    return str(datetime.date.today())


def record_usage(model: str, prompt_tokens: int | None, candidates_tokens: int | None, total_tokens: int | None):
    if not model:
        return
    init_usage_db()
    pt = int(prompt_tokens or 0)
    ct = int(candidates_tokens or 0)
    tt = int(total_tokens or (pt + ct))
    day = _today()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO usage(date, model, calls, prompt_tokens, candidates_tokens, total_tokens) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(date, model) DO UPDATE SET calls = calls + excluded.calls, "
            "prompt_tokens = prompt_tokens + excluded.prompt_tokens, candidates_tokens = candidates_tokens + excluded.candidates_tokens, "
            "total_tokens = total_tokens + excluded.total_tokens",
            (day, model, 1, pt, ct, tt),
        )
        conn.commit()
    finally:
        conn.close()


def get_usage_today(model: str):
    init_usage_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT calls, prompt_tokens, candidates_tokens, total_tokens FROM usage WHERE date = ? AND model = ?", (_today(), model))
        row = c.fetchone()
        if not row:
            return {"calls": 0, "prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}
        return {"calls": row[0], "prompt_tokens": row[1], "candidates_tokens": row[2], "total_tokens": row[3]}
    finally:
        conn.close()


def get_usage_today_all():
    init_usage_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT model, calls, prompt_tokens, candidates_tokens, total_tokens FROM usage WHERE date = ?", (_today(),))
        out = {}
        for model, calls, pt, ct, tt in c.fetchall():
            out[model] = {"calls": calls, "prompt_tokens": pt, "candidates_tokens": ct, "total_tokens": tt}
        return out
    finally:
        conn.close()
