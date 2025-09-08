# CONJURR API Guide

Programmatic access to AI-driven recommendations. Architecture relies on:
- Tautulli: watch history & user list
- TMDb: metadata, posters, runtime, rating, genres (multi-pass search for robust TMDb ID resolution)
- Overseerr: on-demand availability (presence + plexUrl implies available)
- **Multi-Provider AI**: Gemini, Mistral, or OpenRouter for candidate generation (20 shows + 20 movies per request)

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
- ✅ **AI Model Selection** - Choose specific AI models per request
- ✅ **Multi-Provider Support** - Gemini, Mistral, OpenRouter
- ✅ Backward compatibility with existing user_id parameter

## Query Parameters
- `user_id` (optional): Tautulli user ID number (e.g., `29170859`)
- `user` (optional): Email or username for automatic lookup (alternative to user_id)
- `mode` (optional): `history` (default) or `custom`
- `decade` (optional, custom mode): `1950s`, `1960s`, `1970s`, `1980s`, `1990s`, `2000s`, `2010s`, `2020s` (or numeric: `1950`, `1960`, etc.)
- `genre` (optional, custom mode): TMDb genre name (case-insensitive): `action`, `drama`, `comedy`, `sci-fi`, `horror`, `thriller`, `documentary`, `animation`, `family`, `fantasy`, `romance`, `crime`, `mystery`, `adventure`, `war`, `western`, `musical`, `biography`, `history`, `sports`
- `mood` (optional, custom mode): Mood-based filtering: `underrated`, `surprise me`, `out of my comfort zone`, `comfort food`, `award winners`, `popular (streaming services)`, `seasonal`
- `model` (optional): **NEW** - Override default AI model for this request
- `format` (optional): `json` (default) or `html`

**Requirements:**
- Either `user_id` OR `user` must be provided
- Custom mode requires at least one of: `decade`, `genre`, `mood`

## AI Model Selection

### Supported Models by Provider

#### Gemini (Google AI)
- `gemini-2.5-flash-lite` - Fast, cost-effective (Default)
- `gemini-2.0-flash-001` - Balanced performance
- `gemini-1.5-flash` - Fast responses
- `gemini-1.5-pro` - Higher quality
- `gemini-pro` - Legacy high quality

#### Mistral AI
- `mistral-small` - Fast, cost-effective (Default, Free)
- `mistral-tiny` - Fastest, basic quality (Free)
- `mistral-medium` - Better quality
- `mistral-large-latest` - Highest quality

#### OpenRouter
- `anthropic/claude-3-haiku` - Fast, cost-effective (Default)
- `anthropic/claude-3-sonnet` - Balanced quality
- `anthropic/claude-3-opus` - Highest quality
- `openai/gpt-4o-mini` - Fast GPT-4 variant
- `openai/gpt-4o` - Full GPT-4 quality

**Notes:**
- Model availability depends on your configured AI provider
- Free models marked where applicable
- Defaults to your configured model if not specified
- Invalid models for your provider will fall back to defaults

## Examples (PowerShell)

### Basic Usage
```powershell
# Using Tautulli user ID (backward compatible)
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user_id=29170859"

# Using email lookup (new feature)
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com"

# Using username lookup
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=jsmith"
```

### AI Model Selection
```powershell
# Use specific Gemini model
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&model=gemini-1.5-pro"

# Use free Mistral model
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user_id=29170859&model=mistral-small"

# Use Claude via OpenRouter
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&model=anthropic/claude-3-sonnet"

# Use GPT-4 via OpenRouter
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user_id=29170859&model=openai/gpt-4o"
```

### Custom Filtering
```powershell
# Animation recommendations
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&mode=custom&genre=animation"

# 1980s movies and shows
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user_id=29170859&mode=custom&decade=1980s"

# 2000s Sci-Fi
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&mode=custom&decade=2000s&genre=sci-fi"

# Comfort Food mood recommendations
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&mode=custom&mood=comfort%20food"

# Award Winners mood
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user_id=29170859&mode=custom&mood=award%20winners"

# Seasonal mood (holiday-themed recommendations)
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&mode=custom&mood=seasonal"

# Combined filtering: 1990s Award Winners
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&mode=custom&decade=1990s&mood=award%20winners"
```

### Advanced Examples with Model Selection
```powershell
# High-quality Gemini model for detailed recommendations
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&model=gemini-1.5-pro"

# Fast free Mistral model for quick results
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user_id=29170859&model=mistral-tiny"

# Custom filtering with specific model
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&mode=custom&genre=sci-fi&model=anthropic/claude-3-opus"

# Seasonal recommendations with GPT-4
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&mode=custom&mood=seasonal&model=openai/gpt-4o"
```

