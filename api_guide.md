# ZOLTARR API Guide

A lightweight guide to interact with the Flask service programmatically. This app uses Tautulli for Plex data and Gemini for AI suggestions. No authentication is enforced by the app itself (secure via network/reverse proxy).

- Base URL: http://<host>:<port>
- CORS: Not configured (browser cross-origin calls may be blocked by default)
- Rate limits: None

## Prerequisites
- Configure settings in the UI at `/settings` (Tautulli URL, Tautulli API Key, Google Gemini API Key).
- Ensure Tautulli is reachable from the app host.

## Get Recommendations
Returns a JSON bundle of AI recommendations, availability in your Plex library (via Tautulli), user watch stats, and debug timing.

- Method: GET
- Path: `/recommendations`
- Query params:
  - `user_id` (required): Tautulli user ID

### Example (PowerShell)
```powershell
# Replace the host/port and user_id
Invoke-RestMethod -Method Get -Uri "http://localhost:5000/recommendations?user_id=123" | ConvertTo-Json -Depth 6
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
  "history_count": 42,
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

## Reset/Rebuild Library Cache
Forces the app to drop the local library cache; the next recommendation call (or page load) will repopulate it from Tautulli.

- Method: POST
- Path: `/rebuild_library`

### Example (PowerShell)
```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:5000/rebuild_library" | ConvertTo-Json -Depth 6
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
- `/` main page: user selector + recommendations table
- `/settings` configure Tautulli and Gemini keys

## Security and Deployment
- No built-in auth; deploy behind a firewall/proxy and restrict access.
- Consider adding auth and CORS if exposing publicly.
