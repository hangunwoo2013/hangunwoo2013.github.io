# Changelog — B-ROUTE 1.8

- Added server-side data.go.kr/TAGO request adapter and credential redaction.
- Added bus route catalog endpoint using `BusRoute/getBusRoute`.
- Added rail city, station and origin/destination train-time endpoints using TAGO `TrainInfo`.
- Added normalized TAGO bus arrival fields.
- Added owner-only provider probe and admin UI controls.
- Added provider response cache and best-effort per-instance request throttling.
- Added source integration guide and explicit boundary between provider lookup and GTFS route planning.
- Updated service worker shell cache version to 1.8.
- No real API key, live upstream call or EdgeOne deployment was used in tests.
