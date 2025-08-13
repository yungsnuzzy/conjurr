# zoltarr
Zoltarr is an AI recommendation tool that uses Tautulli watch data to recommend what users should watch next.

## Overview
Zoltarr analyzes Plex watch history via Tautulli and uses Google Gemini to suggest what to watch next. The app provides:

- AI Top 10 recommendations for shows and movies (History mode)
- Clear split of recommendations available in your Plex library vs. not in library
- Your Top Watched and Recently Watched lists that inform the AI
- Beautiful poster galleries for recommended shows and movies (via TMDb)
- A scrolling “AI Categories” ticker inferred from your tastes (hidden in Custom mode)
- Optional mobile-optimized UI (auto-detected for phones/tablets in user mode)
- Optional “User Mode” for direct user access with email/username login (no admin/debug panels)
- Custom Mode with optional Decade + Genre filters (must pick at least one) for a curated blend (40% history taste, 60% filter target)
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
- USER_MODE (optional: 1 to enable user mode, 0 to disable)
- OVERSEERR_URL (optional: enables poster links to Overseerr)
- OVERSEERR_API_KEY (optional: only needed if Overseerr endpoint requires it for lookups)

User Mode flag:
- Prefer setting `USER_MODE=1` in your `.env` to enable user mode (hides settings/debug, requires email/username login, auto mobile UI for phones/tablets). You can still set the code default in `app.py` but `.env` wins.

Mobile override:
- You can force mobile/desktop rendering by adding `?mobile=1` (force mobile) or `?mobile=0` (force desktop) to the URL. This only affects the template choice; app logic is unchanged.

## Using the app
1. In admin mode: pick a user from the dropdown and click “Get Recommendations”.
2. In user mode: enter your Plex email or username, then click “Get Recommendations”.
3. Review posters (Movies listed before Shows; each on its own row). Categories ticker only appears in History mode.
4. Expand the “table details” (in user mode) to see the full data table.
5. Use “Rebuild Library DB” when library data is stale; the next request repopulates the cache.
6. Switch to Custom mode to constrain by Decade (1950s–2020 Now) and/or Genre (alphabetized list). You must select at least one; both will yield a combined descriptor (e.g. “Best of 1980s Sci-Fi”). Categories ticker is hidden in Custom mode.

### Custom Mode Details
- Weighting: 40% influenced by historical viewing taste, 60% by the selected decade/genre filters.
- Decade 2020 includes all future/current titles (2020 and later).
- If only one dimension is provided, the other is broadened intelligently (e.g. only Decade → broader genre variety; only Genre → broader decades around modern/popular eras).
- The selection descriptor (selection_desc) is shown under the form and returned in the API.
- Categories ticker suppressed to keep focus on curated filter output.

### Poster Ordering / Separation
- Movies always appear before Shows in both poster galleries and tables.
- Movies and Shows never share the same horizontal poster row (hard separation).

### Year Display & Matching
- Each AI recommendation includes a year; the app enforces year presence in the Gemini prompt.
- TMDb searches are weighted to favor exact year + title similarity; fallback search occurs if the year-specific search yields no result.
- Poster cards display the year beneath the title.

API usage: see `api_guide.md` for programmatic access to `/recommendations` and `/rebuild_library` with examples and response fields.

## Features in detail

 Overseerr (optional) for request links; set OVERSEERR_URL and optionally OVERSEERR_API_KEY. When set, posters link to the item page in Overseerr.
- Package as a standalone Windows service/EXE.
