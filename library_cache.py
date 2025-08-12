import sqlite3
import os
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'library.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS library_cache (
        media_type TEXT,
        date TEXT,
        items TEXT
    )''')
    conn.commit()
    conn.close()

def save_library_items(media_type, items):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = str(datetime.date.today())
    c.execute('DELETE FROM library_cache WHERE media_type=?', (media_type,))
    c.execute('INSERT INTO library_cache (media_type, date, items) VALUES (?, ?, ?)',
              (media_type, today, '\n'.join(items)))
    conn.commit()
    conn.close()

def load_library_items(media_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = str(datetime.date.today())
    c.execute('SELECT items, date FROM library_cache WHERE media_type=?', (media_type,))
    row = c.fetchone()
    conn.close()
    if row and row[1] == today:
        return row[0].split('\n')
    return None

def last_cache_date(media_type):
    init_db()  # Ensure table exists
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT date FROM library_cache WHERE media_type=?', (media_type,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None
