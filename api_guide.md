# ZOLTARR API Guide

Programmatic access to AI-driven recommendations. Architecture relies on:
- Tautulli: watch history & user list  
- TMDb: metadata, posters, runtime, rating, genres (multi-pass search for robust TMDb ID resolution)
- Overseerr: on-demand availability (presence + plexUrl implies available)
- Gemini: large language model for candidate generation (20 shows + 20 movies per request)

Base URL: `http://<host>:<port>`
Authentication: None built-in (enforce at reverse proxy)
CORS: Not enabled by default
Rate limits: None

## API Endpoint
| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | /recommendations | Generate recommendation set (JSON or HTML) |

**Enhanced Features:**
- ✅ Email/username to user ID lookup
- ✅ Custom decade/genre filtering  
- ✅ Multiple output formats (JSON/HTML)
- ✅ Backward compatibility with existing user_id parameter

## Query Parameters
- `user_id` (optional): Tautulli user ID number (e.g., `29170859`)
- `user` (optional): Email or username for automatic lookup (alternative to user_id)
- `mode` (optional): `history` (default) or `custom`
- `decade` (optional, custom mode): `1950s`, `1960s`, `1970s`, `1980s`, `1990s`, `2000s`, `2010s`, `2020s` (or numeric: `1950`, `1960`, etc.)
- `genre` (optional, custom mode): TMDb genre name (case-insensitive): `action`, `drama`, `comedy`, `sci-fi`, `horror`, `thriller`, `documentary`, `animation`, `family`, `fantasy`, `romance`, `crime`, `mystery`, `adventure`, `war`, `western`, `musical`, `biography`, `history`, `sports`
- `format` (optional): `json` (default) or `html`

**Requirements:**
- Either `user_id` OR `user` must be provided
- Custom mode requires at least one of: `decade`, `genre`

## Examples (PowerShell)

### Basic Usage
```powershell
# Using Tautulli user ID (backward compatible)
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user_id=29170859"

# Using email lookup (new feature)
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user=josh@example.com"

# Using username lookup
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user=jsmith"
```

### Custom Filtering
```powershell
# Animation recommendations
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user=josh@example.com&mode=custom&genre=animation"

# 1980s movies and shows
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user_id=29170859&mode=custom&decade=1980s"

# 2000s Sci-Fi
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user=josh@example.com&mode=custom&decade=2000s&genre=sci-fi"
```

