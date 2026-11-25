# B-ROUTE Local 1.4 — Demo Ready

## Added
- `?demo=1` demo mode with an explicit banner stating sample transit data is fictional.
- Three preset scenarios: bus-only (Seoul), rail-only (Busan), and bus + rail (Goyang–Seoul).
- Sample route geometry and step-by-step cards for demonstrating the map and itinerary UI without provider API keys or GTFS feeds.
- Automatic device-local saving after successful real route calculations and demo route generation.
- Saved route snapshots so a previously computed result can be reopened without recalculating it.
- Per-route `.broute` JSON export and validated `.broute` import.
- Top-bar shortcut to the tester feedback form.
- Service worker cache version bumped to 1.4.

## Preserved
- Original Leaflet map, satellite/hybrid/terrain layers, place search, GPS, waypoints, stop-time fields, bus/rail/combined routing mode, Google sign-in foundation, owner status page, and backend GTFS routing engine.

## Important limitations
- Demo scenario routes and schedules are fictional UI samples, not real transit service data.
- Real GTFS route planning still requires real regional GTFS feeds.
- Place search uses Photon by default; it requires internet and is subject to provider availability and terms.
- Saved routes and feedback remain in the current browser's local storage. They are not synced to the owner or other devices.
- `.broute` is a versioned JSON export/import format; cloud sync, 1GB quota enforcement, history migration, and conflict resolution are not implemented yet.
- API keys and Google OAuth are not required to use `?demo=1` sample routes. Actual Google sign-in and connected provider APIs still require owner configuration.

## 최종 점검 보완
- API `/health` 및 관리자 상태 응답의 앱 버전을 1.4.0으로 통일했습니다.
- Leaflet/지도 객체가 준비되지 않은 경우 경로선 렌더링을 건너뛰도록 방어 처리를 추가했습니다.
- Python 컴파일, JavaScript 구문, API 기본 권한, 3개 시연 경로 시간 합계 검사를 다시 수행했습니다.
- EdgeOne 배포 및 실제 Google OAuth 연결 테스트는 수행하지 않았습니다.
