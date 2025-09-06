from rapidfuzz import fuzz, process
from flask import Flask, jsonify, render_template, request, send_from_directory, g, redirect, url_for, abort
import requests
import os, shutil
from pathlib import Path
from dotenv import load_dotenv, set_key, dotenv_values, find_dotenv
import configparser
from usage_tracker import record_usage, get_usage_today
from collections import Counter
# Prefer new google-genai SDK; fall back to legacy google-generativeai if present
try:
    from google import genai as genai  # google-genai
    _GENAI_SDK = 'new'
except Exception:
    try:
        import google.generativeai as genai  # legacy
        _GENAI_SDK = 'legacy'
    except Exception:
        genai = None
        _GENAI_SDK = None
import time
import threading
import re
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

# PyInstaller compatibility
def get_base_path():
    """Get the base path for files, whether running as script or executable."""
    if hasattr(sys, '_MEIPASS'):
        # Running as PyInstaller executable
        return sys._MEIPASS
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))

# Configure Flask app with proper paths for PyInstaller
base_path = get_base_path()
template_dir = os.path.join(base_path, 'templates')
static_dir = os.path.join(base_path, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

# App version (displayed in UI)
VERSION = "v3.7.2 beta (The 'matchymatchy' update)"

# User Mode (1 or 0): when enabled, hide settings/debug/library status and require Plex email/username prompt
USER_MODE = 0

# Global mood mapping for templates
MOOD_LABEL_MAP = {
    'underrated': 'Underrated',
    'surprise': 'Surprise Me',
    'comfort_zone': 'Out of my comfort zone',
    'comfort_food': 'Comfort Food',
    'award_winners': 'Award Winners',
    'popular_streaming': 'Popular (streaming services)',
    'seasonal': 'Seasonal'
}


# Load .env file (used in dev; for frozen EXE we'll use settings.ini)
ROOT = Path(__file__).resolve().parent
if os.path.exists(ROOT / ".env"):
    os.makedirs(ROOT / "env", exist_ok = True)
    shutil.move(ROOT / ".env", ROOT / "env" / ".env")
ENV_PATH = find_dotenv(usecwd=True) or str(ROOT / "env" / ".env")
load_dotenv(ENV_PATH)

# Runtime path helpers
def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))

def get_runtime_dir() -> str:
    # For frozen EXE, use the folder containing the executable
    if is_frozen():
        try:
            return os.path.dirname(sys.executable)
        except Exception:
            return os.getcwd()
    # For dev, use the project src dir
    return os.path.dirname(os.path.abspath(__file__))

def get_appdata_dir() -> str:
    # Fallback writable location on Windows
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    path = os.path.join(base, 'Conjurr')
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path

def get_settings_ini_paths() -> tuple[str, str]:
    primary = os.path.join(get_runtime_dir(), 'settings.ini')
    fallback = os.path.join(get_appdata_dir(), 'settings.ini')
    return primary, fallback

def read_settings_ini() -> dict:
    cfg = configparser.ConfigParser()
    primary, fallback = get_settings_ini_paths()
    path = primary if os.path.exists(primary) else (fallback if os.path.exists(fallback) else None)
    data = {}
    if path:
        try:
            cfg.read(path, encoding='utf-8')
            sect = 'conjurr'
            if cfg.has_section(sect):
                for k, v in cfg.items(sect):
                    data[k.upper()] = v
        except Exception:
            pass
    return data

def write_settings_ini(values: dict) -> tuple[bool, str|None]:
    cfg = configparser.ConfigParser()
    sect = 'conjurr'
    # Load existing
    existing = read_settings_ini()
    cfg[sect] = {}
    # Merge existing with new values (new values win)
    merged = {**existing, **{k.upper(): ('' if v is None else str(v)) for k, v in values.items()}}
    for k, v in merged.items():
        cfg[sect][k] = str(v)
    primary, fallback = get_settings_ini_paths()
    # Try primary (next to EXE) first
    for target in (primary, fallback):
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                cfg.write(f)
            return True, None
        except Exception as e:
            last_err = str(e)
            continue
    return False, last_err if 'last_err' in locals() else 'Unknown error writing settings.ini'

# Helper: determine if current request is from localhost (IPv4 127.0.0.1 or IPv6 ::1)
def _is_request_localhost(req: request) -> bool:
    try:
        # Honor common reverse-proxy headers first
        xf = req.headers.get('X-Forwarded-For') or req.headers.get('X-Real-IP')
        if xf:
            ip = xf.split(',')[0].strip()
        else:
            ip = req.remote_addr
        return ip in ('127.0.0.1', '::1', 'localhost')
    except Exception:
        return False

# Localhost-only endpoint to toggle USER_MODE by updating .env
@app.post('/toggle_user_mode')
def toggle_user_mode():
    if not _is_request_localhost(request):
        return abort(403)
    # Desired value optional; if missing, toggle current
    desired = request.form.get('value')
    current = False
    try:
        current = bool(getattr(g, 'USER_MODE', False))
    except Exception:
        current = False
    if desired in ('0', '1'):
        new_val = desired
    else:
        new_val = '0' if current else '1'
    ok, err = save_settings({'USER_MODE': new_val})
    # Redirect back to index; reload_settings will pick up the change automatically
    return redirect(url_for('index', toggled='1', _ts=int(time.time())))

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.static_folder, 'APP ICONS'), '32.ico', mimetype='image/x-icon')

# Debug route to test if Flask is working
@app.route('/test_plex')
def test_plex():
    """Test endpoint to verify Plex connection"""
    try:
        plex = get_plex_client()
        if plex is None:
            return jsonify({
                "success": False,
                "error": "Plex not configured (missing URL or token)"
            })
        
        # Test connection
        connection_ok = plex.test_connection()
        if not connection_ok:
            return jsonify({
                "success": False,
                "error": "Cannot connect to Plex server"
            })
        
        # Get library info
        libraries = plex.get_libraries()
        
        return jsonify({
            "success": True,
            "connection": "OK",
            "libraries": libraries,
            "library_count": len(libraries)
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })

@app.route('/debug')
def debug():
    return f"""
    <h1>Debug Info</h1>
    <p>Base path: {base_path}</p>
    <p>Template folder: {app.template_folder}</p>
    <p>Static folder: {app.static_folder}</p>
    <p>Templates exist: {os.path.exists(app.template_folder)}</p>
    <p>Static exists: {os.path.exists(app.static_folder)}</p>
    <p>ENV_PATH: {ENV_PATH}</p>
    <p>ENV exists: {os.path.exists(ENV_PATH)}</p>
    <p>Routes: {[rule.rule for rule in app.url_map.iter_rules()]}</p>
    """

# Print startup info
print(f"Flask app starting...")
print(f"Base path: {base_path}")
print(f"Template folder: {template_dir}")
print(f"Static folder: {static_dir}")
print(f"Templates exist: {os.path.exists(template_dir)}")
print(f"Static exists: {os.path.exists(static_dir)}")

# Config: Load from .env or environment
def get_settings():
    # Defaults
    defaults = {
        'TAUTULLI_URL': 'http://localhost:8181',
        'TAUTULLI_API_KEY': '',
        'GOOGLE_API_KEY': '',
        'TAUTULLI_DB_PATH': '',
        'USER_MODE': str(USER_MODE),
        'GEMINI_DAILY_QUOTAS': '',
        'TMDB_API_KEY': '',
        'OVERSEERR_URL': '',
        'OVERSEERR_API_KEY': '',
        'GEMINI_MODEL': '',
        'PLEX_URL': 'http://localhost:32400',
        'PLEX_TOKEN': '',
        'TAUTULLI_CACHE_REBUILD_TIME': '03:00',
    }
    # Suggested default DB path (Windows)
    try:
        localapp = os.environ.get('LOCALAPPDATA')
        if localapp:
            defaults['TAUTULLI_DB_PATH'] = os.path.join(localapp, 'Tautulli', 'Tautulli.db')
    except Exception:
        pass
    # If running frozen, prefer INI; else use .env
    if is_frozen():
        ini_vals = read_settings_ini()
        if not ini_vals:
            # Migrate from .env if exists
            try:
                env_vals = dotenv_values(ENV_PATH)
            except Exception:
                env_vals = {}
            if env_vals:
                write_settings_ini(env_vals)
                ini_vals = read_settings_ini()
        # Merge ini over defaults
        merged = {**defaults, **{k: ini_vals.get(k, defaults.get(k, '')) for k in defaults.keys()}}
        return merged
    else:
        # Dev: .env values override defaults, else OS env
        vals = {}
        try:
            vals = dotenv_values(ENV_PATH)
        except Exception:
            vals = {}
        result = {}
        for k in defaults.keys():
            result[k] = vals.get(k) or os.environ.get(k, defaults[k])
        return result

def save_settings(new_settings):
    # Persist settings depending on runtime: INI for frozen, .env for dev
    try:
        if is_frozen():
            ok, err = write_settings_ini(new_settings)
            return (ok, err)
        else:
            for k, v in new_settings.items():
                set_key(ENV_PATH, k, '' if v is None else str(v))
            load_dotenv(ENV_PATH, override=True)
            return True, None
    except Exception as e:
        return False, str(e)


# Always reload settings from .env at the start of each request
@app.before_request
def reload_settings():
    settings = get_settings()
    g.settings = settings
    # Expose user mode to templates
    try:
        um = settings.get('USER_MODE', USER_MODE)
        g.USER_MODE = bool(int(um)) if isinstance(um, (int, str)) else bool(um)
    except Exception:
        g.USER_MODE = bool(USER_MODE)
    g.TAUTULLI_URL = settings['TAUTULLI_URL']
    g.TAUTULLI_API_KEY = settings['TAUTULLI_API_KEY']
    g.GOOGLE_API_KEY = settings['GOOGLE_API_KEY']
    g.TAUTULLI_DB_PATH = settings.get('TAUTULLI_DB_PATH')
    g.use_tautulli_db = bool(g.TAUTULLI_DB_PATH and os.path.exists(g.TAUTULLI_DB_PATH))
    g.TMDB_API_KEY = settings.get('TMDB_API_KEY', '')
    g.OVERSEERR_URL = (settings.get('OVERSEERR_URL', '') or '').rstrip('/')
    g.OVERSEERR_API_KEY = settings.get('OVERSEERR_API_KEY', '')
    g.GEMINI_MODEL = settings.get('GEMINI_MODEL', '').strip()
    g.PLEX_URL = (settings.get('PLEX_URL', '') or '').rstrip('/')
    g.PLEX_TOKEN = settings.get('PLEX_TOKEN', '').strip()
    # Optional library inclusion filter: comma-separated section_ids (ints). Empty => include all for that type.
    raw_libs = ''  # library inclusion filter deprecated
    include_ids = set()
    if raw_libs.strip():
        for part in raw_libs.split(','):
            p = part.strip()
            if not p:
                continue
            # allow numeric only
            try:
                include_ids.add(int(p))
            except Exception:
                # keep raw as fallback string id
                include_ids.add(p)
    g.TAUTULLI_INCLUDE_LIBRARIES = set()  # deprecated
    # Optional: user-provided daily quotas per model as JSON, e.g. {"gemini-2.0-flash-001":200}
    g.GEMINI_DAILY_QUOTAS = {}
    try:
        import json as _json
        raw_q = settings.get('GEMINI_DAILY_QUOTAS')
        if raw_q:
            g.GEMINI_DAILY_QUOTAS = _json.loads(raw_q)
    except Exception:
        g.GEMINI_DAILY_QUOTAS = {}
    g.genai_client = None
    g.genai_sdk = None
    if g.GOOGLE_API_KEY and genai is not None:
        try:
            if _GENAI_SDK == 'new':
                # New SDK client
                g.genai_client = genai.Client(api_key=g.GOOGLE_API_KEY)
                g.genai_sdk = 'new'
            elif _GENAI_SDK == 'legacy':
                # Legacy SDK uses global configure()
                genai.configure(api_key=g.GOOGLE_API_KEY)
                g.genai_client = 'legacy'
                g.genai_sdk = 'legacy'
        except Exception:
            g.genai_client = None
            g.genai_sdk = None


