# B-ROUTE 1.8 내부 테스트 보고서

## 테스트 환경
- 로컬 Python/FastAPI TestClient
- SQLite 임시 DB
- 합성 TAGO/공공데이터 응답 fixtures
- 실제 공공 API 키 미사용
- 실제 외부 API 네트워크 호출 미사용
- EdgeOne 배포 테스트 미실시

## 테스트 결과

1. TAGO BusRoute route catalog parameter mapping and normalization — PASS
2. TAGO TrainInfo city codes — PASS
3. TAGO TrainInfo station catalog — PASS
4. TAGO TrainInfo origin/destination train schedules — PASS
5. TAGO bus stop arrival normalization (seconds, remaining stops, vehicle) — PASS
6. provider response caching — PASS
7. owner-only provider probe / non-owner 403 — PASS
8. input validation for dates and station IDs — PASS
9. public status response excludes credentials — PASS
10. upstream result message key redaction — PASS
11. per-instance rate limiting and Retry-After — PASS
12. no configured API key fails closed with 503 — PASS
13. existing 1.7 COS staging/GTFS test suite — PASS
14. Python compilation — PASS
15. main/admin JavaScript parsing via Node — PASS
16. ZIP archive integrity — PASS (verified after packaging)

## Interpretation

PASS means the tested code path handled the synthetic data/conditions as expected. It does not prove the actual government provider schema, account authorization, daily quota, regional data coverage, or live timetables. Actual provider mapping remains subject to verification using the owner's approved key and real responses.