### Output Formats  
```powershell
# Force JSON output (default)
Invoke-RestMethod -Method Get -Uri "http://localhost:9658/recommendations?user=josh@example.com&format=json"

# Get HTML for embedding in web pages
Invoke-WebRequest -Method Get -Uri "http://localhost:9658/recommendations?user=josh@example.com&format=html"
```
```

## JSON Response (Current Implementation)
```json
{
  "user_id": "29170859",
  "mode": "history", 
  "history_count": 156,
  "movie_posters": [
    {
      "title": "Dune",
      "year": 2021,
      "tmdb_id": 438631,
      "poster_url": "https://image.tmdb.org/t/p/w342/def456.jpg",
      "overseerr_available": false,
      "plex_url": null,
      "overseerr_url": "https://overseerr.local/movie/438631"
    }
  ],
  "show_posters": [
    {
      "title": "Severance", 
      "year": 2022,
      "tmdb_id": 95396,
      "poster_url": "https://image.tmdb.org/t/p/w342/abc123.jpg",
      "overseerr_available": true,
      "plex_url": "https://plex.local/web/index.html#!/server/.../show/...",
      "overseerr_url": "https://overseerr.local/tv/95396"
    }
  ],
  "movie_posters_unavailable": [...],
  "show_posters_unavailable": [...],
  "categories": ["Prestige Workplace Sci-Fi", "Slow-Burn Mystery"],
  "debug_info": {
    "model_used": "gemini-2.5-flash-lite",
    "sample_calls": ["tv/95396", "movie/438631"],
    "base_url": "https://overseerr.local",
    "timing": {
      "total": 5.842,
      "ai": 1.944,
      "tmdb_search": 0.732,  
      "availability": 0.307
    }
  }
}
```

## Field Notes (Current Response)
- `overseerr_available`: True if Overseerr item exists and exposes `plex_url`
- `plex_url`: Direct link to content in Plex (null if unavailable)
- `overseerr_url`: Link to request/manage item in Overseerr
- Separate arrays for available (`*_posters`) and unavailable (`*_posters_unavailable`) content
- `debug_info.timing`: Per-phase execution times in seconds
- `categories`: AI-generated content categories (history mode only)

## Errors
- 400: Missing user identifier (`user_id` or `user` required)
- 400: User not found (invalid email/username)
- 400: Invalid mode (must be `history` or `custom`)
- 400: Invalid decade (must be `1950s`-`2020s`)
- 400: Invalid genre (see supported genres list above)
- 400: Custom mode missing filters (requires `decade` and/or `genre`)
- 400: Invalid format (must be `json` or `html`)
- 500: Internal error (check debug_info for details)

## Getting User Information
Multiple ways to identify users for the API:

### 1. Tautulli User IDs (Most Direct)
- **Web Interface**: Users & Libraries > Users table shows user IDs
- **Tautulli API**: 
  ```powershell
  Invoke-RestMethod -Uri "http://tautulli:8181/api/v2?apikey=YOUR_KEY&cmd=get_users"
  ```
- **Debug Output**: User IDs appear in Zoltarr logs during recommendations

### 2. Email/Username Lookup (New Feature)
- Use any email address associated with the Plex account
- Use Plex username (exact or partial match)
- Use Plex friendly/display name
- API automatically searches Tautulli user database for matches

## Response Formats

### JSON Format (Default)
Standard structured data suitable for programmatic consumption:
- Separate arrays for available/unavailable content
- Rich metadata including TMDb IDs, poster URLs, availability status
- Debug information with timing and performance metrics
- Categories and AI-generated insights

### HTML Format
Mobile-optimized HTML suitable for embedding or direct display:
- Responsive design with poster grid layout
- Interactive elements and visual styling
- Includes debug information in collapsible sections
- Same content as JSON but formatted for human consumption

## Implementation Status
**✅ Fully Implemented:**
- Basic recommendations via Tautulli user ID or email/username lookup
- History-based and custom mode recommendations  
- Decade filtering (1950s-2020s)
- Genre filtering (21 supported genres)
- JSON and HTML response formats
- Overseerr availability checking
- TMDb metadata and posters
- Comprehensive error handling and validation

**🔄 Available in Web Interface Only:**
- Advanced debug panels
- Interactive forms and settings management
- User authentication and session management

## Backward Compatibility
The enhanced API maintains full backward compatibility:
- Existing `user_id` parameter continues to work unchanged
- Default `mode=history` preserves original behavior  
- Default `format=json` maintains original response structure
- All original response fields remain intact

## Performance Notes
- **Email/Username Lookup**: Adds ~100-200ms for user resolution
- **Custom Mode**: Similar performance to history mode
- **HTML Format**: Slightly larger response size but faster client rendering
- **Caching**: User lookups and availability data are cached for improved performance

## Migration Path
For existing API consumers:
1. **No changes required** - existing calls continue to work
2. **Optional enhancements** - gradually adopt new parameters as needed
3. **Email lookup** - replace user_id with user parameter for simpler client code
4. **Custom filtering** - add mode/decade/genre for specialized recommendations

## Best Practices
- Cache responses client-side if polling (recommendations are compute-intensive)
- Use Tautulli user IDs directly for better performance  
- Monitor `debug_info.timing` to identify bottlenecks
- Consider proxy-level authentication for production use

## Security  
Add authentication at reverse proxy level (OAuth, Basic Auth, etc.). API responses contain no sensitive data, but recommendation generation consumes AI API quotas.

---
Updated to reflect current implementation limitations and suggest future enhancements.