# Plex API Client for direct availability checking
class PlexClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.headers = {
            'X-Plex-Token': token,
            'Accept': 'application/json'
        }
        self._libraries_cache = None
        self._library_content_cache = {}
        
    def test_connection(self):
        """Test Plex server connection"""
        try:
            r = requests.get(f"{self.base_url}/", headers=self.headers, timeout=10)
            return r.status_code == 200
        except Exception:
            return False
    
    def get_libraries(self):
        """Get all library sections"""
        if self._libraries_cache is not None:
            return self._libraries_cache
            
        try:
            r = requests.get(f"{self.base_url}/library/sections", headers=self.headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                libraries = []
                for section in data.get('MediaContainer', {}).get('Directory', []):
                    if section.get('type') in ['movie', 'show']:
                        libraries.append({
                            'key': section.get('key'),
                            'title': section.get('title'),
                            'type': section.get('type')
                        })
                self._libraries_cache = libraries
                return libraries
        except Exception as e:
            print(f"Error getting Plex libraries: {e}")
        return []
    
    def get_library_content_titles(self, library_key, library_type):
        """Get all titles from a specific library"""
        cache_key = f"{library_key}_{library_type}"
        if cache_key in self._library_content_cache:
            return self._library_content_cache[cache_key]
            
        titles = set()
        try:
            # Get all items from this library
            url = f"{self.base_url}/library/sections/{library_key}/all"
            r = requests.get(url, headers=self.headers, timeout=30)
            
            if r.status_code == 200:
                data = r.json()
                for item in data.get('MediaContainer', {}).get('Metadata', []):
                    title = item.get('title', '').strip()
                    if title:
                        # Use the new title variations function
                        variations = get_title_variations(title)
                        titles.update(variations)
                            
        except Exception as e:
            print(f"Error getting library content for {library_key}: {e}")
        
        self._library_content_cache[cache_key] = titles
        return titles
    
    def build_availability_cache(self):
        """Build a complete cache of all available titles"""
        all_titles = {'movie': set(), 'show': set()}
        
        libraries = self.get_libraries()
        for library in libraries:
            library_key = library['key']
            library_type = library['type']
            
            if library_type in ['movie', 'show']:
                print(f"Scanning Plex library: {library['title']} ({library_type})")
                titles = self.get_library_content_titles(library_key, library_type)
                all_titles[library_type].update(titles)
        
        return all_titles
    
    def batch_check_availability(self, items, media_type):
        """Batch check availability for multiple items"""
        # Get all available titles for this media type
        libraries = self.get_libraries()
        available_titles = set()
        
        for library in libraries:
            if library['type'] == media_type:
                titles = self.get_library_content_titles(library['key'], media_type)
                available_titles.update(titles)
        
        # Check each item against available titles
        results = {}
        for item in items:
            title = item.get('title') if isinstance(item, dict) else item
            if title:
                # Generate all variations of the AI title for matching
                ai_variations = get_title_variations(title)
                
                # Use only exact set-based matching (no substring fallback)
                # This prevents false positives like "Mythbusters Jr." matching "Mythbusters"
                is_available = bool(ai_variations & available_titles)
                
                results[title] = is_available
        
        return results


# Global Plex client instance
plex_client = None

def get_plex_client():
    """Get or create Plex client instance"""
    global plex_client
    settings = get_settings()
    plex_url = settings.get('PLEX_URL', '').strip()
    plex_token = settings.get('PLEX_TOKEN', '').strip()
    
    if not plex_url or not plex_token:
        return None
        
    if plex_client is None or plex_client.base_url != plex_url.rstrip('/') or plex_client.token != plex_token:
        plex_client = PlexClient(plex_url, plex_token)
        
    return plex_client


_USER_CACHE = { 'users': None, 'hash': None, 'ts': 0 }
_USER_CACHE_LOCK = threading.Lock()

def _hash_users(user_list):
    try:
        # Build a stable hash based on user_id + username + email
        parts = []
        for u in user_list or []:
            try:
                parts.append(f"{u.get('user_id')}|{(u.get('username') or '').lower()}|{(u.get('email') or '').lower()}")
            except Exception:
                continue
        import hashlib
        return hashlib.sha1('\n'.join(sorted(parts)).encode('utf-8')).hexdigest()
    except Exception:
        return None

# Low-level fetch (no caching) from Tautulli / DB
def _fetch_users_raw():
    # Prefer DB if available
    if getattr(g, 'use_tautulli_db', False):
        try:
            from tautulli_db import db_get_users
            db_users = db_get_users(g.TAUTULLI_DB_PATH)
            # Best-effort: enrich with API data to populate email/username if missing
            params = {
                'apikey': g.TAUTULLI_API_KEY,
                'cmd': 'get_users'
            }
            api_users = []
            try:
                resp = requests.get(f"{g.TAUTULLI_URL}/api/v2", params=params, timeout=5)
                data = resp.json()
                payload = data.get('response', {}).get('data', [])
                if isinstance(payload, list):
                    api_users = payload
                elif isinstance(payload, dict):
                    if isinstance(payload.get('users'), list):
                        api_users = [u for u in payload['users'] if u.get('is_active', True)]
                    elif isinstance(payload.get('data'), list):
                        api_users = payload['data']
            except Exception:
                api_users = []
            if not api_users:
                return db_users
            # Build indices for API users
            idx_by_id = {str(u.get('user_id')): u for u in api_users if u.get('user_id') is not None}
            idx_by_username = {str(u.get('username')).lower(): u for u in api_users if u.get('username')}
            enriched = []
            for u in db_users:
                uid = str(u.get('user_id'))
                au = idx_by_id.get(uid)
                if not au and u.get('username'):
                    au = idx_by_username.get(str(u.get('username')).lower())
                if au:
                    # Fill missing username/email
                    if not u.get('username') and au.get('username'):
                        u['username'] = au.get('username')
                    if not u.get('email') and au.get('email'):
                        u['email'] = au.get('email')
                    # Prefer a nicer friendly name if DB one is generic
                    if (not u.get('friendly_name') or str(u.get('friendly_name')) == str(u.get('user_id'))):
                        u['friendly_name'] = au.get('friendly_name') or au.get('username') or u.get('friendly_name')
                    # is_active flag
                    if 'is_active' not in u and 'is_active' in au:
                        u['is_active'] = au['is_active']
                enriched.append(u)
            # Keep only active users if the flag exists
            return [u for u in enriched if u.get('is_active', True)]
        except Exception:
            pass
    # Fallback to API
    params = {
        'apikey': g.TAUTULLI_API_KEY,
        'cmd': 'get_users'
    }
    try:
        resp = requests.get(f"{g.TAUTULLI_URL}/api/v2", params=params, timeout=2)
        data = resp.json()
        payload = data.get('response', {}).get('data', [])
        # Tautulli may return a list directly or under a 'users' or 'data' key
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            user_list = []
            if isinstance(payload.get('users'), list):
                users = payload['users']
                for user in users:
                    # Only include active users when available
                    if user.get('is_active', True):
                        user_list.append(user)
                return user_list
            if isinstance(payload.get('data'), list):
                return payload['data']
        return []
    except Exception:
        return []

def refresh_user_cache_if_changed():
    """Fetch latest users and update cache only if membership changed.
    Called during recommendation generation (POST) to detect updates lazily."""
    try:
        latest = _fetch_users_raw()
        new_hash = _hash_users(latest)
        with _USER_CACHE_LOCK:
            if new_hash and new_hash != _USER_CACHE['hash']:
                _USER_CACHE['users'] = latest
                _USER_CACHE['hash'] = new_hash
                _USER_CACHE['ts'] = time.time()
    except Exception:
        pass

def get_cached_users():
    """Return cached users (may be None on first run). Does not trigger network."""
    with _USER_CACHE_LOCK:
        users = _USER_CACHE['users']
    # If cache empty, perform one lazy fill (non-blocking future calls reused)
    if users is None:
        users = _fetch_users_raw()
        with _USER_CACHE_LOCK:
            _USER_CACHE['users'] = users
            _USER_CACHE['hash'] = _hash_users(users)
            _USER_CACHE['ts'] = time.time()
    return users

# Helper to fetch user watch history from Tautulli
def get_user_watch_history_api(user_id):
    """Always fetch recent (bounded window) history via API for top/recent calculations."""
    one_year_ago = int(time.time()) - 365*24*60*60
    params = {
        'apikey': g.TAUTULLI_API_KEY,
        'cmd': 'get_history',
        'user_id': user_id,
        'length': 1000,
        'after': one_year_ago
    }
    try:
        resp = requests.get(f"{g.TAUTULLI_URL}/api/v2", params=params, timeout=5)
        data = resp.json()
        return data.get('response', {}).get('data', {}).get('data', [])
    except Exception:
        return []

def get_user_watch_history(user_id):
    """Retained for backward compatibility: prefer DB for recent subset if available, else API.
    Not used for top/recent anymore (we explicitly call API)."""
    one_year_ago = int(time.time()) - 365*24*60*60
    if getattr(g, 'use_tautulli_db', False):
        try:
            from tautulli_db import db_get_user_watch_history
            return db_get_user_watch_history(g.TAUTULLI_DB_PATH, user_id, after=one_year_ago, limit=1000)
        except Exception:
            pass
    return get_user_watch_history_api(user_id)

# Helper to fetch the user's entire watch history from Tautulli (paginated)
def get_user_watch_history_all(user_id):
    # Prefer DB if available
    if getattr(g, 'use_tautulli_db', False):
        try:
            from tautulli_db import db_get_user_watch_history_all
            return db_get_user_watch_history_all(g.TAUTULLI_DB_PATH, user_id)
        except Exception:
            pass
    start = 0
    page_size = 1000
    all_items = []
    total_records = None
    while True:
        params = {
            'apikey': g.TAUTULLI_API_KEY,
            'cmd': 'get_history',
            'user_id': user_id,
            'start': start,
            'length': page_size
        }
        try:
            resp = requests.get(f"{g.TAUTULLI_URL}/api/v2", params=params, timeout=15)
            data = resp.json()
            payload = data.get('response', {}).get('data', {})
            items = payload.get('data', []) if isinstance(payload, dict) else []
            if total_records is None and isinstance(payload, dict):
                total_records = payload.get('recordsTotal') or payload.get('recordsFiltered')
            if not items:
                break
            all_items.extend(items)
            # Stop if we've collected all records
            if total_records is not None and len(all_items) >= int(total_records):
                break
            start += page_size
        except Exception:
            break
    return all_items

# Helpers
def normalize_title(title: str) -> str:
    if not title:
        return ''
    t = title.lower()
    
    # Handle common character/word substitutions before removing special chars
    # Convert & to "and" 
    t = re.sub(r'\s*&\s*', ' and ', t)
    t = re.sub(r'\s*\+\s*', ' and ', t)
    
    # Preserve important differentiators before normalization
    # Keep Jr, Sr, III, etc. as they are significant differentiators
    important_suffixes = ['jr', 'sr', 'ii', 'iii', 'iv', 'v']
    preserved_suffix = ''
    for suffix in important_suffixes:
        pattern = rf'\b{suffix}\.?\s*$'
        if re.search(pattern, t):
            preserved_suffix = f' {suffix}'
            t = re.sub(pattern, '', t).strip()
            break
    
    # Remove all non-alphanumeric except spaces
    t = re.sub(r'[^a-z0-9 ]', '', t)
    
    # Normalize common word variations
    t = re.sub(r'\band\b', '', t)  # Remove "and" completely for better matching
    t = re.sub(r'\bthe\b', '', t)  # Remove articles
    t = re.sub(r'\ba\b', '', t)
    t = re.sub(r'\ban\b', '', t)
    
    # Clean up multiple spaces and add back preserved suffix
    t = re.sub(r'\s+', ' ', t).strip()
    t += preserved_suffix
    return t.strip()

def get_title_variations(title: str) -> set[str]:
    """Generate multiple variations of a title for better matching"""
    if not title:
        return set()
    
    variations = set()
    title_lower = title.lower()
    
    # Always add the normalized version
    normalized = normalize_title(title)
    if normalized:
        variations.add(normalized)
    
    # Add original lowercased
    variations.add(title_lower)
    
    # Remove common version suffixes for core matching
    version_suffixes = [
        r'\s+xl\b',           # "QI XL" -> "QI"
        r'\s+extended\b',     # "Movie Extended" -> "Movie"
        r'\s+uncut\b',        # "Movie Uncut" -> "Movie"
        r'\s+directors?\s*cut\b',  # "Movie Director's Cut" -> "Movie" (handles apostrophe)
        r'\s+ultimate\s+edition\b', # "Movie Ultimate Edition" -> "Movie"
        r'\s+special\s+edition\b',  # "Movie Special Edition" -> "Movie"
        r'\s+remastered\b',   # "Movie Remastered" -> "Movie"
        r'\s+redux\b',        # "Movie Redux" -> "Movie"
        r'\s+\d+th\s+anniversary\b',  # "Movie 25th Anniversary" -> "Movie"
    ]
    
    for suffix_pattern in version_suffixes:
        base_title = re.sub(suffix_pattern, '', title_lower)
        if base_title != title_lower:
            variations.add(base_title)
            # Also add normalized version of base title
            base_normalized = normalize_title(base_title)
            if base_normalized:
                variations.add(base_normalized)
    
    # Remove articles from beginning
    for article in ['the ', 'a ', 'an ']:
        if title_lower.startswith(article):
            variant = title_lower[len(article):]
            variations.add(variant)
            # Add normalized version of variant too
            variant_normalized = normalize_title(variant)
            if variant_normalized:
                variations.add(variant_normalized)
    
    # Remove year from title if present
    year_pattern = r'\s*\(\d{4}\)\s*$'
    title_no_year = re.sub(year_pattern, '', title_lower)
    if title_no_year != title_lower:
        variations.add(title_no_year)
        # Add normalized version without year
        no_year_normalized = normalize_title(title_no_year)
        if no_year_normalized:
            variations.add(no_year_normalized)
    
    # Remove empty strings
    variations.discard('')
    return variations

def fuzzy_available(ai_list, library_list, watched_set, threshold=80):
    """Deprecated full fuzzy matcher retained as a fallback if enabled.
    Set ENABLE_FUZZY_FALLBACK=1 in environment to activate when TMDb/Overseerr fail."""
    if not os.environ.get('ENABLE_FUZZY_FALLBACK'):
        return [], []
    available = []
    debug_matches = []
    norm_library = [normalize_title(lib) for lib in library_list]
    for ai_item in ai_list:
        ai_title = ai_item.get('title') if isinstance(ai_item, dict) else ai_item
        ai_year = ai_item.get('year') if isinstance(ai_item, dict) else None
        if not ai_title:
            continue
        norm_ai_title = normalize_title(ai_title)
        candidates = [norm_ai_title]
        if ai_year:
            candidates.insert(0, f"{norm_ai_title} {ai_year}")
        matched_title = None
        best_score = 0
        for cand in candidates:
            match = process.extractOne(cand, norm_library, scorer=fuzz.token_sort_ratio, score_cutoff=threshold) or (None,0,None)
            _, score, idx = match
            if score > best_score and match[0] is not None and idx is not None:
                matched_title = library_list[idx]
                best_score = score
        debug_matches.append({'ai_title': ai_title, 'ai_year': ai_year, 'match': matched_title, 'score': best_score})
        if matched_title and matched_title not in watched_set and matched_title not in available:
            available.append(matched_title)
    return available, debug_matches

# Tautulli helpers: search and poster resolution
def _poster_url_from_result(result: dict) -> str | None:
    return None

def _tmdb_search(media_type: str, title: str, year: int | None):
    # Use TMDb's search endpoints
    try:
        if not getattr(g, 'TMDB_API_KEY', ''):
            return None
        base = 'https://api.themoviedb.org/3'
        if media_type == 'movie':
            url = f"{base}/search/movie"
            params = {'api_key': g.TMDB_API_KEY, 'query': title, 'include_adult': 'false'}
            if year:
                params['year'] = year
        else:
            url = f"{base}/search/tv"
            params = {'api_key': g.TMDB_API_KEY, 'query': title, 'include_adult': 'false'}
            if year:
                params['first_air_date_year'] = year
        resp = requests.get(url, params=params, timeout=8)
        j = resp.json()
        results = j.get('results') or []
        if not results:
            return None
        ntarget = normalize_title(title)
        def score_item(it):
            name = it.get('title') or it.get('name') or ''
            year_field = it.get('release_date') or it.get('first_air_date') or ''
            year_val = None
            if isinstance(year_field, str) and len(year_field) >= 4:
                try:
                    year_val = int(year_field[:4])
                except Exception:
                    year_val = None
            title_score = fuzz.token_sort_ratio(ntarget, normalize_title(name))
            year_bonus = 5 if (year and year_val == year) else 0
            return (title_score + year_bonus, title_score, it.get('popularity') or 0)
        # Sort with composite keys: primary = title+year bonus, secondary = raw title score, tertiary = popularity
        best = sorted(results, key=score_item, reverse=True)[0]
        path = best.get('poster_path')
        if not path:
            return None
        # Use a reasonable size; w342 balances size/quality
        poster_url = f"https://image.tmdb.org/t/p/w342{path}"
        tmdb_id = best.get('id')
        if not tmdb_id:
            return None
        return { 'poster_url': poster_url, 'tmdb_id': tmdb_id }
    except Exception:
        return None

def _extract_year_from_title(t: str) -> int | None:
    # Try to detect a year in parentheses
    if not t:
        return None
    import re as _re
    m = _re.search(r'\((\d{4})\)', t)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

def _tmdb_details(media_type: str, tmdb_id: int) -> dict | None:
    """Fetch detail metadata (overview, runtime, rating) for a TMDb item. Lightweight caching in g."""
    try:
        if not getattr(g, 'TMDB_API_KEY', '') or not tmdb_id:
            return None
        cache = getattr(g, '_tmdb_details_cache', None)
        if cache is None:
            cache = {}
            setattr(g, '_tmdb_details_cache', cache)
        key = (media_type, tmdb_id)
        if key in cache:
            return cache[key]
        base = 'https://api.themoviedb.org/3'
        if media_type == 'movie':
            url = f"{base}/movie/{tmdb_id}"
        else:
            url = f"{base}/tv/{tmdb_id}"
        resp = requests.get(url, params={'api_key': g.TMDB_API_KEY, 'language': 'en-US'}, timeout=6)
        if resp.status_code != 200:
            cache[key] = None
            return None
        data = resp.json() or {}
        cache[key] = data
        return data
    except Exception:
        return None

def _format_runtime_minutes(minutes: int | None) -> str | None:
    if not minutes or minutes <= 0:
        return None
    h = minutes // 60
    m = minutes % 60
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"

_TMDB_SEARCH_CACHE: dict[tuple[str, str, int | None], dict | None] = {}

def get_posters_for_titles(media_type: str, titles: list[str], year_map: dict | None = None, *, max_workers: int = 10, fetch_details: bool = True, pre_tmdb_map: dict | None = None) -> list[dict]:
    """Fetch posters (and optionally details) for a list of titles more quickly.

    Optimizations:
    - Per-process in-memory cache for TMDb search results (_TMDB_SEARCH_CACHE)
    - Threaded concurrent search+details fetch (default 6 workers)
    - Skip duplicate titles
    - If year-hint search fails, fall back once without year
    - Details fetch can be disabled via fetch_details flag
    """
    api_key = getattr(g, 'TMDB_API_KEY', '') if hasattr(g, 'TMDB_API_KEY') else ''
    if not api_key:
        return []
    year_map = year_map or {}
    pre_tmdb_map = pre_tmdb_map or {}
    overseerr_base = getattr(g, 'OVERSEERR_URL', '') or ''
    # Preserve input order while de-duplicating
    seen = set()
    work: list[tuple[int, str]] = []
    for idx, t in enumerate(titles):
        if not t:
            continue
        if t in seen:
            continue
        seen.add(t)
        work.append((idx, t))
    if not work:
        return []

    def _search_one(title: str):
        year_hint = year_map.get(title) or _extract_year_from_title(title)
        # Cache key uses lower title + year (may be None)
        preset_id = pre_tmdb_map.get(title)
        if preset_id:
            # Fast path: fetch details for poster (store in cache using year-hint key)
            key_direct = (media_type, f"__direct_{preset_id}", None)
            res_direct = _TMDB_SEARCH_CACHE.get(key_direct)
            if res_direct is None:
                try:
                    base = 'https://api.themoviedb.org/3'
                    url = f"{base}/movie/{preset_id}" if media_type == 'movie' else f"{base}/tv/{preset_id}"
                    resp_d = requests.get(url, params={'api_key': api_key, 'language': 'en-US'}, timeout=6)
                    if resp_d.status_code == 200:
                        jd = resp_d.json() or {}
                        path = jd.get('poster_path')
                        if path:
                            res_direct = {'poster_url': f"https://image.tmdb.org/t/p/w342{path}", 'tmdb_id': preset_id}
                except Exception:
                    res_direct = None
                _TMDB_SEARCH_CACHE[key_direct] = res_direct
            if res_direct:
                return year_hint, res_direct
        key = (media_type, title.lower(), year_hint if isinstance(year_hint, int) else None)
        res = _TMDB_SEARCH_CACHE.get(key)
        if res is None:
            # Local minimal search to avoid relying on Flask context inside threads
            try:
                base = 'https://api.themoviedb.org/3'
                if media_type == 'movie':
                    url = f"{base}/search/movie"
                    params = {'api_key': api_key, 'query': title, 'include_adult': 'false'}
                    if year_hint:
                        params['year'] = year_hint
                else:
                    url = f"{base}/search/tv"
                    params = {'api_key': api_key, 'query': title, 'include_adult': 'false'}
                    if year_hint:
                        params['first_air_date_year'] = year_hint
                resp = requests.get(url, params=params, timeout=8)
                j = resp.json()
                results = j.get('results') or []
                if results:
                    ntarget = normalize_title(title)
                    def score_item(it):
                        name = it.get('title') or it.get('name') or ''
                        year_field = it.get('release_date') or it.get('first_air_date') or ''
                        year_val = None
                        if isinstance(year_field, str) and len(year_field) >= 4:
                            try:
                                year_val = int(year_field[:4])
                            except Exception:
                                year_val = None
                        title_score = fuzz.token_sort_ratio(ntarget, normalize_title(name))
                        year_bonus = 5 if (year_hint and year_val == year_hint) else 0
                        return (title_score + year_bonus, title_score, it.get('popularity') or 0)
                    best = sorted(results, key=score_item, reverse=True)[0]
                    path = best.get('poster_path')
                    tmdb_id = best.get('id')
                    if path and tmdb_id:
                        res = {'poster_url': f"https://image.tmdb.org/t/p/w342{path}", 'tmdb_id': tmdb_id}
                    else:
                        res = None
                else:
                    res = None
            except Exception:
                res = None
            # Fallback without year if nothing found and we had a year
            if not res and year_hint:
                key2 = (media_type, title.lower(), None)
                res2 = _TMDB_SEARCH_CACHE.get(key2)
                if res2 is None:
                    # second attempt without year
                    try:
                        base = 'https://api.themoviedb.org/3'
                        if media_type == 'movie':
                            url = f"{base}/search/movie"
                            params = {'api_key': api_key, 'query': title, 'include_adult': 'false'}
                        else:
                            url = f"{base}/search/tv"
                            params = {'api_key': api_key, 'query': title, 'include_adult': 'false'}
                        resp2 = requests.get(url, params=params, timeout=8)
                        j2 = resp2.json()
                        results2 = j2.get('results') or []
                        if results2:
                            ntarget2 = normalize_title(title)
                            def score_item2(it):
                                name = it.get('title') or it.get('name') or ''
                                title_score = fuzz.token_sort_ratio(ntarget2, normalize_title(name))
                                return (title_score, it.get('popularity') or 0)
                            best2 = sorted(results2, key=score_item2, reverse=True)[0]
                            path2 = best2.get('poster_path')
                            tmdb_id2 = best2.get('id')
                            if path2 and tmdb_id2:
                                res2 = {'poster_url': f"https://image.tmdb.org/t/p/w342{path2}", 'tmdb_id': tmdb_id2}
                            else:
                                res2 = None
                        else:
                            res2 = None
                    except Exception:
                        res2 = None
                    _TMDB_SEARCH_CACHE[key2] = res2
                res = res2
            _TMDB_SEARCH_CACHE[key] = res
        return year_hint, res

    def _details_for(media_type: str, tmdb_id: int):
        try:
            # local details call (cannot rely on g inside thread safely)
            if not tmdb_id:
                return None
            base = 'https://api.themoviedb.org/3'
            url = f"{base}/movie/{tmdb_id}" if media_type == 'movie' else f"{base}/tv/{tmdb_id}"
            resp = requests.get(url, params={'api_key': api_key, 'language': 'en-US'}, timeout=6)
            if resp.status_code != 200:
                return None
            return resp.json() or {}
        except Exception:
            return None

    results_tmp: list[tuple[int, dict]] = []

    # Phase 1: concurrent search (and optional details)
    # Bound workers to number of tasks
    workers = min(max_workers, len(work)) if max_workers > 1 else 1
    if workers <= 1:
        # Fallback sequential (unlikely)
        for idx, title in work:
            year_hint, search = _search_one(title)
            if not (search and isinstance(search, dict)):
                continue
            tmdb_id = search.get('tmdb_id')
            overview = runtime_str = vote = None
            if fetch_details and tmdb_id:
                details = _details_for(media_type, tmdb_id)
                if details:
                    try:
                        overview = (details.get('overview') or '')[:500].strip() or None
                    except Exception:
                        pass
                    if media_type == 'movie':
                        runtime_str = _format_runtime_minutes(details.get('runtime'))
                    else:
                        rt_list = details.get('episode_run_time')
                        if isinstance(rt_list, list) and rt_list:
                            runtime_str = _format_runtime_minutes(rt_list[0])
                    vote_val = details.get('vote_average')
                    if isinstance(vote_val, (int, float)) and vote_val > 0:
                        vote = round(vote_val, 1)
            href = f"{overseerr_base}/{'movie' if media_type=='movie' else 'tv'}/{tmdb_id}" if overseerr_base and tmdb_id else None
            results_tmp.append((idx, {
                'title': title,
                'url': search.get('poster_url'),
                'source': 'tmdb',
                'tmdb_id': tmdb_id,
                'href': href,
                'year': year_hint,
                'overview': overview,
                'runtime': runtime_str,
                'vote': vote,
                'media_type': media_type,
            }))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_search_one, title): (idx, title) for idx, title in work}
            for fut in as_completed(future_map):
                idx, title = future_map[fut]
                try:
                    year_hint, search = fut.result()
                except Exception:
                    continue
                if not (search and isinstance(search, dict)):
                    continue
                tmdb_id = search.get('tmdb_id')
                overview = runtime_str = vote = None
                details = None
                if fetch_details and tmdb_id:
                    # Fetch details in the same worker thread (sequential inside thread)
                    details = _details_for(media_type, tmdb_id)
                if details:
                    try:
                        overview = (details.get('overview') or '')[:500].strip() or None
                    except Exception:
                        pass
                    if media_type == 'movie':
                        runtime_str = _format_runtime_minutes(details.get('runtime'))
                    else:
                        rt_list = details.get('episode_run_time')
                        if isinstance(rt_list, list) and rt_list:
                            runtime_str = _format_runtime_minutes(rt_list[0])
                    vote_val = details.get('vote_average')
                    if isinstance(vote_val, (int, float)) and vote_val > 0:
                        vote = round(vote_val, 1)
                href = f"{overseerr_base}/{'movie' if media_type=='movie' else 'tv'}/{tmdb_id}" if overseerr_base and tmdb_id else None
                results_tmp.append((idx, {
                    'title': title,
                    'url': search.get('poster_url'),
                    'source': 'tmdb',
                    'tmdb_id': tmdb_id,
                    'href': href,
                    'year': year_hint,
                    'overview': overview,
                    'runtime': runtime_str,
                    'vote': vote,
                    'media_type': media_type,
                }))

    # Restore original order
    posters = [p for _, p in sorted(results_tmp, key=lambda x: x[0]) if p.get('url')]
    return posters

