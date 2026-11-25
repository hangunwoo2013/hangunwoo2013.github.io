# B-ROUTE Local 1.9 변경사항

- GTFS rail transfer graph 보강
- transfers.txt 우선순위·환승 유형 0~5 규칙 적용
- linked trip type 4/5는 운행편 경계에서만 처리
- type 4의 다른 승강장 ID 동일 역 연결 처리
- pathways 및 cross-feed 버스-철도 연결 보강
- 도보-only 대중교통 결과 방지
- BusRoutespecificStopInformation API 경로 파라미터 오류 수정
- TAGO HTTP 요청 규약 및 오류 처리 테스트 추가
- stop_access pathway 검증을 Worker/직접 API 간 일치
- 버전 표시 및 Service Worker cache key 1.9로 갱신
