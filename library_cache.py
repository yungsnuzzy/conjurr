import sqlite3
import os
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'library.db')

# DEPRECATED: Stub implementations (no file IO).
def init_db():
    return None

def save_library_items(media_type, items):
    return None

def load_library_items(media_type):
    return None

def last_cache_date(media_type):
    return None