def extract_json_object(text: str) -> str | None:
    if not text:
        return None
    # Strip code fences if present
    txt = text.strip()
    if txt.startswith('```'):
        # remove first fence line and possible language
        parts = txt.split('\n', 1)
        txt = parts[1] if len(parts) > 1 else txt
        if txt.endswith('```'):
            txt = txt[: -3]
    # Find the first top-level JSON object using simple bracket matching
    start = txt.find('{')
    end = txt.rfind('}')
    if start != -1 and end != -1 and end > start:
        return txt[start:end+1]
    return None


# Dummy recommendation logic (to be improved)
def recommend_for_user(user_id, mode='history', decade_code=None, genre_code=None, mood_code=None):
    import time
    timing = {}
    t0 = time.time()
    # Attempt to capture requester IP from current Flask request context
    try:
        req_ip = None
        from flask import request as _rq
        if _rq:
            # Honor common reverse-proxy header first
            xf = _rq.headers.get('X-Forwarded-For') or _rq.headers.get('X-Real-IP')
            if xf:
                # Could be comma separated list; take first
                req_ip = xf.split(',')[0].strip()
            if not req_ip:
                req_ip = _rq.remote_addr
        # Determine model to display for debugging
        display_model = g.GEMINI_MODEL
        if not display_model:
            # Show the default model that will be tried first
            if getattr(g, 'genai_sdk', None) == 'new':
                display_model = 'gemini-2.5-flash-lite'  # first in default order
            elif getattr(g, 'genai_sdk', None) == 'legacy':
                display_model = 'gemini-pro'
            else:
                display_model = 'none'
        
        # Get username for debug output
        debug_username = "unknown"
        try:
            users = get_cached_users()
            user_match = next((u for u in users if str(u.get('user_id')) == str(user_id)), None)
            if user_match:
                debug_username = user_match.get('username') or user_match.get('friendly_name') or "unknown"
        except Exception:
            pass
        
        print(f"DEBUG: recommend_for_user called (ip={req_ip}) user_id={user_id} username={debug_username} mode={mode} decade={decade_code} genre={genre_code} mood={mood_code} model={display_model}")
    except Exception:
        # Determine model to display for debugging
        display_model = g.GEMINI_MODEL
        if not display_model:
            # Show the default model that will be tried first
            if getattr(g, 'genai_sdk', None) == 'new':
                display_model = 'gemini-2.5-flash-lite'  # first in default order
            elif getattr(g, 'genai_sdk', None) == 'legacy':
                display_model = 'gemini-pro'
            else:
                display_model = 'none'
        
        # Get username for debug output (fallback)
        debug_username = "unknown"
        try:
            users = get_cached_users()
            user_match = next((u for u in users if str(u.get('user_id')) == str(user_id)), None)
            if user_match:
                debug_username = user_match.get('username') or user_match.get('friendly_name') or "unknown"
        except Exception:
            pass
        
        print(f"DEBUG: recommend_for_user called user_id={user_id} username={debug_username} mode={mode} mood={mood_code} model={display_model}")

    # Step 1: Recent (API) history strictly for top/recent calculations (stateless, up-to-date)
    hist_api = get_user_watch_history_api(user_id)
    timing['user_history'] = time.time() - t0

    # Step 2: Top watched and recents derived ONLY from API subset per requirement
    t1 = time.time()
    hist = hist_api  # alias for legacy variable names below
    shows = [item.get('grandparent_title') for item in hist if item.get('media_type') == 'episode' and item.get('grandparent_title')]
    movies = [item.get('title') for item in hist if item.get('media_type') == 'movie' and item.get('title')]
    show_counts = Counter(shows)
    movie_counts = Counter(movies)
    top_shows = [show for show, _ in show_counts.most_common(3)]
    top_movies = [movie for movie, _ in movie_counts.most_common(3)]

    # Compute last 10 watched (helper)
    def _ts(it):
        for k in ('date', 'watched_at', 'timestamp', 'last_played', 'time'):
            v = it.get(k)
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v)
                except Exception:
                    continue
        return None

    any_ts = any(_ts(it) is not None for it in hist)
    if any_ts:
        ordered_hist = sorted(hist, key=lambda it: _ts(it) or 0.0, reverse=True)
    else:
        # Assume API returns newest-first; keep as-is
        ordered_hist = list(hist)
    last10_shows = []
    last10_movies = []
    seen_shows = set()
    seen_movies = set()
    for it in ordered_hist:
        if it.get('media_type') == 'episode':
            title = it.get('grandparent_title')
            if title and title not in seen_shows:
                last10_shows.append(title)
                seen_shows.add(title)
        elif it.get('media_type') == 'movie':
            title = it.get('title')
            if title and title not in seen_movies:
                last10_movies.append(title)
                seen_movies.add(title)
        if len(last10_shows) >= 10 and len(last10_movies) >= 10:
            break

    timing['top_watched'] = time.time() - t1

    # Step 2b: Build an all-time watched set from FULL history (prefer DB) for filtering only
    t2a = time.time()
    hist_all = get_user_watch_history_all(user_id)
    shows_all = [it.get('grandparent_title') for it in hist_all if it.get('media_type') == 'episode' and it.get('grandparent_title')]
    movies_all = [it.get('title') for it in hist_all if it.get('media_type') == 'movie' and it.get('title')]
    watched_set_all = set(shows_all + movies_all)
    timing['user_history_all'] = time.time() - t2a

    # Build full unique-by-recency watched lists from full history for AI prompt (do NOT override top/recent)
    ordered_all = sorted(hist_all, key=lambda it: it.get('date') or 0.0, reverse=True)
    watched_shows_unique = []
    watched_movies_unique = []
    seen_shows2 = set()
    seen_movies2 = set()
    for it in ordered_all:
        if it.get('media_type') == 'episode':
            t = it.get('grandparent_title')
            if t and t not in seen_shows2:
                watched_shows_unique.append(t)
                seen_shows2.add(t)
        elif it.get('media_type') == 'movie':
            t = it.get('title')
            if t and t not in seen_movies2:
                watched_movies_unique.append(t)
                seen_movies2.add(t)
    # Cap what we include in the prompt to avoid exceeding model limits
    WATCHED_MAX_PER_TYPE = 100
    watched_shows_in_prompt = watched_shows_unique[:WATCHED_MAX_PER_TYPE]
    watched_movies_in_prompt = watched_movies_unique[:WATCHED_MAX_PER_TYPE]

    # Step 3: Skip legacy full-library prefetch (deprecated) – availability resolved later
    debug = {'library_prefetch': 'skipped'}
    timing['library_fetch'] = 0.0

    # Step 5: Gemini AI recommendations
    t4 = time.time()
    gemini_recs = {'shows': [], 'movies': [], 'error': None, 'prompt': None, 'raw_response': None, 'parsed_json': None, 'available_models': None}
    ai_recommended = {'shows': [], 'movies': [], 'categories': []}
    # Build selection descriptor for custom mode
    selection_desc = None
    decades_label_map = {
        1950: '1950s', 1960: '1960s', 1970: '1970s', 1980: '1980s', 1990: '1990s', 2000: '2000s', 2010: '2010s', 2020: '2020 - Now'
    }
    genre_label_map = {
        'action': 'Action','drama':'Drama','comedy':'Comedy','scifi':'Sci-Fi','horror':'Horror','thriller':'Thriller','documentary':'Documentary','animation':'Animation','family':'Family','fantasy':'Fantasy','romance':'Romance','crime':'Crime','mystery':'Mystery','adventure':'Adventure','war':'War','western':'Western','musical':'Musical','biography':'Biography','history':'History','sports':'Sports'
    }
    # Define mood mapping
    mood_label_map = MOOD_LABEL_MAP
    
    if mode == 'custom':
        # If mood is selected, it takes precedence over decade/genre
        if mood_code:
            # Mood mode - ignore decade and genre
            mood_label = mood_label_map.get(mood_code)
            if mood_label:
                selection_desc = mood_label
            else:
                return {
                    'user_id': user_id,
                    'shows': [], 'movies': [], 'top_shows': [], 'top_movies': [],
                    'ai_shows': [], 'ai_movies': [], 'ai_categories': [],
                    'ai_shows_titles': [], 'ai_movies_titles': [],
                    'ai_shows_unavailable': [], 'ai_movies_unavailable': [],
                    'ai_shows_available': [], 'ai_movies_available': [],
                    'history_count': len(hist_all),
                    'show_posters': [], 'movie_posters': [],
                    'show_posters_unavailable': [], 'movie_posters_unavailable': [],
                    'debug': {'error': f'Invalid mood: {mood_code}. Valid options: {", ".join(mood_label_map.keys())}', 'timing': timing},
                    'selection_desc': None,
                    'mode': mode,
                    'decade_code': decade_code,
                    'genre_code': genre_code,
                    'mood_code': mood_code,
                }
        else:
            # Traditional decade/genre mode - validate at least one selection
            if not decade_code and not genre_code:
                return {
                    'user_id': user_id,
                    'shows': [], 'movies': [], 'top_shows': [], 'top_movies': [],
                    'ai_shows': [], 'ai_movies': [], 'ai_categories': [],
                    'ai_shows_titles': [], 'ai_movies_titles': [],
                    'ai_shows_unavailable': [], 'ai_movies_unavailable': [],
                    'ai_shows_available': [], 'ai_movies_available': [],
                    'history_count': len(hist_all),
                    'show_posters': [], 'movie_posters': [],
                    'show_posters_unavailable': [], 'movie_posters_unavailable': [],
                    'debug': {'error': 'At least a decade, genre, or mood must be selected for Custom mode.', 'timing': timing},
                    'selection_desc': None,
                    'mode': mode,
                    'decade_code': decade_code,
                    'genre_code': genre_code,
                    'mood_code': mood_code,
                }
            decade_label = decades_label_map.get(decade_code) if decade_code else None
            genre_label = genre_label_map.get(genre_code) if genre_code else None
            if decade_label and genre_label:
                selection_desc = f"Best of {decade_label} {genre_label}"
            elif decade_label:
                selection_desc = f"Best of {decade_label}"
            elif genre_label:
                selection_desc = f"Best of {genre_label}"
    if not g.GOOGLE_API_KEY:
        gemini_recs['error'] = 'GOOGLE_API_KEY is not set in the environment.'
    elif top_shows or top_movies or mode == 'custom':
        import json as pyjson
        if mode == 'history':
            prompt = (
            "You are generating recommendations for a single, specific user. Treat this as a brand-new, stateless request. "
            "Ignore any prior conversation or memory. Do not carry information across users or calls.\n"
            f"User's top watched shows: {top_shows}\n"
            f"User's top watched movies: {top_movies}\n"
            f"User's recent shows (last 10, newest first): {last10_shows}\n"
            f"User's recent movies (last 10, newest first): {last10_movies}\n"
            f"Already watched shows (unique by recency, included {len(watched_shows_in_prompt)} of {len(watched_shows_unique)}): {watched_shows_in_prompt}\n"
            f"Already watched movies (unique by recency, included {len(watched_movies_in_prompt)} of {len(watched_movies_unique)}): {watched_movies_in_prompt}\n"
            "Instructions:\n"
            "- Recommend only items the user has NOT watched. Recommendations cannot be items that are in this prompt. \n"
            "- Base suggestions strictly on this user's data above; avoid generic/global-popularity picks unless they clearly match the user's profile.\n"
            "- Enforce diversity: do NOT cluster around a single director/franchise/genre. Limit to max 2 items per director or franchise/universe, max 3 per genre, and ensure at least 6 distinct genres across the 40 total picks.\n"
            "- Spread across time and regions when relevant: include a mix of decades, countries/languages, and mainstream vs. lesser-known titles—while still aligned to the user's tastes.\n"
            "- Personalize to the user's top and recent viewing, but replace over-concentrated picks with adjacent-yet-diverse alternatives that fit the user's profile.\n"
            "- Do not rely on any memory across requests; each call is independent.\n"
            "Output:\n"
            "- 20 shows and 20 movies the user would most enjoy next.\n"
            "- 5–12 high-level categories/genres/styles inferred from the user's tastes (e.g., 'Game shows', 'British comedy', 'Sketch comedy', 'Medical Drama').\n"
            "Requirements for each show/movie object: MUST include integer 'year' (first release year) AND 'tmdb_id' (TheMovieDB numeric id or null if unknown). May include 'director' and 'genres'.\n"
            "Return ONLY JSON in this exact format (no prose). Example format: "
            '{"shows": [{"title": "...", "year": 2020, "tmdb_id": 123, "director": "...", "genres": ["..."]}, ...], "movies": [{"title": "...", "year": 2020, "tmdb_id": 456, "director": "...", "genres": ["..."]}, ...], "categories": ["..."]}'
            )
        elif mode == 'custom' and mood_code:
            # Mood-based prompt generation
            mood_prompts = {
                'underrated': (
                    "You are discovering hidden gems and underrated content for this user.\n"
                    "Focus on lesser-known, cult classics, indie productions, foreign films, and overlooked titles that deserve more recognition.\n"
                    "Avoid mainstream blockbusters or widely popular series. Look for critically acclaimed but commercially underappreciated content.\n"
                    "Consider international cinema, festival favorites, early works by now-famous creators, and niche genre standouts."
                ),
                'surprise': (
                    "You are creating surprising, eclectic recommendations that will catch this user off-guard in the best way.\n"
                    "Deliberately venture outside their usual patterns while still being quality content they might enjoy.\n"
                    "Mix different decades, countries, styles, and genres. Include some wild cards and unexpected discoveries.\n"
                    "Balance 'safe surprises' (adjacent to their tastes) with 'bold surprises' (completely different but still high-quality)."
                ),
                'comfort_zone': (
                    "You are pushing this user completely outside their viewing comfort zone while still ensuring quality.\n"
                    f"Analyze their viewing patterns from the data above and recommend the OPPOSITE: if they watch a lot of comedy, suggest serious drama; if they prefer recent content, suggest classics; if they stick to English-language, suggest international; if they love action, suggest slow-burn character studies.\n"
                    "The goal is thoughtful expansion of their horizons, not random content. Make it challenging but rewarding."
                ),
                'comfort_food': (
                    "You are recommending feel-good, uplifting, cozy content that provides emotional comfort and warmth.\n"
                    "Focus on wholesome comedies, heartwarming dramas, nostalgic picks, and content with positive vibes.\n"
                    "Think shows/movies that make people feel better about life: found family stories, gentle humor, inspiring tales, cozy mysteries.\n"
                    "This is about emotional nourishment - content that feels like a warm hug after a long day."
                ),
                'award_winners': (
                    "You are recommending critically acclaimed, award-winning content of the highest quality.\n"
                    "Focus on Oscar winners, Emmy winners, Golden Globe recipients, festival darlings, and universally praised content.\n"
                    "Prioritize prestige television, acclaimed international films, and content with critical consensus.\n"
                    "Look for artistic merit, exceptional performances, outstanding writing, and cultural significance."
                ),
                'popular_streaming': (
                    "You are recommending currently trending and popular content across major streaming services.\n"
                    "Focus on what's hot right now: Netflix top 10s, Disney+ hits, HBO Max trending, Amazon Prime favorites, etc.\n"
                    "Include recent releases, viral sensations, award winners, and broadly appealing mainstream content.\n"
                    "This is about cultural zeitgeist and what everyone is talking about."
                ),
                'seasonal': get_seasonal_prompt()
            }
            
            mood_instruction = mood_prompts.get(mood_code, "")
            server_context = ""
            
            prompt = (
                f"You are generating curated recommendations for a single user in mood: {selection_desc}.\n"
                "Treat this as stateless. Do not reuse prior conversations.\n"
                f"User's top watched shows: {top_shows}\n"
                f"User's top watched movies: {top_movies}\n"
                f"User's recent shows (last 10, newest first): {last10_shows}\n"
                f"User's recent movies (last 10, newest first): {last10_movies}\n"
                f"Already watched shows (unique by recency, included {len(watched_shows_in_prompt)} of {len(watched_shows_unique)}): {watched_shows_in_prompt}\n"
                f"Already watched movies (unique by recency, included {len(watched_movies_in_prompt)} of {len(watched_movies_unique)}): {watched_movies_in_prompt}\n"
                f"{server_context}"
                "Instructions:\n"
                f"- {mood_instruction}\n"
                "- Produce 20 shows and 20 movies the user has NOT watched. Recommendations cannot be items that are in this prompt.\n"
                "- Maintain quality: even if pushing boundaries, ensure recommended content is well-made and engaging.\n"
                "- Maintain diversity: max 2 per director/franchise, max 3 per genre tag, at least 6 distinct genres overall.\n"
                "- Replace any watched or duplicate picks with fresh alternatives that still satisfy the mood.\n"
                "Each show/movie object MUST include integer 'year' (first release) AND 'tmdb_id' (TheMovieDB numeric id). If unknown set tmdb_id to null explicitly. Include optional 'director' and 'genres'.\n"
                "Output strictly JSON. Return ONLY JSON in format: {\"shows\": [{\"title\":\"...\",\"year\":2022,\"tmdb_id\":123}], \"movies\": [{\"title\":\"...\",\"year\":1999,\"tmdb_id\":456}], \"categories\": [\"...\"]}"
            )
        else:
            # Custom mode prompt building (decade/genre)
            # Determine filters
            decade_clause = ''
            decade_range = None
            if decade_code:
                if decade_code == 2020:
                    decade_range = (2020, 2100)
                else:
                    decade_range = (decade_code, decade_code + 9)
                decade_clause = f" Focus primarily on titles first released between {decade_range[0]} and {decade_range[1]}."
            genre_clause = ''
            if genre_code:
                genre_label = genre_label_map.get(genre_code, genre_code)
                genre_clause = f" Emphasize the {genre_label} genre (or strong {genre_label} elements) while allowing adjacent subgenres for variety."
            selection_clause = selection_desc or 'Best of selection'
            prompt = (
                f"You are generating curated recommendations for a single user in a special mode: {selection_clause}.\n"
                "Treat this as stateless. Do not reuse prior conversations.\n"
                f"User's top watched shows: {top_shows}\n"
                f"User's top watched movies: {top_movies}\n"
                f"User's recent shows (last 10, newest first): {last10_shows}\n"
                f"User's recent movies (last 10, newest first): {last10_movies}\n"
                f"Already watched shows (unique by recency, included {len(watched_shows_in_prompt)} of {len(watched_shows_unique)}): {watched_shows_in_prompt}\n"
                f"Already watched movies (unique by recency, included {len(watched_movies_in_prompt)} of {len(watched_movies_unique)}): {watched_movies_in_prompt}\n"
                "Instructions:\n"
                "- Produce 20 shows and 20 movies the user has NOT watched. Recommendations cannot be items that are in this prompt.\n"
                "- Weight constraints: 40% influenced by the user's historical tastes (themes, tone, pacing) and 60% by the curated selection target (decade/genre filters).\n"
                f"-{decade_clause}{genre_clause}\n"
                "- Favor a mix of canonical standouts and under-the-radar picks within the selection scope.\n"
                "- Maintain diversity: max 2 per director/franchise, max 3 per genre tag you output, at least 6 distinct genres overall if feasible.\n"
                "- Replace any watched or duplicate picks with fresh alternatives that still satisfy selection constraints.\n"
                "- If one of decade or genre is omitted, treat the other as 'best of' and broaden the omitted dimension intelligently.\n"
                "- If both provided, tightly align with both while still ensuring variety.\n"
                "Each show/movie object MUST include integer 'year' (first release) AND 'tmdb_id' (TheMovieDB numeric id). If unknown set tmdb_id to null explicitly. Include optional 'director' and 'genres'.\n"
                "Output strictly JSON. Return ONLY JSON in format: {\"shows\": [{\"title\":\"...\",\"year\":2022,\"tmdb_id\":123}], \"movies\": [{\"title\":\"...\",\"year\":1999,\"tmdb_id\":456}], \"categories\": [\"...\"]}"
            )
        gemini_recs['prompt'] = prompt
        # Log prompt with requesting IP for debugging/auditing
        try:
            from flask import request as _rqp
            ip_dbg = None
            if _rqp:
                xf2 = _rqp.headers.get('X-Forwarded-For') or _rqp.headers.get('X-Real-IP')
                if xf2:
                    ip_dbg = xf2.split(',')[0].strip()
                if not ip_dbg:
                    ip_dbg = _rqp.remote_addr
        except Exception:
            pass
        if getattr(g, 'genai_sdk', None) == 'new':
            # Try a shortlist of commonly available models with the new google-genai SDK
            # Preferred model order. Allow override via GEMINI_MODEL (.env) and prioritize requested 2.5 flash lite.
            default_order = ['gemini-2.5-flash-lite', 'gemini-2.0-flash-001']
            if getattr(g, 'GEMINI_MODEL', ''):
                # Put user-specified model first if provided.
                user_model = g.GEMINI_MODEL
                # Ensure no duplicates while preserving order.
                tried_models = [user_model] + [m for m in default_order if m != user_model]
            else:
                tried_models = default_order
            gemini_recs['available_models'] = tried_models
            client = getattr(g, 'genai_client', None)
            last_err = None
            if client is None:
                gemini_recs['error'] = 'GenAI client not initialized.'
            else:
                for model_name in tried_models:
                    try:
                        response = client.models.generate_content(model=model_name, contents=prompt)
                        content = getattr(response, 'text', None)
                        gemini_recs['raw_response'] = content
                        # Capture model and usage metadata when available
                        gemini_recs['model_used'] = model_name
                        usage_meta = getattr(response, 'usage_metadata', None)
                        usage = None
                        if usage_meta is not None:
                            if isinstance(usage_meta, dict):
                                usage = usage_meta
                            else:
                                # Best-effort extraction of token counts
                                try:
                                    usage = {
                                        'prompt_token_count': getattr(usage_meta, 'prompt_token_count', None),
                                        'candidates_token_count': getattr(usage_meta, 'candidates_token_count', None),
                                        'total_token_count': getattr(usage_meta, 'total_token_count', None),
                                    }
                                except Exception:
                                    try:
                                        usage = usage_meta.__dict__
                                    except Exception:
                                        usage = None
                        gemini_recs['usage'] = usage
                        rec_json = extract_json_object(content)
                        gemini_recs['parsed_json'] = rec_json
                        if not rec_json:
                            raise ValueError('No JSON found in Gemini response')
                        ai_recommended = pyjson.loads(rec_json)
                        cats = ai_recommended.get('categories', []) or []
                        if cats and isinstance(cats[0], dict):
                            cats = [c.get('name') or c.get('title') or str(c) for c in cats]
                        ai_recommended['categories'] = [c for c in cats if isinstance(c, str)]
                        ut = gemini_recs.get('usage') or {}
                        record_usage(
                            gemini_recs.get('model_used') or model_name,
                            ut.get('prompt_token_count'),
                            ut.get('candidates_token_count'),
                            ut.get('total_token_count'),
                        )
                        # Snapshot today's usage for this model
                        gemini_recs['usage_today'] = get_usage_today(gemini_recs.get('model_used') or model_name)
                        break
                    except Exception as e:
                        last_err = e
                        gemini_recs['error'] = f"Tried model {model_name}: {e}"
                if gemini_recs['error'] and last_err is not None:
                    # Keep the last error for context
                    gemini_recs['error'] = f"Gemini request failed: {last_err}"
        elif getattr(g, 'genai_sdk', None) == 'legacy':
            # Legacy SDK fallback
            try:
                model = genai.GenerativeModel('gemini-pro')
                response = model.generate_content(prompt)
                content = getattr(response, 'text', None)
                gemini_recs['raw_response'] = content
                # Capture model and usage
                gemini_recs['model_used'] = 'gemini-pro'
                usage_meta = getattr(response, 'usage_metadata', None)
                usage = None
                if usage_meta is not None:
                    if isinstance(usage_meta, dict):
                        usage = usage_meta
                    else:
                        try:
                            usage = {
                                'prompt_token_count': getattr(usage_meta, 'prompt_token_count', None),
                                'candidates_token_count': getattr(usage_meta, 'candidates_token_count', None),
                                'total_token_count': getattr(usage_meta, 'total_token_count', None),
                            }
                        except Exception:
                            try:
                                usage = usage_meta.__dict__
                            except Exception:
                                usage = None
                gemini_recs['usage'] = usage
                rec_json = extract_json_object(content)
                gemini_recs['parsed_json'] = rec_json
                if not rec_json:
                    raise ValueError('No JSON found in Gemini response')
                ai_recommended = pyjson.loads(rec_json)
                cats = ai_recommended.get('categories', []) or []
                if cats and isinstance(cats[0], dict):
                    cats = [c.get('name') or c.get('title') or str(c) for c in cats]
                ai_recommended['categories'] = [c for c in cats if isinstance(c, str)]
                gemini_recs['error'] = None
                # Record usage locally for daily tracking
                ut = gemini_recs.get('usage') or {}
                record_usage(
                    gemini_recs.get('model_used') or 'gemini-pro',
                    ut.get('prompt_token_count'),
                    ut.get('candidates_token_count'),
                    ut.get('total_token_count'),
                )
                # Snapshot today's usage for this model
                gemini_recs['usage_today'] = get_usage_today(gemini_recs.get('model_used') or 'gemini-pro')
                gemini_recs['available_models'] = ['gemini-pro']
            except Exception as e:
                gemini_recs['error'] = f"Legacy Gemini request failed: {e}"
    timing['gemini'] = time.time() - t4

    # Step 6: AI parse
    t5 = time.time()
    ai_shows = ai_recommended.get('shows', [])
    ai_movies = ai_recommended.get('movies', [])
    ai_categories = ai_recommended.get('categories', [])
    # Normalize tmdb_id fields (ensure int or None)
    def _norm_tmdb(items):
        if not isinstance(items, list):
            return
        for it in items:
            if not isinstance(it, dict):
                continue
            tid = it.get('tmdb_id')
            if tid in ('', 'null', 'None'):
                it['tmdb_id'] = None
                continue
            if isinstance(tid, (int, float)):
                try:
                    it['tmdb_id'] = int(tid)
                except Exception:
                    it['tmdb_id'] = None
                continue
            if isinstance(tid, str):
                import re as _re
                m = _re.match(r'\d+', tid.strip())
                if m:
                    try:
                        it['tmdb_id'] = int(m.group(0))
                    except Exception:
                        it['tmdb_id'] = None
                else:
                    it['tmdb_id'] = None
    _norm_tmdb(ai_shows)
    _norm_tmdb(ai_movies)
    timing['ai_parse'] = time.time() - t5

    # Step 7: Diversity enforcement (already applied above) + On-demand Plex availability & fuzzy match
    t6 = time.time()
    def _enforce_diversity(items, target_count=20):
        # Items may be dicts with optional 'director' and 'genres' fields.
        # Caps: max 2 per director, max 3 per genre. Preserve order when possible.
        if not items or not isinstance(items[0], dict):
            return items
        dir_cap = 2
        genre_cap = 3
        dir_counts = {}
        genre_counts = {}
        selected = []
        overflow = []
        for it in items:
            d = (it.get('director') or '').strip().lower()
            gs = it.get('genres') or []
            if not isinstance(gs, list):
                gs = [str(gs)] if gs else []
            # Check caps
            dir_ok = True
            if d:
                dir_ok = dir_counts.get(d, 0) < dir_cap
            genres_ok = True
            for gname in gs:
                gkey = str(gname).strip().lower()
                if gkey and genre_counts.get(gkey, 0) >= genre_cap:
                    genres_ok = False
                    break
            if dir_ok and genres_ok and len(selected) < target_count:
                selected.append(it)
                if d:
                    dir_counts[d] = dir_counts.get(d, 0) + 1
                for gname in gs:
                    gkey = str(gname).strip().lower()
                    if gkey:
                        genre_counts[gkey] = genre_counts.get(gkey, 0) + 1
            else:
                overflow.append(it)
        # If we couldn't fill up to target_count, append from overflow (best-effort)
        for it in overflow:
            if len(selected) >= target_count:
                break
            selected.append(it)
        return selected

    # Apply diversity caps if metadata present
    try:
        if ai_shows and isinstance(ai_shows[0], dict):
            ai_shows = _enforce_diversity(ai_shows, target_count=20)
        if ai_movies and isinstance(ai_movies[0], dict):
            ai_movies = _enforce_diversity(ai_movies, target_count=20)
    except Exception:
        pass

    # Pre-step: derive years & accurate TMDb IDs from TMDb (ignore/override any AI-provided tmdb_id for accuracy)
    # Build year maps from AI items once (used for pre-ID resolution AND later poster fetch)
    ai_show_years = {}
    ai_movie_years = {}
    try:
        for it in ai_shows:
            if isinstance(it, dict):
                t = it.get('title'); y = it.get('year')
                if t and isinstance(y, (int, float)):
                    try: ai_show_years[t] = int(y)
                    except Exception: pass
        for it in ai_movies:
            if isinstance(it, dict):
                t = it.get('title'); y = it.get('year')
                if t and isinstance(y, (int, float)):
                    try: ai_movie_years[t] = int(y)
                    except Exception: pass
    except Exception:
        pass
    # Collect raw title lists
    ai_show_titles = [it.get('title') for it in ai_shows if isinstance(it, dict) and it.get('title')] if ai_shows else []
    ai_movie_titles = [it.get('title') for it in ai_movies if isinstance(it, dict) and it.get('title')] if ai_movies else []
    # Pre-resolve posters (fetch_details False) purely to obtain authoritative tmdb_id for every AI item
    pre_show_tmdb = get_posters_for_titles('show', ai_show_titles, ai_show_years, fetch_details=False) if ai_show_titles else []
    pre_movie_tmdb = get_posters_for_titles('movie', ai_movie_titles, ai_movie_years, fetch_details=False) if ai_movie_titles else []
    tmdb_pre_map_shows = {p['title']: p.get('tmdb_id') for p in pre_show_tmdb if p.get('tmdb_id')}
    tmdb_pre_map_movies = {p['title']: p.get('tmdb_id') for p in pre_movie_tmdb if p.get('tmdb_id')}
    # Strip any AI-provided tmdb_ids to avoid trusting hallucinated IDs; we'll overwrite later if needed.
    for it in ai_shows:
        if isinstance(it, dict): it['tmdb_id'] = tmdb_pre_map_shows.get(it.get('title'))
    for it in ai_movies:
        if isinstance(it, dict): it['tmdb_id'] = tmdb_pre_map_movies.get(it.get('title'))

    # Overseerr-based availability using TMDb IDs (preferred)
    overseerr_available_shows = []
    overseerr_available_movies = []
    show_matches = []
    movie_matches = []
    overseerr_errors = []
    overseerr_timing_start = time.time()
    overseerr_url = getattr(g, 'OVERSEERR_URL', '')
    
    # Simple availability cache for this request (TTL: duration of request)
    _availability_cache = {}
    
    def _normalize_overseerr_base(u: str) -> str:
        if not u:
            return ''
        base = u.rstrip('/')
        # If the path does not already contain /api/, append standard segment
        if '/api/' not in base:
            base = base + '/api/v1'
        return base
    overseerr_url = _normalize_overseerr_base(overseerr_url)
    overseerr_key = getattr(g, 'OVERSEERR_API_KEY', '')
    headers_over = {'X-Api-Key': overseerr_key} if overseerr_key else {}

    def _extract_tmdb_id(item):
        if isinstance(item, dict):
            # AI object form
            if 'tmdb_id' in item:
                return item.get('tmdb_id')
            # We may enrich later
        return None

    # Enhanced TMDb ID resolution with fallback passes & debug instrumentation
    tmdb_resolution_events = []
    def _tmdb_search_id(title, year, media_type):
        if not title:
            return None
        try:
            if not getattr(g, 'TMDB_API_KEY', ''):
                tmdb_resolution_events.append({'title': title, 'reason': 'no_api_key'})
                return None
            base = 'https://api.themoviedb.org/3'
            search_endpoint = f"{base}/search/{'movie' if media_type=='movie' else 'tv'}"

            def do_search(q, yr, pass_name):
                params = {'api_key': g.TMDB_API_KEY, 'query': q, 'include_adult': 'false'}
                if isinstance(yr, (int, float)):
                    if media_type == 'movie':
                        params['primary_release_year'] = int(yr)
                    else:
                        params['first_air_date_year'] = int(yr)
                try:
                    r = requests.get(search_endpoint, params=params, timeout=6)
                    if r.status_code != 200:
                        tmdb_resolution_events.append({'title': title, 'pass': pass_name, 'status': r.status_code})
                        return None
                    js = r.json() or {}
                    results = js.get('results') or []
                    tmdb_resolution_events.append({'title': title, 'pass': pass_name, 'results': len(results)})
                    if results:
                        return results[0].get('id')
                except Exception as e:
                    tmdb_resolution_events.append({'title': title, 'pass': pass_name, 'error': str(e)[:120]})
                return None

            # Pass 1: original
            tid = do_search(title, year, 'orig')
            if tid:
                return tid
            # Pass 2: without year
            tid = do_search(title, None, 'no_year')
            if tid:
                return tid
            # Pass 3: sanitized title (remove text after colon / dash / parentheses)
            simplified = title
            for sep in [':', ' -', '(']:
                if sep in simplified:
                    simplified = simplified.split(sep)[0].strip()
            if simplified and simplified.lower() != title.lower():
                tid = do_search(simplified, None, 'simplified')
                if tid:
                    return tid
            # Pass 4: attempt Overseerr search (may return mixed media); only if Overseerr configured
            if overseerr_url and overseerr_key:
                try:
                    oq = simplified or title
                    over_search = f"{overseerr_url}/search?query={requests.utils.quote(oq)}"
                    r2 = requests.get(over_search, headers=headers_over, timeout=6)
                    if r2.status_code == 200:
                        js2 = r2.json() or {}
                        # Overseerr search returns a list or dict; normalize
                        candidates = []
                        if isinstance(js2, list):
                            candidates = js2
                        elif isinstance(js2, dict):
                            candidates = js2.get('results') or []
                        # Filter by mediaType alignment
                        media_key = 'movie' if media_type == 'movie' else 'tv'
                        for c in candidates:
                            if str(c.get('mediaType')) == media_key and c.get('tmdbId'):
                                tmdb_resolution_events.append({'title': title, 'pass': 'overseerr_search', 'hit': True})
                                return c.get('tmdbId')
                        tmdb_resolution_events.append({'title': title, 'pass': 'overseerr_search', 'hit': False, 'cand': len(candidates)})
                except Exception as e:
                    tmdb_resolution_events.append({'title': title, 'pass': 'overseerr_search', 'error': str(e)[:120]})
            tmdb_resolution_events.append({'title': title, 'pass': 'fail'})
        except Exception as e:
            tmdb_resolution_events.append({'title': title, 'pass': 'exception', 'error': str(e)[:120]})
        return None

    _overseerr_debug_samples = []  # capture a few endpoint results
    def _overseerr_available(tmdb_id, media_type, api_url, api_key, error_list):
        """Return tuple(available_bool_or_None, plex_url_present_bool) based on Overseerr lookup.

        Availability rule: Check for PlexUrl presence in mediaInfo to indicate Plex availability.
        """
        # Check cache first
        cache_key = f"{media_type}:{tmdb_id}"
        if cache_key in _availability_cache:
            return _availability_cache[cache_key]
            
        # Debug: log what we're working with
        if not tmdb_id:
            error_list.append(f"_overseerr_available: tmdb_id is None/empty for {media_type}")
            result = (None, False)
            _availability_cache[cache_key] = result
            return result
        if not api_url:
            error_list.append(f"_overseerr_available: api_url is None/empty: '{api_url}'")
            result = (None, False)
            _availability_cache[cache_key] = result
            return result
            
        endpoint = f"{api_url}/{'movie' if media_type=='movie' else 'tv'}/{tmdb_id}"
        
        # Add comprehensive debug logging
        debug_info = {
            'tmdb_id': tmdb_id,
            'media_type': media_type,
            'api_url': api_url,
            'endpoint': endpoint,
            'has_api_key': bool(api_key)
        }
        
        try:
            hdrs = {'X-Api-Key': api_key} if api_key else {}
            r = requests.get(endpoint, headers=hdrs, timeout=8)
            status = r.status_code
            
            debug_info.update({
                'status': status,
                'response_length': len(r.text) if r.text else 0
            })
            
            if status == 404:
                debug_info['result'] = 'not_found'
                if len(_overseerr_debug_samples) < 8:
                    _overseerr_debug_samples.append(debug_info)
                result = (False, False)  # not found -> not available
                _availability_cache[cache_key] = result
                return result
                
            if status != 200:
                debug_info['result'] = f'http_error_{status}'
                debug_info['response_snippet'] = str(r.text)[:300]
                error_list.append(f"_overseerr_available: HTTP {status} for {endpoint}: {r.text[:100]}")
                if len(_overseerr_debug_samples) < 8:
                    _overseerr_debug_samples.append(debug_info)
                result = (None, False)
                _availability_cache[cache_key] = result
                return result
                
            try:
                j = r.json()
            except Exception as json_e:
                debug_info['result'] = 'json_parse_error'
                debug_info['json_error'] = str(json_e)
                error_list.append(f"_overseerr_available: JSON parse error for {endpoint}: {json_e}")
                if len(_overseerr_debug_samples) < 8:
                    _overseerr_debug_samples.append(debug_info)
                result = (None, False)
                _availability_cache[cache_key] = result
                return result
                
            if not isinstance(j, dict):
                debug_info['result'] = 'non_dict_response'
                debug_info['response_type'] = type(j).__name__
                error_list.append(f"_overseerr_available: Non-dict response for {endpoint}")
                if len(_overseerr_debug_samples) < 8:
                    _overseerr_debug_samples.append(debug_info)
                result = (None, False)
                _availability_cache[cache_key] = result
                return result
            
            # Add response structure to debug
            debug_info['response_keys'] = list(j.keys())
            
            # Get mediaInfo
            mi = j.get('mediaInfo')
            debug_info['has_mediaInfo'] = mi is not None
            if isinstance(mi, dict):
                debug_info['mediaInfo_keys'] = list(mi.keys())
            
            # Check for PlexUrl at various levels
            plex_url_checks = {
                'root_PlexUrl': j.get('PlexUrl'),
                'root_plexUrl': j.get('plexUrl'),
                'mediaInfo_PlexUrl': mi.get('PlexUrl') if isinstance(mi, dict) else None,
                'mediaInfo_plexUrl': mi.get('plexUrl') if isinstance(mi, dict) else None,
            }
            debug_info['plex_url_checks'] = plex_url_checks
            
            # Primary rule: plexUrl presence (root OR inside mediaInfo)
            plex_url_val = (plex_url_checks['root_PlexUrl'] or 
                           plex_url_checks['root_plexUrl'] or
                           plex_url_checks['mediaInfo_PlexUrl'] or 
                           plex_url_checks['mediaInfo_plexUrl'])
            
            if plex_url_val:
                debug_info['result'] = 'available_with_plexurl'
                debug_info['plex_url_value'] = str(plex_url_val)[:100]
                if len(_overseerr_debug_samples) < 8:
                    _overseerr_debug_samples.append(debug_info)
                result = (True, True)
                _availability_cache[cache_key] = result
                return result
            
            # Fallback: check mediaInfo status
            if isinstance(mi, dict):
                mi_status = mi.get('status')
                download_status = mi.get('downloadStatus')
                debug_info['mediaInfo_status'] = mi_status
                debug_info['downloadStatus'] = download_status
                
                if mi_status == 4 or str(mi_status).lower() == 'available' or download_status == 1:
                    debug_info['result'] = 'available_by_status'
                    if len(_overseerr_debug_samples) < 8:
                        _overseerr_debug_samples.append(debug_info)
                    result = (True, False)  # available but no explicit PlexUrl field
                    _availability_cache[cache_key] = result
                    return result
            
            # Not available
            debug_info['result'] = 'not_available'
            if len(_overseerr_debug_samples) < 8:
                _overseerr_debug_samples.append(debug_info)
            result = (False, False)
            _availability_cache[cache_key] = result
            return result
            
        except Exception as e:
            debug_info['result'] = 'exception'
            debug_info['exception'] = str(e)
            error_msg = f"_overseerr_available exception for {endpoint}: {str(e)}"
            error_list.append(error_msg)
            if len(_overseerr_debug_samples) < 8:
                _overseerr_debug_samples.append(debug_info)
            result = (None, False)
            _availability_cache[cache_key] = result
            return result

    def _resolve(items, media_type, pre_map):
        results = []
        tmdb_map = {}
        if not items:
            return [], [], {}, 0.0
        
        start_batch = time.time()
        
        # Get Plex client for availability checking
        plex = get_plex_client()
        if plex is None:
            print("Warning: Plex not configured, marking all items as unavailable")
            # If Plex not configured, mark all as unavailable
            for it in items:
                title = it.get('title') if isinstance(it, dict) else it
                year = it.get('year') if isinstance(it, dict) else None
                tmdb_id = pre_map.get(title)
                if not tmdb_id:
                    tmdb_id = _tmdb_search_id(title, year, media_type)
                    if isinstance(it, dict): 
                        it['tmdb_id'] = tmdb_id
                
                results.append({
                    'ai_title': title, 
                    'ai_year': year, 
                    'tmdb_id': tmdb_id, 
                    'plex_available': False, 
                    'plex_url': False
                })
                
                if tmdb_id:
                    tmdb_map[title] = tmdb_id
                    
            available_titles = []
            return results, available_titles, tmdb_map, time.time() - start_batch
        
        # Step 1: Batch check Plex availability for all items
        plex_availability = plex.batch_check_availability(items, media_type)
        
        # Step 2: Process TMDb IDs in batches for items that need them
        items_needing_tmdb = []
        for it in items:
            title = it.get('title') if isinstance(it, dict) else it
            if title and not pre_map.get(title):
                items_needing_tmdb.append(it)
        
        # Resolve TMDb IDs in smaller batches
        if items_needing_tmdb:
            batch_size = 5
            for i in range(0, len(items_needing_tmdb), batch_size):
                batch = items_needing_tmdb[i:i + batch_size]
                for it in batch:
                    title = it.get('title') if isinstance(it, dict) else it
                    year = it.get('year') if isinstance(it, dict) else None
                    tmdb_id = _tmdb_search_id(title, year, media_type)
                    if isinstance(it, dict): 
                        it['tmdb_id'] = tmdb_id
                    if tmdb_id:
                        pre_map[title] = tmdb_id
        
        # Step 3: Build final results
        for it in items:
            title = it.get('title') if isinstance(it, dict) else it
            year = it.get('year') if isinstance(it, dict) else None
            
            # Get TMDb ID
            tmdb_id = pre_map.get(title)
            
            # Get availability from Plex batch results
            plex_avail = plex_availability.get(title, False)
            
            results.append({
                'ai_title': title, 
                'ai_year': year, 
                'tmdb_id': tmdb_id, 
                'plex_available': plex_avail, 
                'plex_url': plex_avail
            })
            
            if tmdb_id:
                tmdb_map[title] = tmdb_id
        
        available_titles = [r['ai_title'] for r in results if r.get('plex_available') and r.get('ai_title') not in watched_set_all]
        return results, available_titles, tmdb_map, time.time() - start_batch

    show_matches, rec_shows, tmdb_map_shows, dur_shows = _resolve(ai_shows, 'show', tmdb_pre_map_shows)
    movie_matches, rec_movies, tmdb_map_movies, dur_movies = _resolve(ai_movies, 'movie', tmdb_pre_map_movies)
    tmdb_map_all = {**tmdb_map_shows, **tmdb_map_movies}
    timing['availability'] = dur_shows + dur_movies
    timing['fuzzy_match'] = timing['availability']  # maintain legacy key
    debug['plex_availability'] = {
        'shows_checked': len(ai_shows),
        'movies_checked': len(ai_movies),
        'shows_available': len(rec_shows),
        'movies_available': len(rec_movies),
        'plex_hits_shows': sum(1 for m in show_matches if m.get('plex_url')),
        'plex_hits_movies': sum(1 for m in movie_matches if m.get('plex_url')),
        'duration_shows': round(dur_shows,3),
        'duration_movies': round(dur_movies,3),
        'duration_total': round(timing['availability'],3),
        'optimization': 'direct_plex_api',
        'plex_configured': get_plex_client() is not None
    }
    # TMDb resolution debug summary
    if tmdb_resolution_events:
        fail_count = sum(1 for e in tmdb_resolution_events if e.get('pass') == 'fail')
        debug['tmdb_resolution'] = {
            'events': tmdb_resolution_events[-50:],  # cap to recent 50 to avoid bloat
            'failures': fail_count,
            'total_events': len(tmdb_resolution_events)
        }
    debug['fuzzy_show_matches'] = show_matches
    debug['fuzzy_movie_matches'] = movie_matches
    plex_available_shows = rec_shows
    plex_available_movies = rec_movies

    # Unavailable items (not in Plex)
    def dedup(seq):
        seen = set(); out = []
        for x in seq:
            if x and x not in seen:
                seen.add(x); out.append(x)
        return out
    ai_shows_unavailable = dedup([m.get('ai_title') for m in show_matches if not m.get('plex_available')])
    ai_movies_unavailable = dedup([m.get('ai_title') for m in movie_matches if not m.get('plex_available')])

    # Step 8: Resolve posters for available recommendations (best-effort)
    t7 = time.time()
    # (Year maps already built earlier.) Include matched library titles years if not present.
    try:
        for m in show_matches:
            y = m.get('ai_year'); mt = m.get('match')
            if mt and isinstance(y, (int, float)) and mt not in ai_show_years:
                try: ai_show_years[mt] = int(y)
                except Exception: pass
        for m in movie_matches:
            y = m.get('ai_year'); mt = m.get('match')
            if mt and isinstance(y, (int, float)) and mt not in ai_movie_years:
                try: ai_movie_years[mt] = int(y)
                except Exception: pass
    except Exception:
        pass
    show_posters = get_posters_for_titles('show', rec_shows, ai_show_years, pre_tmdb_map=tmdb_map_shows)
    movie_posters = get_posters_for_titles('movie', rec_movies, ai_movie_years, pre_tmdb_map=tmdb_map_movies)
    # Also fetch posters for AI recommendations that are not in the library
    show_posters_unavailable = get_posters_for_titles('show', ai_shows_unavailable, ai_show_years, pre_tmdb_map=tmdb_map_shows)
    movie_posters_unavailable = get_posters_for_titles('movie', ai_movies_unavailable, ai_movie_years, pre_tmdb_map=tmdb_map_movies)
    timing['posters'] = time.time() - t7
    # Build a concise source summary for UI
    def _count_sources(items):
        d = {'tmdb': 0}
        for it in items:
            src = it.get('source')
            if src in d:
                d[src] += 1
        return d
    show_src = _count_sources(show_posters)
    movie_src = _count_sources(movie_posters)
    poster_source_summary = None
    total_tmdb = show_src.get('tmdb', 0) + movie_src.get('tmdb', 0)
    poster_source_summary = 'TMDb' if total_tmdb else 'None'

    debug.update({
        'watched_set_count': len(watched_set_all),
        'watched_set_count_recent_window': len(set(shows + movies)),
        'recent_shows': last10_shows,
        'recent_movies': last10_movies,
        'gemini_error': gemini_recs.get('error'),
    'genai_sdk': getattr(g, 'genai_sdk', None),
    'gemini_model_used': gemini_recs.get('model_used'),
    'gemini_usage': gemini_recs.get('usage'),
        'gemini_prompt': gemini_recs.get('prompt'),
        'gemini_raw_response': gemini_recs.get('raw_response'),
        'gemini_parsed_json': gemini_recs.get('parsed_json'),
    'gemini_usage_today': gemini_recs.get('usage_today'),
    'gemini_daily_quota': None,
    'gemini_daily_remaining': None,
        'gemini_ai_shows': ai_shows,
        'gemini_ai_movies': ai_movies,
    'gemini_ai_categories': ai_categories,
    'gemini_ai_shows_available': rec_shows,
    'gemini_ai_movies_available': rec_movies,
        'watched_list_prompt_counts': {
            'shows_total': len(watched_shows_unique),
            'shows_included': len(watched_shows_in_prompt),
            'movies_total': len(watched_movies_unique),
            'movies_included': len(watched_movies_in_prompt),
        },
        'timing': timing
    })
    # Add poster source breakdown to debug for UI
    debug['poster_sources'] = {
        'shows': show_src,
        'movies': movie_src,
        'summary': poster_source_summary,
    }
    # Compute optional quota/remaining using local usage tracker and configured quotas
    try:
        model_used = gemini_recs.get('model_used')
        if model_used and isinstance(getattr(g, 'GEMINI_DAILY_QUOTAS', {}), dict):
            qmap = getattr(g, 'GEMINI_DAILY_QUOTAS', {})
            quota = qmap.get(model_used)
            if isinstance(quota, (int, float)):
                usage_today = gemini_recs.get('usage_today') or {}
                calls_today = int((usage_today or {}).get('calls') or 0)
                remaining = max(int(quota) - calls_today, 0)
                debug['gemini_daily_quota'] = int(quota)
                debug['gemini_daily_remaining'] = remaining
    except Exception:
        pass
    try:
        # Build ordered summary with total first; format to 2 decimals
        total_time = 0.0
        for _k,_v in timing.items():
            try:
                total_time += float(_v)
            except Exception:
                pass
        formatted = {k: (f"{float(v):.2f}" if isinstance(v,(int,float)) else v) for k,v in timing.items()}
        timing_summary = {'total': f"{total_time:.2f}"}
        timing_summary.update(formatted)
        print('DEBUG: final timing:', timing_summary)
    except Exception:
        print('DEBUG: final timing (raw fallback):', timing)

    # Convenience title lists for template rendering
    # Extract simple title lists plus year maps for display
    ai_shows_titles = []
    ai_movies_titles = []
    ai_show_years_template = {}
    ai_movie_years_template = {}
    for it in ai_shows:
        if isinstance(it, dict):
            tt = it.get('title')
            if tt: ai_shows_titles.append(tt)
            y = it.get('year')
            if tt and isinstance(y, (int, float)):
                try: ai_show_years_template[tt] = int(y)
                except Exception: pass
        else:
            ai_shows_titles.append(it)
    for it in ai_movies:
        if isinstance(it, dict):
            tt = it.get('title')
            if tt: ai_movies_titles.append(tt)
            y = it.get('year')
            if tt and isinstance(y, (int, float)):
                try: ai_movie_years_template[tt] = int(y)
                except Exception: pass
        else:
            ai_movies_titles.append(it)
    # Augment template year maps with matched library titles (same logic as earlier)
    for m in show_matches:
        y = m.get('ai_year')
        mt = m.get('match')
        if mt and isinstance(y, (int, float)) and mt not in ai_show_years_template:
            try: ai_show_years_template[mt] = int(y)
            except Exception: pass
    for m in movie_matches:
        y = m.get('ai_year')
        mt = m.get('match')
        if mt and isinstance(y, (int, float)) and mt not in ai_movie_years_template:
            try: ai_movie_years_template[mt] = int(y)
            except Exception: pass

    result = {
        'user_id': user_id,
        'shows': rec_shows,
        'movies': rec_movies,
        'top_shows': top_shows,
        'top_movies': top_movies,
        'ai_shows': ai_shows,
        'ai_movies': ai_movies,
    'ai_categories': ai_categories,
        'ai_shows_titles': ai_shows_titles,
        'ai_movies_titles': ai_movies_titles,
    'ai_show_years': ai_show_years_template,
    'ai_movie_years': ai_movie_years_template,
    'ai_shows_unavailable': ai_shows_unavailable,
    'ai_movies_unavailable': ai_movies_unavailable,
        'ai_shows_available': rec_shows,
        'ai_movies_available': rec_movies,
    'history_count': len(hist_all),
    'show_posters': show_posters,
    'movie_posters': movie_posters,
    'show_posters_unavailable': show_posters_unavailable,
    'movie_posters_unavailable': movie_posters_unavailable,
        'debug': debug
    }
    if mode == 'custom':
        result['selection_desc'] = selection_desc
    result['mode'] = mode
    result['decade_code'] = decade_code
    result['genre_code'] = genre_code
    return result



