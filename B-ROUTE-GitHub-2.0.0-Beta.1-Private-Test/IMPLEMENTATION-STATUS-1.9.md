# B-ROUTE 1.9 구현 현황

## 완료

- GTFS 시간표 그래프 기반 철도 다중환승 처리
- `transfers.txt` 규칙 0~5 지원 및 세부 우선순위
- 환승 금지(type 3), 최소환승시간(type 2), 시간 연계(type 1)
- 동일 차량 내 연결(type 4): 이전 운행편 끝/다음 운행편 시작 경계 확인, 다른 stop ID의 동일 역/근접 끝점 지원
- 하차 후 재승차(type 5) 규칙 및 최소시간
- `pathways.txt` 방향성·이동시간 기반 역 내부 연결
- 동일 feed 내부 임의 플랫폼 직선 연결 차단
- 버스 feed ↔ 철도 feed 출입구 기반 연결 후보
- 대중교통 탑승이 없는 도보-only 결과 차단
- bus / rail / transit 모드 필터 유지
- 버스 노선별 경유정류장 API의 FastAPI path parameter 선언 오류 수정
- TAGO HTTP 요청 계약 테스트: service URL, 필수 query, 인증키 서버 전용, 오류·timeout 처리
- 대용량 Worker와 직접 가져오기 검증 규칙 일치 보완(`stop_access=1` pathway endpoint 거부)
- API health/config 상태, 관리자 UI, manifest, service worker 캐시 버전 1.9 동기화

## 구현상 한계

- cross-feed 지리 연결의 보행시간은 직선거리 근사이며 실제 도보 경로가 아닙니다.
- 서로 다른 GTFS feed 사이 GTFS transfers.txt 규칙을 직접 결합하지 않습니다. 이 경우 출입구/좌표 연결을 사용하므로 운영 데이터 통합 시 하나의 표준 feed로 병합하거나 명시적 inter-feed transfer mapping이 필요합니다.
- `transfer_type=4`는 GTFS trip 경계와 동일 parent_station 또는 100m 이내 위치를 보수적으로 확인합니다. 데이터 오류가 있을 경우 실제 연속 운행을 놓칠 수 있습니다.
- GTFS Flex, frequencies.txt, levels.txt 기반 완전한 층별 접근성 그래프는 아직 지원하지 않습니다.
- TAGO direct origin-destination train query는 다중 환승 그래프가 아닙니다.
- KTDB의 2025-03 전국 파일럿 GTFS는 자료 신청·이용조건과 ID 변환이 필요하며, 2026년 현재 운행시간표 최신본으로 간주하면 안 됩니다.
- KRIC 환승·도시철도 시간표 API는 데이터 소스 조사만 완료했습니다. 실제 응답 필드 스키마와 인증이 확인된 뒤 연결해야 합니다.

## 테스트 범위

로컬 합성 데이터와 HTTP mock 기반. 실제 TAGO/KRIC/KTDB 네트워크 호출, 실 키 인증, 실제 전국 GTFS 가져오기, PostgreSQL/COS 운영 환경, EdgeOne 배포는 미실행.
