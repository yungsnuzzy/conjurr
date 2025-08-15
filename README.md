# conjurr
Conjurr is an AI recommendation tool that uses Tautulli watch data to recommend what users should watch next.

## Overview
Conjurr analyzes Plex watch history via Tautulli, resolves authoritative TMDb IDs, and uses Google Gemini to suggest what to watch next. Availability is determined through Overseerr (via TMDb IDs + Plex URL presence). The app provides:tarr
Conjurr is an AI recommendation tool that uses Tautulli watch data to recommend what users should watch next.

## Overview
Conjurr analyzes Plex watch history via Tautulli, resolves TMDb IDs, and uses Google Gemini to suggest what to watch next. Availability is determined through Overseerr (via TMDb IDs + Plex URL presence). The app provides:

- AI 20×20 candidate lists (20 shows + 20 movies requested from the model) with diversity caps
- Clear split of recommendations available vs. not available (Overseerr / Plex presence)
- Top Watched and Recently Watched lists that inform the AI prompt
- High-quality posters & metadata (overview/runtime/rating) via TMDb
- Scrolling “AI Categories” ticker inferred from tastes (hidden in Custom mode)
- Mobile-optimized UI (auto-selected in user mode for small viewports)
- User Mode (email/username required; hides settings/debug panels)
- Custom Mode (Decade + Genre + Mood filters; must supply at least one; 40% history taste / 60% filter emphasis)
- Concurrency + caching for TMDb searches, posters, Overseerr availability, and user lists
- Timing & AI diagnostics (admin mode only)
- Open Graph/Twitter meta tags for rich link previews
- Model label in header (shows which Gemini model served the response)

## Setup
1. Install dependencies:
	- Use `requirements.txt` with your Python 3.11+ environment.
2. Start the app and open the UI at `/` (defaults to http://127.0.0.1:2665).(CONJ)
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
5. Switch to Custom mode to constrain by Decade (1950s–2020 Now) and/or Genre (alphabetized list). You must select at least one; both will yield a combined descriptor (e.g. “Best of 1980s Sci-Fi”). Categories ticker hidden in Custom mode.

### Custom Mode Details
- Weighting: 40% influenced by historical viewing taste, 60% by the selected decade/genre/mood filters.
- Decade 2020 includes all future/current titles (2020 and later).
- Mood options: Underrated, Surprise Me, Out of my comfort zone, Comfort Food, Award Winners, Popular (streaming services), Seasonal.
- If only one dimension is provided, the other dimensions are broadened intelligently (e.g. only Decade → broader genre/mood variety; only Mood → broader decades around user preferences).
- The selection descriptor (selection_desc) is shown under the form and returned in the API.
- Categories ticker suppressed to keep focus on curated filter output.

### Poster Ordering / Separation
- Movies appear before Shows; each type gets its own poster section.
- Items that are available in plex appear separate from items that are unavailable. 

### Year Display & Matching
- Each AI recommendation includes a year; the app enforces year presence in the Gemini prompt.
- TMDb searches are weighted to favor exact year + title similarity; fallback search occurs if the year-specific search yields no result.
- Poster cards display the year beneath the title.

### API usage: 
- see `api_guide.md` for programmatic access to `/recommendations` 

## Features in detail

 Overseerr (optional) for deep links & availability; set OVERSEERR_URL and optionally OVERSEERR_API_KEY (if your instance requires a key). Posters link to the Overseerr item page.

Removed / Deprecated (docs updated):
- Local library.db cache & rebuild button (availability now on-demand via Overseerr; full pre-scan removed)
- Library inclusion filter UI (TAUTULLI_INCLUDE_LIBRARIES)
- Plex direct library inventory (Plex URL/Token fields)
- /rebuild_library endpoint

Known issues:
- "Paddington effect" - It seems sometimes the model will get hung up on one movie and recommend it to several people. This isn't super noticeable and isn't even that common, but while building this I've noticed everyone getting recommended Paddington for some reason. Maybe it's the movie that will bring humanity together - all things to all people. Idk. 

- .env is used for every call, but if you change the model in Settings and don't refresh the main page, it will persist with the old model name (display only) on the top right. 

Planned / Ideas:
- Short-lived availability cache (per tmdb_id) to reduce Overseerr round trips
- Disk persistence for TMDb detail cache
- Optional authentication / API token for /recommendations endpoint