# Simple in-process cache for TMDb keyword id lookups (category -> keyword id or None)
_KEYWORD_ID_CACHE = {}

def tmdb_keyword_id(term: str) -> int | None:
    """Resolve a free-form category term to a TMDb keyword id using /search/keyword.
    Caches results (including misses) in-memory for the process lifetime."""
    if not term or not getattr(g, 'TMDB_API_KEY', ''):
        return None
    key = term.strip().lower()
    if key in _KEYWORD_ID_CACHE:
        return _KEYWORD_ID_CACHE[key]
    try:
        resp = requests.get(
            'https://api.themoviedb.org/3/search/keyword',
            params={'api_key': g.TMDB_API_KEY, 'query': term, 'page': 1}, timeout=6
        )
        js = resp.json() if resp.status_code == 200 else {}
        results = js.get('results') or []
        if not results:
            _KEYWORD_ID_CACHE[key] = None
            return None
        # Pick best fuzzy match
        target_norm = normalize_title(term)
        def _score(r):
            name = r.get('name') or ''
            return fuzz.token_sort_ratio(target_norm, normalize_title(name))
        best = sorted(results, key=_score, reverse=True)[0]
        score = _score(best)
        if score < 55:  # too weak
            _KEYWORD_ID_CACHE[key] = None
            return None
        kid = best.get('id')
        if isinstance(kid, int):
            _KEYWORD_ID_CACHE[key] = kid
            return kid
    except Exception:
        pass
    _KEYWORD_ID_CACHE[key] = None
    return None