### Output Formats  
```powershell
# Force JSON output (default)
Invoke-RestMethod -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&format=json"

# Get HTML for embedding in web pages
Invoke-WebRequest -Method Get -Uri "http://localhost:2665/recommendations?user=josh@example.com&format=html"
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
  "debug": {
    "ai_provider": "mistral",
    "ai_endpoint": "https://api.mistral.ai/v1/chat/completions",
    "ai_model_selected": "mistral-small",
    "ai_model_used": "mistral-small",
    "ai_usage": {
      "prompt_token_count": 1250,
      "candidates_token_count": 890,
      "total_token_count": 2140
    },
    "ai_usage_today": {
      "mistral-small": {
        "prompt_tokens": 1250,
        "completion_tokens": 890,
        "total_tokens": 2140,
        "requests": 1
      }
    },
    "timing": {
      "gemini_mistral-small": 2.145,
      "ai_parse": 0.023,
      "availability": 0.307,
      "posters": 1.234
    }
  }
}
```

## Field Notes (Current Response)
- `overseerr_available`: True if Overseerr item exists and exposes `plex_url`
- `plex_url`: Direct link to content in Plex (null if unavailable)
- `overseerr_url`: Link to request/manage item in Overseerr
- Separate arrays for available (`*_posters`) and unavailable (`*_posters_unavailable`) content
- `debug.ai_provider`: Current AI provider (gemini/mistral/openrouter)
- `debug.ai_endpoint`: API endpoint URL used for the request
- `debug.ai_model_selected`: Model requested (or "Auto-selected" if none)
- `debug.ai_model_used`: Actual model used by the AI provider
- `debug.ai_usage`: Token usage statistics for the request
- `debug.ai_usage_today`: Daily usage tracking for the model
- `debug.timing`: Per-phase execution times in seconds (now includes provider_model in AI timing)
- `categories`: AI-generated content categories (history mode only)

## Errors
- 400: Missing user identifier (`user_id` or `user` required)
- 400: User not found (invalid email/username)
- 400: Invalid mode (must be `history` or `custom`)
- 400: Invalid decade (must be `1950s`-`2020s`)
- 400: Invalid genre (see supported genres list above)
- 400: Invalid mood (must be one of: `underrated`, `surprise me`, `out of my comfort zone`, `comfort food`, `award winners`, `popular (streaming services)`, `seasonal`)
- 400: Custom mode missing filters (requires `decade`, `genre`, and/or `mood`)
- 400: Invalid format (must be `json` or `html`)
- 400: Invalid model (model not available for current AI provider)
- 500: Internal error (check debug section for details)

## Getting User Information
Multiple ways to identify users for the API:

### 1. Tautulli User IDs (Most Direct)
- **Web Interface**: Users & Libraries > Users table shows user IDs
- **Tautulli API**: 
  ```powershell
  Invoke-RestMethod -Uri "http://tautulli:8181/api/v2?apikey=YOUR_KEY&cmd=get_users"
  ```
- **Debug Output**: User IDs appear in Conjurr logs during recommendations

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
- Mood filtering (7 curated options: Underrated, Surprise Me, Out of my comfort zone, Comfort Food, Award Winners, Popular streaming, Seasonal)
- **AI Model Selection** - Per-request model override
- **Multi-Provider AI Support** - Gemini, Mistral, OpenRouter
- JSON and HTML response formats
- Overseerr availability checking
- TMDb metadata and posters
- Comprehensive error handling and validation
- Enhanced debug information with AI endpoint tracking

**🔄 Available in Web Interface Only:**
- Advanced debug panels with AI endpoint tracking
- Interactive forms and settings management
- User authentication and session management
- **Model selection dropdowns** - Choose AI models via web UI
- Real-time debug information display
- Model selection dropdowns

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
4. **Custom filtering** - add mode/decade/genre/mood for specialized recommendations

## Best Practices
- Cache responses client-side if polling (recommendations are compute-intensive)
- Use Tautulli user IDs directly for better performance
- **Choose appropriate AI models**: Use free models (mistral-small/tiny) for cost control
- **Monitor API usage**: Check `debug.ai_usage` and `debug.ai_usage_today` for quota management
- Monitor `debug.timing` to identify bottlenecks
- Consider proxy-level authentication for production use
- Use model selection strategically - higher quality models may have higher latency

## Security
Add authentication at reverse proxy level (OAuth, Basic Auth, etc.). API responses contain no sensitive data, but recommendation generation consumes AI API quotas from multiple providers (Google Gemini, Mistral AI, OpenRouter).

**AI Provider Considerations:**
- **Gemini**: Uses Google AI API quotas
- **Mistral**: Uses Mistral AI API quotas (free tier available)
- **OpenRouter**: Uses OpenRouter API quotas (proxies to various providers)

Monitor usage via the `debug.ai_usage_today` field to track consumption across providers.

---
**Last Updated:** September 8, 2025  
**Version:** 2.0 - Multi-Provider AI with Model Selection  
**Features:** Complete API documentation with AI model selection, multi-provider support, and enhanced debug information.
