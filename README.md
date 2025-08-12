# zoltarr
Zoltarr is an AI recommendation tool that uses Tautulli watch data to recommend what users should watch next. 


## Overview
Zoltarr analyzes Plex watch history via Tautulli and uses Google Gemini to suggest what to watch next. It shows:

- AI Top 10 recommendations for shows and movies
- Which AI picks are available in your Plex library vs. not in library
- Your Top Watched and Recent (last 10) items that inform the AI
- Timing diagnostics for each step (always visible)

Data about your Plex library is cached locally in SQLite and refreshed daily to keep the UI fast. A Rebuild button lets you reset the cache on demand.

## How to use
1. Start the app and open the UI at `/' (Defaults to 127.0.0.1:9658)
2. Go to `/settings` and enter:
	- Tautulli URL and API key
	- Google Gemini API key
3. Back on the main page, pick a user and click “Get Recommendations”.
4. Review the table: available picks, not-in-library picks, AI Top 10, categories, and your watch stats.
5. If library data seems stale or missing, use “Rebuild Library DB” in the left panel.

API usage: see `api_guide.md` for programmatic access to `/recommendations` and `/rebuild_library` with examples.


TO DO
* There should be a way for users to pull their own recommendation data any time. Maybe "input your email" type field that uses PHP to look up users and give them their recommendations on the fly Otherwise they'll only get it in emails, and that may be overwhelming. 

* Make it functionally standalone, make a release as an EXE or NT service

* (DONE) Make it pretty

* (DONE) Make settings page for Tautulli path and api key, google gemini api key

* (DONE) Formalize API so a given user can be passed, and the data returned as JSON - make quick guide for using API

* (DONE) Movie and show data is currently cached for up to 1 day while the app is running - this should be moved to a local media.db file that gets update once a day/week? maybe a user setting for how often, since it takes a while. 

* (DONE) Instead of just "Top 3" movies and shows, maybe we use the top 3 along with the last 3? Last 5? 10? 

* (DONE) Separate AI recommendations into "Available on Plex" and "Not available yet"

* (DONE) Set version variable