def overseerr_keyword_id(term: str) -> int | None:
    """Resolve a free-form category term to a keyword id using Overseerr's API.
    Caches results (including misses) in-memory for the process lifetime."""
    if not term or not getattr(g, 'OVERSEERR_URL', ''):
        return None
    
    key = term.strip().lower()
    if key in _KEYWORD_ID_CACHE:
        return _KEYWORD_ID_CACHE[key]
    
    overseerr_url = getattr(g, 'OVERSEERR_URL', '').rstrip('/')
    overseerr_key = getattr(g, 'OVERSEERR_API_KEY', '')
    
    if not overseerr_url:
        _KEYWORD_ID_CACHE[key] = None
        return None
    
    try:
        # Use Overseerr's keyword search endpoint
        headers = {}
        if overseerr_key:
            headers['X-API-Key'] = overseerr_key
        
        resp = requests.get(
            f"{overseerr_url}/api/v1/search/keyword",
            params={'query': term, 'page': 1},
            headers=headers,
            timeout=6
        )
        
        if resp.status_code != 200:
            _KEYWORD_ID_CACHE[key] = None
            return None
            
        js = resp.json()
        results = js.get('results', [])
        
        if not results:
            _KEYWORD_ID_CACHE[key] = None
            return None
        
        # Pick best fuzzy match
        target_norm = normalize_title(term)
        def _score(r):
            name = r.get('name', '')
            return fuzz.token_sort_ratio(target_norm, normalize_title(name))
        
        best = sorted(results, key=_score, reverse=True)[0]
        score = _score(best)
        
        if score < 55:  # too weak match
            _KEYWORD_ID_CACHE[key] = None
            return None
        
        kid = best.get('id')
        if isinstance(kid, int):
            _KEYWORD_ID_CACHE[key] = kid
            return kid
            
    except Exception:
        pass
    
    _KEYWORD_ID_CACHE[key] = None
    return None

