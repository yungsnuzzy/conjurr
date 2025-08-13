# ZOLTARR API Guide

A lightweight guide to interact with the Flask service programmatically. This app uses Tautulli for Plex data and Gemini for AI suggestions. No authentication is enforced by the app itself (secure via network/reverse proxy).

- Base URL: http://<host>:<port>
- CORS: Not configured (browser cross-origin calls may be blocked by default)
- Rate limits: None

## Prerequisites
- Configure settings in the UI at `/settings` (Tautulli URL, Tautulli API Key, Google Gemini API Key).
- Ensure Tautulli is reachable from the app host.
 - Optional: Set `USER_MODE=1` in `.env` to enable user mode (hides settings/debug; requires email/username login).

## Get Recommendations
Returns a JSON bundle of AI recommendations, availability in your Plex library (via Tautulli), user watch stats, posters (if TMDb is configured), and debug/timing/AI metadata.

Two modes influence the AI prompt:
- history (default): Pure history-based taste modeling. Includes ai_categories ticker.
- custom: Requires at least one of decade or genre; blends 40% historical taste + 60% filter targeting. Categories (ai_categories) suppressed in UI; field may be empty.

- Method: GET
- Path: `/recommendations`
- Query params:
  - `user_id` (required): Tautulli user ID
  - `mode` (optional): 'history' (default) or 'custom'
  - `decade` (optional, custom mode): One of 1950,1960,...,2020 (2020 = 2020 and later). Must supply decade or genre (or both) when mode=custom.
  - `genre` (optional, custom mode): One of the supported short codes (action, drama, comedy, scifi, horror, thriller, documentary, animation, family, fantasy, romance, crime, mystery, adventure, war, western, musical, biography, history, sports).

### Example (PowerShell)
```powershell
# Replace the host/port and user_id
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user_id=123" | ConvertTo-Json -Depth 6
```

### Response (200)
```json
{
  "user_id": "123",
  "shows": ["Title A", "Title B"],
  "movies": ["Movie A", "Movie B"],
  "top_shows": ["Most Watched Show", "..."],
  "top_movies": ["Most Watched Movie", "..."],
  "ai_shows": [{"title": "...", "year": 2020}, {"title": "..."}],
  "ai_movies": [{"title": "...", "year": 2019}],
  "ai_categories": ["British comedy", "Game shows", "..."],
  "ai_shows_titles": ["..."],
  "ai_movies_titles": ["..."],
  "ai_shows_unavailable": ["AI rec that wasn't in library"],
  "ai_movies_unavailable": ["..."],
  "ai_shows_available": ["AI rec that matched library"],
  "ai_movies_available": ["..."],
  "show_posters": [{"title": "Title A", "url": "https://...", "source": "tmdb"}],
  "movie_posters": [{"title": "Movie A", "url": "https://...", "source": "tmdb"}],
  "history_count": 42,
  "mode": "history",
  "decade_code": 1980,
  "genre_code": "scifi",
  "selection_desc": "Best of 1980s Sci-Fi",
  "debug": {
    "timing": {
      "user_history": 0.12,
      "top_watched": 0.01,
      "library_fetch": 2.5,
      "unwatched_filter": 0.01,
      "gemini": 1.3,
      "ai_parse": 0.01,
      "fuzzy_match": 0.08
    },
    "recent_shows": ["..."],
    "recent_movies": ["..."],
    "gemini_error": null,
    "genai_sdk": "new",
    "gemini_model_used": "gemini-2.0-flash-001",
    "gemini_usage": {"prompt_token_count": 0, "candidates_token_count": 0, "total_token_count": 0},
    "gemini_usage_today": {"calls": 3, "total_tokens": 12345},
    "gemini_daily_quota": 200,
    "gemini_daily_remaining": 197,
    "gemini_prompt": "...",
    "gemini_raw_response": "...",
    "gemini_parsed_json": "{...}",
    "gemini_ai_shows": [{"title": "..."}],
    "gemini_ai_movies": [{"title": "..."}],
    "gemini_ai_categories": ["..."],
    "unwatched_shows_count": 100,
    "unwatched_movies_count": 200,
    "all_shows_count": 2000,
    "all_movies_count": 5000
  }
}
```

### Errors
- 400 when `user_id` is missing:
```json
{"error": "user_id required"}
```

Notes:
- On first call of the day, `library_fetch` may be slower while the local cache is rebuilt from Tautulli.
- `debug.gemini_error` may contain a message if the AI call failed; other fields will still be populated when possible.
- Posters are included only if a TMDb API key is configured; sources are labeled (e.g., `tmdb`).
- If `OVERSEERR_URL` is configured, poster tiles will link out to the corresponding item page in Overseerr.
- Daily model quotas can be configured via `GEMINI_DAILY_QUOTAS` (JSON) to soft-cap usage; see README.
- In custom mode the server will return `mode` plus any `decade_code` / `genre_code` provided; `ai_categories` may be an empty list.
- If mode=custom and neither decade nor genre is supplied the server returns 400 with an error JSON payload.

## Reset/Rebuild Library Cache
Forces the app to drop the local library cache; the next recommendation call (or page load) will repopulate it from Tautulli.

- Method: POST
- Path: `/rebuild_library`

### Example (PowerShell)
```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:9658/rebuild_library" | ConvertTo-Json -Depth 6
```

### Response (200)
```json
{
  "db_path": "C:/.../library.db",
  "status": "Library cache reset. It will be rebuilt on next page load.",
  "action": "deleted_file"
}
```

### Errors (500)
```json
{"error": "Failed to reset cache: ...", "db_path": "C:/.../library.db"}
```

## Get the user_id from Tautulli
This app does not expose a users API. Retrieve the `user_id` from your Tautulli instance directly:

- Method: GET
- Path: `TAUTULLI_URL/api/v2`
- Query: `cmd=get_users&apikey=<TAUTULLI_API_KEY>`

### Example (PowerShell)
```powershell
$tautulli = "http://localhost:8181"
$apiKey = "<TAUTULLI_API_KEY>"
$resp = Invoke-RestMethod -Method Get -Uri "$tautulli/api/v2?cmd=get_users&apikey=$apiKey"
$resp.response.data | ConvertTo-Json -Depth 6
```

Find the `user_id` field for the desired account and use it with `/recommendations`.

## UI Endpoints (HTML)
- `/` main page: user selector + recommendations table (admin mode) or email/username login (user mode)
- `/settings` configure Tautulli, Gemini, optional TMDb, and other settings (hidden in user mode)
 - Mobile override: append `?mobile=1` to force the mobile template or `?mobile=0` to force desktop.

## Security and Deployment
- No built-in auth; deploy behind a firewall/proxy and restrict access.
- Consider adding auth and CORS if exposing publicly.
