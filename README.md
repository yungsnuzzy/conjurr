# zoltarr
Zoltarr is an AI recommendation tool that uses Tautulli watch data to recommend what users should watch next.

## Overview
Zoltarr analyzes Plex watch history via Tautulli and uses Google Gemini to suggest what to watch next. The app provides:

- AI Top 10 recommendations for shows and movies
- Clear split of recommendations available in your Plex library vs. not in library
- Your Top Watched and Recently Watched lists that inform the AI
- Beautiful poster galleries for recommended shows and movies (via TMDb)
- A scrolling “AI Categories” ticker inferred from your tastes
- Optional mobile-optimized UI (auto-detected for phones/tablets in user mode)
- Optional “User Mode” for direct user access with email/username login (no admin/debug panels)
- Local library caching (SQLite) refreshed daily, plus a one-click Rebuild Cache button
- Timing and AI diagnostics (visible in admin mode; hidden in user mode)
- Open Graph/Twitter meta tags for rich link previews
- Model label in the header showing which Gemini model was used

## Setup
1. Install dependencies:
	- Use `requirements.txt` with your Python 3.11+ environment.
2. Start the app and open the UI at `/` (defaults to http://127.0.0.1:9658).
3. Visit `/settings` and enter:
	- Tautulli URL and API key
	- Google Gemini API key
	- Optional: Tautulli DB Path (for faster local reads)
	- Optional: TMDb API key (to enable posters)
	- Optional: Gemini daily quotas JSON (e.g. {"gemini-2.0-flash-001": 200})

Environment/.env keys recognized:
- TAUTULLI_URL
- TAUTULLI_API_KEY
- GOOGLE_API_KEY
- TAUTULLI_DB_PATH (optional)
- TMDB_API_KEY (optional)
- GEMINI_DAILY_QUOTAS (optional JSON)

User Mode flag:
- In `app.py`, set `USER_MODE = 1` to enable user mode (hides settings/debug, requires email/username login, mobile UI auto for phones/tablets).

## Using the app
1. In admin mode: pick a user from the dropdown and click “Get Recommendations”.
2. In user mode: enter your Plex email or username, then click “Get Recommendations”.
3. Review posters and the categories ticker at the top.
4. Expand the “table details” (in user mode) to see the full data table.
5. Use “Rebuild Library DB” when library data is stale; the next request repopulates the cache.

API usage: see `api_guide.md` for programmatic access to `/recommendations` and `/rebuild_library` with examples and response fields.

## Features in detail
- Posters via TMDb: Provide `TMDB_API_KEY` to fetch poster images for recommended titles.
- Caching: Library items are persisted to `library.db` once per day; daily refresh keeps requests fast.
- Data sources: Uses Tautulli DB first (if configured) for users/history; falls back to Tautulli API.
- Gemini models: Tries a shortlist with the new Google GenAI SDK and tracks usage locally; shows model name in the UI.
- Quotas: Optional local daily quota tracking by model (configure via `GEMINI_DAILY_QUOTAS`).

## TO DO
- Package as a standalone Windows service/EXE.
- Add optional authentication and CORS configuration for public deployments.
- Add settings toggle to control user mode and mobile override.