# ZOLTARR API Guide

Programmatic access to AI-driven recommendations. Architecture now relies on:
- Tautulli: watch history & user list
- TMDb: metadata, posters, runtime, rating, genres (multi-pass search for robust TMDb ID resolution)
- Overseerr: on-demand availability (presence + plexUrl implies available)
- Gemini: large language model for candidate generation (20 shows + 20 movies per request)

Base URL: `http://<host>:<port>`
Authentication: None built-in (enforce at reverse proxy)
CORS: Not enabled by default
Rate limits: None

## Endpoint
| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | /recommendations | Generate recommendation set (HTML or JSON) |

The former `/rebuild_library` endpoint and local library cache have been removed. Availability is resolved per-item via Overseerr at request time; no daily pre-scan.

## Query Parameters
- `user` (optional): Email or username; omit for aggregate profile.
- `mode` (optional): `history` (default) or `custom`.
- `decade` (custom): `1950s`..`2020 Now` (must supply decade or genre when custom).
- `genre` (custom): TMDb genre name (case-insensitive).
- `format` (optional): `json` to force JSON output.

If `mode=custom` and neither `decade` nor `genre` supplied -> 400.

## Example (PowerShell)
```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user=alice@example.com&format=json" | ConvertTo-Json -Depth 8
```

## JSON Response (Representative)
```json
{
  "user": "alice@example.com",
  "mode": "history",
  "filters": {},
  "counts": {
    "shows": {"total": 20, "available": 11},
    "movies": {"total": 20, "available": 9}
  },
  "shows": [
    {
      "title": "Severance",
      "type": "show",
      "year": 2022,
      "tmdb_id": 95396,
      "available": true,
      "overview": "Mark leads a team...",
      "poster_url": "https://image.tmdb.org/t/p/w342/abc123.jpg",
      "genres": ["Sci-Fi", "Drama"],
      "rating": 8.4,
      "runtime": 55,
      "overseerr_url": "https://overseerr.local/tv/95396"
    }
  ],
  "movies": [
    {
      "title": "Dune",
      "type": "movie",
      "year": 2021,
      "tmdb_id": 438631,
      "available": false,
      "overview": "Paul Atreides...",
      "poster_url": "https://image.tmdb.org/t/p/w342/def456.jpg",
      "genres": ["Adventure", "Sci-Fi"],
      "rating": 8.1,
      "runtime": 155,
      "overseerr_url": "https://overseerr.local/movie/438631"
    }
  ],
  "debug": {
    "model": "gemini-1.5-flash",
    "raw_prompt_chars": 3210,
    "ai_response_chars": 2504,
    "tmdb_resolution": {
      "attempts": 40,
      "misses": 1,
      "sample_events": ["search:Severance (2022)", "search_no_year:Severance"]
    },
    "overseerr_availability": {
      "calls": 40,
      "cache_hits": 12,
      "sample_calls": ["tv/95396", "movie/438631"],
      "had_key": true
    },
    "categories": ["Prestige Workplace Sci-Fi", "Slow-Burn Mystery"],
    "diversity_enforced": true,
    "timing": {
      "total": 5.842,
      "ai": 1.944,
      "tmdb_search": 0.732,
      "tmdb_details": 0.211,
      "posters": 1.102,
      "availability": 0.307
    }
  }
}
```

## Field Notes
- `counts`: Provided separately (target 20 each; may be lower if AI under-produces or parsing drops items).
- `available`: True if Overseerr item exists and exposes `plexUrl` (or equivalent presence indicator).
- `overseerr_url`: Provided when base Overseerr URL configured.
- `debug.tmdb_resolution`: Multi-pass ID search diagnostics.
- `debug.overseerr_availability`: Overseerr request metrics; `had_key` shows whether API key configured.
- `debug.timing`: Per-phase times (seconds).
- `debug.categories`: Present for history mode; may be empty/suppressed for custom mode.

## Removed / Legacy
- Local library cache & counters (`unwatched_*`, `all_*`)
- `library_fetch`, `fuzzy_match` timings
- `/rebuild_library` endpoint

## Errors
- 400: Invalid custom mode (missing decade & genre) or malformed parameters.
- 500: Internal error (inspect `debug` in admin mode for phase failures).

## Availability Flow
1. Normalize title/year from AI output.
2. Multi-pass TMDb search (original, stripped year, simplified, Overseerr search fallback) to obtain TMDb ID.
3. Query Overseerr item endpoint (`/api/v1/{movie|tv}/{tmdb_id}`).
4. Mark available if item present + `plexUrl` (or positive media status).
5. (Planned) Short TTL cache to coalesce bursts.

## Best Practices
- Cache responses client-side if polling.
- Provide `user` for personalized set.
- Monitor `debug.timing` to identify bottlenecks (AI or network). Optimize via environment (concurrency, caching) rather than increasing poll frequency.

## Security
Add auth at the proxy (e.g., OAuth, Basic Auth). No secrets returned; model prompt appears only in debug (admin mode).

---
Updated for Overseerr-based availability & 20×20 recommendation architecture.