def get_all_library_items(media_type, debug_accum=None):
    # Deprecated: full library inventory now resolved on-demand via Plex during matching.
    if debug_accum is not None:
        debug_accum.setdefault('deprecated_calls', []).append(f'get_all_library_items:{media_type}')
    return []

def lookup_user_by_identifier(identifier):
    """
    Lookup user by email, username, or friendly_name.
    Returns user dict if found, None otherwise.
    """
    users = get_cached_users()
    if not users:
        return None
    
    low = identifier.lower()
    match = None
    
    # Exact match against username/email first
    for u in users:
        uname = str(u.get('username') or '').lower()
        email = str(u.get('email') or '').lower()
        if (uname and low == uname) or (email and low == email):
            match = u
            break
    
    # Relaxed contains match (beginning match) if exact not found
    if not match:
        for u in users:
            uname = str(u.get('username') or '').lower()
            email = str(u.get('email') or '').lower()
            if (uname and uname.startswith(low)) or (email and email.startswith(low)):
                match = u
                break
    
    # Friendly name exact match
    if not match:
        for u in users:
            fname = str(u.get('friendly_name') or '').lower()
            if fname and low == fname:
                match = u
                break
    
    # As a last resort, refresh users once more via API to capture recent changes
    if not match:
        try:
            params = {'apikey': g.TAUTULLI_API_KEY, 'cmd': 'get_users'}
            resp = requests.get(f"{g.TAUTULLI_URL}/api/v2", params=params, timeout=5)
            data = resp.json()
            payload = data.get('response', {}).get('data', [])
            api_users = []
            if isinstance(payload, list):
                api_users = payload
            elif isinstance(payload, dict):
                if isinstance(payload.get('users'), list):
                    api_users = [u for u in payload['users'] if u.get('is_active', True)]
                elif isinstance(payload.get('data'), list):
                    api_users = payload['data']
            
            for u in api_users:
                uname = str(u.get('username') or '').lower()
                email = str(u.get('email') or '').lower()
                if (uname and low == uname) or (email and low == email):
                    match = u
                    break
                if (uname and uname.startswith(low)) or (email and email.startswith(low)):
                    match = u
                    break
        except Exception:
            pass
    
    return match


