# zoltarr
Zoltarr is an AI recommendation tool that uses Tautulli watch data to recommend what users should watch next. 


TO DO
* There should be a way for users to pull their own recommendation data any time. Maybe "input your email" type field that uses PHP to look up users and give them their recommendations on the fly? Otherwise they'll only get it in emails, and that may be overwhelming. 

* Make it pretty

* Make it functionally standalone, make a release as an EXE or NT service

* Make settings page for Tautulli path and api key, google gemini api key

* Formalize API so a given user can be passed, and the data returned as JSON

* Movie and show data is currently cached for up to 1 day while the app is running - this should be moved to a local media.db file that gets update once a day/week? maybe a user setting for how often, since it takes a while. 

* Instead of just "Top 3" movies and shows, maybe we use the top 3 along with the last 3? Last 5? 10? 

* Separate AI recommendations into "Available on Plex" and "Not available yet"