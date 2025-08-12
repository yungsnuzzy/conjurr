import os, sqlite3, sys, json

def main(path: str):
    if not os.path.exists(path):
        print(f"ERROR: DB not found at {path}")
        return 1
    # Prefer read-only
    uri = f"file:{path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except Exception:
        conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print("TABLES:")
    for t in tables:
        print(" -", t)
    print()
    for t in tables:
        print(f"=== {t} ===")
        try:
            cur.execute(f"PRAGMA table_info('{t}')")
            cols = [r[1] for r in cur.fetchall()]
            print("cols:", cols)
            cur.execute(f"SELECT COUNT(*) FROM '{t}'")
            cnt = cur.fetchone()[0]
            print("count:", cnt)
            if cnt:
                cur.execute(f"SELECT * FROM '{t}' LIMIT 3")
                rows = cur.fetchall()
                # Preview first few rows as dicts when possible
                for i, row in enumerate(rows):
                    preview = {cols[j]: row[j] for j in range(min(len(cols), len(row)))}
                    print(f"row{i+1}:", json.dumps(preview, default=str)[:800])
        except Exception as e:
            print("error:", e)
        print()
    conn.close()
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python probe_tautulli_db.py <path_to_Tautulli.db>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