def get_current_holiday_season():
    """
    Determine current holiday season based on date proximity to Halloween and Christmas.
    
    Returns:
        str: 'halloween' for Halloween season, 'christmas' for Christmas season
    
    Rules:
    - Halloween: Oct 1 - Nov 7 (30 days before + 7 days after Oct 31)
    - Christmas: Nov 25 - Feb 1 (30 days before + extended through Feb 1)
    - If outside both windows, return nearest upcoming holiday
    """
    today = date.today()
    current_year = today.year
    
    # Define holiday dates for current year
    halloween = date(current_year, 10, 31)
    christmas = date(current_year, 12, 25)
    
    # Define holiday windows
    halloween_start = date(current_year, 10, 1)  # Oct 1 (30 days before)
    halloween_end = date(current_year, 11, 7)    # Nov 7 (7 days after)
    
    christmas_start = date(current_year, 11, 25) # Nov 25 (30 days before)
    christmas_end = date(current_year + 1, 2, 1) # Feb 1 next year
    
    # Check if we're in Halloween season
    if halloween_start <= today <= halloween_end:
        return 'halloween'
    
    # Check if we're in Christmas season
    if today >= christmas_start or today <= date(current_year, 2, 1):
        return 'christmas'
    
    # If outside both windows, determine nearest upcoming holiday
    if today < halloween_start:
        # Before Halloween season, Halloween is next
        return 'halloween'
    elif halloween_end < today < christmas_start:
        # Between Halloween and Christmas, Christmas is next
        return 'christmas'
    else:
        # After Christmas (Feb 2 - Sep 30), Halloween is next
        return 'halloween'


def get_seasonal_prompt():
    """
    Generate seasonal mood prompt based on current holiday season.
    """
    holiday_season = get_current_holiday_season()
    
    if holiday_season == 'halloween':
        return (
            "You are recommending spooky, Halloween-themed content that captures the spirit of the season.\n"
            "Focus on horror classics, supernatural thrillers, monster movies, ghost stories, and atmospheric scary content.\n"
            "Prioritize Halloween-specific films and shows over general horror - think content that's quintessentially 'Halloween viewing'.\n"
            "Include both modern and classic horror, but lean toward iconic Halloween favorites and seasonal traditions.\n"
            "Consider family-friendly spooky content alongside more intense horror, but emphasize the Halloween atmosphere."
        )
    else:  # christmas
        return (
            "You are recommending Christmas and holiday-themed content that captures the warmth and spirit of the season.\n"
            "Focus on Christmas movies, holiday specials, winter-themed stories, and festive family content.\n"
            "Include classic Christmas films, holiday comedies, heartwarming seasonal stories, and feel-good winter content.\n"
            "Think content that embodies holiday traditions, family gatherings, seasonal magic, and Christmas spirit.\n"
            "Consider both traditional Christmas classics and modern holiday favorites that people watch during the season."
        )


@app.route('/recommendations')
def recommendations():
    # Get parameters
    user_id = request.args.get('user_id')
    user = request.args.get('user')  # email/username alternative
    mode = request.args.get('mode', 'history').lower()
    decade = request.args.get('decade')
    genre = request.args.get('genre')
    mood = request.args.get('mood')
    format_type = request.args.get('format', 'json').lower()
    
    # User lookup - support both user_id and user parameters
    if user_id:
        # Direct user_id provided
        selected_user_id = user_id
    elif user:
        # Email/username lookup
        match = lookup_user_by_identifier(user)
        if not match:
            return jsonify({'error': f'User not found: {user}'}), 400
        selected_user_id = str(match.get('user_id'))
    else:
        return jsonify({'error': 'Either user_id or user parameter required'}), 400
    
    # Validate mode
    if mode not in ['history', 'custom']:
        return jsonify({'error': 'mode must be "history" or "custom"'}), 400
    
    # Parse decade parameter  
    decade_code = None
    if decade:
        # Support both decade names and numbers
        decade_mapping = {
            '1950s': 1950, '1950': 1950,
            '1960s': 1960, '1960': 1960, 
            '1970s': 1970, '1970': 1970,
            '1980s': 1980, '1980': 1980,
            '1990s': 1990, '1990': 1990,
            '2000s': 2000, '2000': 2000,
            '2010s': 2010, '2010': 2010,
            '2020s': 2020, '2020': 2020, '2020 now': 2020, '2020-now': 2020
        }
        decade_code = decade_mapping.get(decade.lower())
        if decade_code is None:
            return jsonify({'error': f'Invalid decade: {decade}. Valid options: 1950s-2020s'}), 400
    
    # Parse genre parameter
    genre_code = None
    if genre:
        # Genre mapping from the app
        genre_mapping = {
            'action': 'action', 'drama': 'drama', 'comedy': 'comedy', 'sci-fi': 'scifi', 'scifi': 'scifi',
            'horror': 'horror', 'thriller': 'thriller', 'documentary': 'documentary', 'animation': 'animation',
            'family': 'family', 'fantasy': 'fantasy', 'romance': 'romance', 'crime': 'crime', 'mystery': 'mystery',
            'adventure': 'adventure', 'war': 'war', 'western': 'western', 'musical': 'musical',
            'biography': 'biography', 'history': 'history', 'sports': 'sports'
        }
        genre_code = genre_mapping.get(genre.lower())
        if genre_code is None:
            valid_genres = list(set(genre_mapping.keys()))
            return jsonify({'error': f'Invalid genre: {genre}. Valid options: {", ".join(sorted(valid_genres))}'}), 400
    
    # Parse mood parameter
    mood_code = None
    if mood:
        mood_mapping = {
            'underrated': 'underrated',
            'surprise me': 'surprise', 'surprise': 'surprise',
            'out of my comfort zone': 'comfort_zone', 'comfort zone': 'comfort_zone', 'comfort_zone': 'comfort_zone',
            'comfort food': 'comfort_food', 'comfort_food': 'comfort_food',
            'award winners': 'award_winners', 'award_winners': 'award_winners',
            'popular (streaming services)': 'popular_streaming', 'popular streaming': 'popular_streaming', 'popular_streaming': 'popular_streaming',
            'seasonal': 'seasonal'
        }
        mood_code = mood_mapping.get(mood.lower())
        if mood_code is None:
            valid_moods = ['underrated', 'surprise me', 'out of my comfort zone', 'comfort food', 'award winners', 'popular (streaming services)', 'seasonal']
            return jsonify({'error': f'Invalid mood: {mood}. Valid options: {", ".join(valid_moods)}'}), 400
    
    # Validate custom mode requirements
    if mode == 'custom':
        if mood_code:
            # Mood mode - decade and genre are ignored
            pass
        elif not decade_code and not genre_code:
            return jsonify({'error': 'Custom mode requires at least one of: decade, genre, mood'}), 400
    
    # Validate format
    if format_type not in ['json', 'html']:
        return jsonify({'error': 'format must be "json" or "html"'}), 400
    
    # Generate recommendations
    try:
        recs = recommend_for_user(selected_user_id, mode=mode, decade_code=decade_code, genre_code=genre_code, mood_code=mood_code)
        
        if format_type == 'html':
            # Return HTML format using the mobile template for API consumers
            from flask import render_template
            return render_template('mobile.html', 
                                 recs=recs, 
                                 user_id=selected_user_id,
                                 mode=mode,
                                 decade_selected=decade_code,
                                 genre_selected=genre_code,
                                 mood_selected=mood_code)
        else:
            # Return JSON format (default)
            return jsonify(recs)
            
    except Exception as e:
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500





@app.route('/', methods=['GET', 'POST'])
def index():
    global TAUTULLI_URL, TAUTULLI_API_KEY, GOOGLE_API_KEY, settings
    # Check for missing settings
    missing = []
    if not g.PLEX_URL:
        missing.append('PLEX_URL')
    if not g.PLEX_TOKEN:
        missing.append('PLEX_TOKEN')
    if not g.GOOGLE_API_KEY:
        missing.append('GOOGLE_API_KEY')
    if missing:
        # In user mode, settings are hidden; don't redirect to settings.
        if not getattr(g, 'USER_MODE', False):
            return redirect(url_for('settings_page'))
    users = get_cached_users()
    user_id = None
    selected_user = None
    recs = None
    debug_info = {}
    user_login_error = None
    # Form selection memory
    form_mode = 'history'
    form_decade = None
    form_genre = None
    form_mood = None
    user_login_value = None
    # Library status UI removed; automatic caching handled in get_all_library_items. We still
    # expose a simple loading overlay if cache is cold (detected lazily in template JS via data attribute).
    show_loading = False
    loading_message = None
    show_status_only = ''
    movie_status_only = ''
    library_status = ''
    if users:
        if getattr(g, 'USER_MODE', False):
            # User mode: require a login by Plex email/username (or friendly_name as fallback)
            if request.method == 'POST':
                form_mode = (request.form.get('mode') or 'history').strip()
                form_decade = request.form.get('decade') or None
                form_genre = request.form.get('genre') or None
                form_mood = request.form.get('mood') or None
                # Ensure empty strings are treated as None
                if form_decade == '': form_decade = None
                if form_genre == '': form_genre = None
                if form_mood == '': form_mood = None
                user_login = (request.form.get('user_login') or '').strip()
                user_login_value = user_login
                if not user_login:
                    user_login_error = 'Please enter your Plex email or username.'
                else:
                    low = user_login.lower()
                    match = None
                    # Exact match against username/email first
                    for u in users:
                        uname = str(u.get('username') or '').lower()
                        email = str(u.get('email') or '').lower()
                        if (uname and low == uname) or (email and low == email):
                            match = u
                            break
                    # Relaxed contains match (beginning match) if exact not found
                    if not match:
                        for u in users:
                            uname = str(u.get('username') or '').lower()
                            email = str(u.get('email') or '').lower()
                            if (uname and uname.startswith(low)) or (email and email.startswith(low)):
                                match = u
                                break
                    if not match:
                        for u in users:
                            fname = str(u.get('friendly_name') or '').lower()
                            if fname and low == fname:
                                match = u
                                break
                    # As a last resort, if still not found, refresh users once more via API to capture recent changes
                    if not match:
                        try:
                            params = {'apikey': g.TAUTULLI_API_KEY, 'cmd': 'get_users'}
                            resp = requests.get(f"{g.TAUTULLI_URL}/api/v2", params=params, timeout=5)
                            data = resp.json()
                            payload = data.get('response', {}).get('data', [])
                            api_users = []
                            if isinstance(payload, list):
                                api_users = payload
                            elif isinstance(payload, dict):
                                if isinstance(payload.get('users'), list):
                                    api_users = [u for u in payload['users'] if u.get('is_active', True)]
                                elif isinstance(payload.get('data'), list):
                                    api_users = payload['data']
                            for u in api_users:
                                uname = str(u.get('username') or '').lower()
                                email = str(u.get('email') or '').lower()
                                if (uname and low == uname) or (email and low == email):
                                    match = u
                                    break
                                if (uname and uname.startswith(low)) or (email and email.startswith(low)):
                                    match = u
                                    break
                        except Exception:
                            pass
                    if match:
                        selected_user = match
                        user_id = str(match.get('user_id'))
                        # Convert decade to int if provided
                        decade_int = None
                        if form_decade and form_decade.isdigit():
                            try:
                                decade_int = int(form_decade)
                            except Exception:
                                decade_int = None
                        # Prevent custom mode with no filters
                        if form_mode == 'custom' and not (form_decade or form_genre or form_mood):
                            recs = None
                            debug_info['error'] = f'No filters selected. Received - decade: "{form_decade}", genre: "{form_genre}", mood: "{form_mood}"'
                        else:
                            refresh_user_cache_if_changed()
                            recs = recommend_for_user(user_id, mode=form_mode, decade_code=decade_int, genre_code=(form_genre or None), mood_code=form_mood)
                            if recs['history_count'] == 0:
                                debug_info['note'] = 'No watch history found for this user.'
                    else:
                        user_login_error = 'User not found. Check your Plex email or username.'
            # No auto-select default on GET in user mode
        else:
            if request.method == 'POST':
                user_id = request.form.get('user_id')
                form_mode = (request.form.get('mode') or 'history').strip()
                form_decade = request.form.get('decade') or None
                form_genre = request.form.get('genre') or None
                form_mood = request.form.get('mood') or None
                # Ensure empty strings are treated as None
                if form_decade == '': form_decade = None
                if form_genre == '': form_genre = None
                if form_mood == '': form_mood = None
            else:
                user_id = request.args.get('user_id')
                form_mode = (request.args.get('mode') or 'history').strip()
                form_decade = request.args.get('decade') or None
                form_genre = request.args.get('genre') or None
                form_mood = request.args.get('mood') or None
            if not user_id:
                user_id = str(users[0].get('user_id'))
            selected_user = next((u for u in users if str(u.get('user_id')) == str(user_id)), users[0])
            if request.method == 'POST':
                decade_int = None
                if form_decade and form_decade.isdigit():
                    try:
                        decade_int = int(form_decade)
                    except Exception:
                        decade_int = None
                # Prevent custom mode with no filters
                if form_mode == 'custom' and not (form_decade or form_genre or form_mood):
                    recs = None
                    debug_info['error'] = f'No filters selected. Received - decade: "{form_decade}", genre: "{form_genre}", mood: "{form_mood}"'
                else:
                    refresh_user_cache_if_changed()
                    recs = recommend_for_user(user_id, mode=form_mode, decade_code=decade_int, genre_code=(form_genre or None), mood_code=form_mood)
                    if recs['history_count'] == 0:
                        debug_info['note'] = 'No watch history found for this user.'
    else:
        debug_info['error'] = 'No users found or unable to connect to Tautulli.'
    # Choose mobile template for user mode on mobile UAs, else desktop
    ua = request.headers.get('User-Agent', '') or ''
    is_mobile = False
    try:
        _ua = ua.lower()
        is_mobile = any(tok in _ua for tok in ['iphone', 'android', 'ipad', 'ipod', 'mobile'])
    except Exception:
        is_mobile = False
    # Manual override via query param (?mobile=1 or ?mobile=0)
    override_mobile = request.args.get('mobile') or request.form.get('mobile')
    if override_mobile is not None:
        try:
            ov = str(override_mobile).strip().lower()
            if ov in ('1', 'true', 'yes', 'y', 'on', 'mobile'):
                is_mobile = True
            elif ov in ('0', 'false', 'no', 'n', 'off', 'desktop'):
                is_mobile = False
        except Exception:
            pass
    template_name = 'table.html'
    if getattr(g, 'USER_MODE', False) and is_mobile:
        template_name = 'mobile.html'
    # Detect if the request is coming from localhost
    is_localhost = _is_request_localhost(request)
    # Build desktop config status panel data (no secrets displayed) shown in both user & admin modes
    user_config_status = []
    if not is_mobile:
        def _add_status(label, ok):
            user_config_status.append({'name': label, 'ok': bool(ok)})
        import re as _re
        def _is_url(u):
            try:
                return bool(u and _re.match(r'^https?://', u))
            except Exception:
                return False
        _add_status('Tautulli URL', _is_url(getattr(g, 'TAUTULLI_URL', '')))
        _add_status('Tautulli API Key', bool(getattr(g, 'TAUTULLI_API_KEY', '')))
        db_path = getattr(g, 'TAUTULLI_DB_PATH', '')
        _add_status('Tautulli DB (optional)', bool(db_path and os.path.exists(db_path)))
        
        # Plex connection status
        plex_url = getattr(g, 'PLEX_URL', '')
        plex_token = getattr(g, 'PLEX_TOKEN', '')
        _add_status('Plex URL', _is_url(plex_url))
        _add_status('Plex Token', bool(plex_token))
        
        # Test actual Plex connection if both URL and token are configured
        plex_connection_ok = False
        if plex_url and plex_token:
            try:
                plex_client = get_plex_client()
                if plex_client:
                    plex_connection_ok = plex_client.test_connection()
            except Exception:
                plex_connection_ok = False
        _add_status('Plex Connection', plex_connection_ok if (plex_url and plex_token) else True)
        
        _add_status('Google Gemini API Key', bool(getattr(g, 'GOOGLE_API_KEY', '')))
        _add_status('TMDb API Key', bool(getattr(g, 'TMDB_API_KEY', '')))
        overseerr_url = getattr(g, 'OVERSEERR_URL', '')
        _add_status('Overseerr URL (optional)', _is_url(overseerr_url) if overseerr_url else True)
        overseerr_key = getattr(g, 'OVERSEERR_API_KEY', '')
        _add_status('Overseerr API Key (optional)', True if not overseerr_url else bool(overseerr_key))
        quotas = getattr(g, 'GEMINI_DAILY_QUOTAS', {})
        _add_status('Gemini Daily Quotas (optional)', isinstance(quotas, dict))
        # Library inclusion filter summary
    # Library filter removed (status entry omitted)
    # Build category -> Overseerr discover links using Overseerr keyword ids when possible
    category_links = []
    if recs and recs.get('ai_categories') and getattr(g, 'OVERSEERR_URL', ''):
        base = getattr(g, 'OVERSEERR_URL')
        for cat in recs.get('ai_categories'):
            if not isinstance(cat, str):
                continue
            # Try Overseerr keyword lookup first, fallback to TMDb if needed
            kid = overseerr_keyword_id(cat)
            if kid is None:
                kid = tmdb_keyword_id(cat)
            
            if kid is not None:
                # Use the user-facing Overseerr page URL, not the API URL
                # Default to TV since many categories apply to both but TV is more common
                url = f"{base}/discover/tv?keywords={kid}"
            else:
                # Fallback: simple search query
                url = f"{base}/search?query={requests.utils.quote(cat)}"
            category_links.append({'label': cat, 'url': url})
    return render_template(
            template_name,
    users=users if not getattr(g, 'USER_MODE', False) else [],
        selected_user=selected_user,
        recs=recs,
        debug_info=debug_info,
    user_login_error=user_login_error,
        show_loading=show_loading,
        loading_message=loading_message,
    library_status=None,
    show_status_only=None,
    movie_status_only=None,
    version=VERSION,
    use_tautulli_db=getattr(g, 'use_tautulli_db', False),
    tautulli_db_path=getattr(g, 'TAUTULLI_DB_PATH', ''),
    tmdb_enabled=bool(getattr(g, 'TMDB_API_KEY', '')),
    user_mode=getattr(g, 'USER_MODE', False),
    is_localhost=is_localhost,
    mode=(recs.get('mode') if recs else form_mode),
    decade_selected=(recs.get('decade_code') if recs else (int(form_decade) if form_decade and form_decade.isdigit() else None)),
    genre_selected=(recs.get('genre_code') if recs else form_genre),
    mood_selected=(recs.get('mood_code') if recs else form_mood),
    moods=MOOD_LABEL_MAP,
    selection_desc=(recs.get('selection_desc') if recs else None),
    user_login_value=user_login_value,
    user_config_status=user_config_status,
    category_links=category_links
    ,overseerr_url=getattr(g, 'OVERSEERR_URL', '')
    )

# Settings page
@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    # Hide settings page entirely in user mode
    if getattr(g, 'USER_MODE', False):
        return redirect(url_for('index'))
    # No need for global, settings are reloaded per request
    message = None
    message_type = None
    redirect_main = False
    import re
    def is_valid_url(url):
        return bool(re.match(r'^https?://', url))
    def is_nonempty(val):
        return bool(val and val.strip())
    def test_tautulli(url: str, api_key: str):
        try:
            params = {'apikey': api_key, 'cmd': 'get_users'}
            r = requests.get(f"{url}/api/v2", params=params, timeout=5)
            j = r.json()
            resp = j.get('response', {})
            if resp.get('result') == 'success':
                data = resp.get('data', [])
                # Accept either list or dict with users/data
                if isinstance(data, list) and len(data) >= 0:
                    return True, None
                if isinstance(data, dict):
                    if isinstance(data.get('users'), list):
                        return True, None
                    if isinstance(data.get('data'), list):
                        return True, None
                # Even with success, if structure unexpected, consider OK
                return True, None
            return False, resp.get('message') or 'Tautulli response not successful'
        except Exception as e:
            return False, str(e)
    def test_tautulli_db(path: str):
        import sqlite3
        try:
            if not path:
                return False, 'No DB path provided'
            if not os.path.exists(path):
                return False, f'DB not found at {path}'
            conn = sqlite3.connect(path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}
            conn.close()
            # Consider DB valid if it has likely Tautulli tables
            likely = {'users', 'session_history'}
            if tables & likely:
                return True, None
            return False, f'DB opened but expected tables not found (found: {sorted(list(tables))[:5]}...)'
        except Exception as e:
            return False, str(e)

    def test_plex(url: str, token: str):
        try:
            if not url or not token:
                return False, 'Plex URL and Token are required'
            
            # Test connection using same logic as PlexClient
            headers = {'X-Plex-Token': token}
            resp = requests.get(f"{url}/identity", headers=headers, timeout=10)
            if resp.status_code == 200:
                return True, None
            else:
                return False, f"HTTP {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            return False, str(e)

    if request.method == 'POST':
        new_settings = {
            'TAUTULLI_URL': request.form.get('TAUTULLI_URL', '').strip(),
            'TAUTULLI_API_KEY': request.form.get('TAUTULLI_API_KEY', '').strip(),
            'GOOGLE_API_KEY': request.form.get('GOOGLE_API_KEY', '').strip(),
            'TAUTULLI_DB_PATH': request.form.get('TAUTULLI_DB_PATH', '').strip(),
            'GEMINI_DAILY_QUOTAS': request.form.get('GEMINI_DAILY_QUOTAS', '').strip(),
            'TMDB_API_KEY': request.form.get('TMDB_API_KEY', '').strip(),
            'OVERSEERR_URL': request.form.get('OVERSEERR_URL', '').strip(),
            'OVERSEERR_API_KEY': request.form.get('OVERSEERR_API_KEY', '').strip(),
            'GEMINI_MODEL': request.form.get('GEMINI_MODEL', '').strip(),
            'PLEX_URL': request.form.get('PLEX_URL', '').strip(),
            'PLEX_TOKEN': request.form.get('PLEX_TOKEN', '').strip(),
        }
        # Collect chosen library IDs from multi-select checkboxes
    # Library inclusion filter removed
        # Optional file upload to copy DB locally
        try:
            file = request.files.get('TAUTULLI_DB_FILE')
        except Exception:
            file = None
        saved_upload_path = None
        if file and getattr(file, 'filename', ''):
            from werkzeug.utils import secure_filename
            safe_name = secure_filename(file.filename) or 'Tautulli.db'
            upload_dir = os.path.join(app.root_path, 'data')
            os.makedirs(upload_dir, exist_ok=True)
            saved_upload_path = os.path.join(upload_dir, safe_name)
            file.save(saved_upload_path)
            new_settings['TAUTULLI_DB_PATH'] = saved_upload_path
        errors = []
        if not is_valid_url(new_settings['PLEX_URL']):
            errors.append('Plex URL must start with http:// or https://')
        if not is_nonempty(new_settings['PLEX_TOKEN']):
            errors.append('Plex Token is required')
        if not is_nonempty(new_settings['GOOGLE_API_KEY']):
            errors.append('Google Gemini API Key is required')
        # Tautulli settings are now optional since we use Plex directly
        if new_settings.get('TAUTULLI_URL') and not is_valid_url(new_settings['TAUTULLI_URL']):
            errors.append('Tautulli URL must start with http:// or https://')
        # Overseerr settings are optional; validate URL format if provided
        if new_settings.get('OVERSEERR_URL'):
            if not is_valid_url(new_settings['OVERSEERR_URL']):
                errors.append('Overseerr URL must start with http:// or https://')
        # Live-validate Plex connectivity with provided values
        if not errors:
            ok_p, err_p = test_plex(new_settings['PLEX_URL'], new_settings['PLEX_TOKEN'])
            if not ok_p:
                errors.append(f"Could not connect to Plex with provided URL/Token: {err_p}")
        
        # Tautulli connectivity test only if URL and API key provided
        if not errors and new_settings.get('TAUTULLI_URL') and new_settings.get('TAUTULLI_API_KEY'):
            ok_t, err_t = test_tautulli(new_settings['TAUTULLI_URL'], new_settings['TAUTULLI_API_KEY'])
            if not ok_t:
                errors.append(f"Could not connect to Tautulli with provided URL/API key: {err_t}")
        # Validate DB path if provided
        if not errors and new_settings.get('TAUTULLI_DB_PATH'):
            ok_db, err_db = test_tautulli_db(new_settings['TAUTULLI_DB_PATH'])
            if not ok_db:
                errors.append(f"Tautulli DB path invalid: {err_db}")
        # Validate quotas JSON if provided
        if not errors and new_settings.get('GEMINI_DAILY_QUOTAS'):
            try:
                import json as _json
                parsed = _json.loads(new_settings['GEMINI_DAILY_QUOTAS'])
                if not isinstance(parsed, dict):
                    errors.append('Gemini daily quotas must be a JSON object mapping model -> integer calls per day')
                else:
                    # Ensure values are numbers
                    for k, v in parsed.items():
                        if not isinstance(v, (int, float)):
                            errors.append('Gemini daily quotas values must be numbers')
                            break
            except Exception as e:
                errors.append(f'Gemini daily quotas invalid JSON: {e}')
        if errors:
            message = ' '.join(errors)
            message_type = 'error'
        else:
            ok, err = save_settings(new_settings)
            if ok:
                message = '\u2705 Settings validated - Redirecting...'
                message_type = 'success'
                # Show message for 2 seconds, then redirect
                return render_template('settings.html', settings=new_settings, missing=[], message=message, message_type=message_type, redirect_main=True)
            else:
                message = f'\u274C Failed to save settings: {err}'
                message_type = 'error'
    settings = get_settings()
    missing = []
    if not settings['TAUTULLI_URL']:
        missing.append('TAUTULLI_URL')
    if not settings['TAUTULLI_API_KEY']:
        missing.append('TAUTULLI_API_KEY')
    if not settings['GOOGLE_API_KEY']:
        missing.append('GOOGLE_API_KEY')
    # DB path is optional; try to infer default
    # Build a simple feature summary map for template clarity
    feature_summary = []
    def _feat(name, enabled, desc):
        feature_summary.append({'name': name, 'enabled': bool(enabled), 'desc': desc})
    _feat('Plex Server Connection', bool(settings.get('PLEX_URL') and settings.get('PLEX_TOKEN')), 'Direct Plex integration for accurate availability checking.')
    _feat('Plex Library Scanning', bool(settings.get('PLEX_URL') and settings.get('PLEX_TOKEN')), 'Batch scanning of all Plex libraries for instant availability.')
    _feat('High-quality Posters & Metadata (TMDb)', bool(settings.get('TMDB_API_KEY')), 'Adds TMDb posters, overview, runtime & ratings.')
    _feat('Direct Overseerr Deep Links', bool(settings.get('OVERSEERR_URL')), 'Poster clicks open within Overseerr UI.')
    _feat('Overseerr Auth Features', bool(settings.get('OVERSEERR_URL') and settings.get('OVERSEERR_API_KEY')), 'Future advanced Overseerr features (requests/status).')
    _feat('Full Watch History (Tautulli DB)', bool(settings.get('TAUTULLI_DB_PATH') and os.path.exists(settings.get('TAUTULLI_DB_PATH'))), 'Enables full watch history enrichment.')
    _feat('Enhanced Watch History (Tautulli API)', bool(settings.get('TAUTULLI_URL') and settings.get('TAUTULLI_API_KEY')), 'Access to user viewing patterns and preferences.')
    _feat('Daily Gemini Quotas Enforcement', bool(settings.get('GEMINI_DAILY_QUOTAS')), 'Limits model calls per day based on JSON map.')
    _feat('Preferred Gemini Model Override', bool(settings.get('GEMINI_MODEL')), 'Forces first-attempt model when generating recommendations.')
    # Removed Library Inclusion Filter & Plex Direct Library Source features
    # Fetch libraries for inclusion UI
    return render_template('settings.html', settings=settings, missing=missing, message=message, message_type=message_type, redirect_main=False, feature_summary=feature_summary)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=2665, debug=True)
