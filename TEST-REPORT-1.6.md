# B-ROUTE 1.6 내부 테스트 보고서

> 모든 테스트는 로컬 개발용 SQLite와 작은 가상 GTFS 샘플을 사용했습니다. EdgeOne에 배포하거나 실제 외부 API·운영 계정·COS·PostgreSQL을 연결하지 않았습니다.

## 정적 검사
- `python -m py_compile cloud-functions/api/index.py`: 통과
- Python 3.10 문법 모드 AST parse: 통과
- 메인 앱 inline JavaScript `node --check`: 통과
- 관리자 inline JavaScript `node --check`: 통과
- `index.html`, `admin.html` 중복 ID: 0개
- ZIP 무결성: 패키징 시 테스트 예정

## API 통합 테스트
- 관리자 로그인 쿠키 모의 및 총괄자 권한 API 테스트
- `data_sources` 출처 등록/목록/비활성화
- 출처 ID를 제공하지 않은 GTFS 사전검증/가져오기 경로는 필수 입력 검증으로 거부
- 올바른 GTFS ZIP 사전검증: 통과
- 손상된 ZIP: 400으로 거부
- GTFS import: stops 2, routes 1, trips 1, stop_times 2 예제 성공
- 동일 데이터 출처에 v1, v2 import: v2만 활성, v1은 아카이브 상태로 보존
- v1 릴리스 활성화: v1이 재활성화되고 v2는 비활성화됨
- import job/release 목록 조회: 통과
- 비활성 데이터 출처를 사용한 재가져오기: 거부
- 버스만 등록된 데이터셋에서 `mode=bus` 경로: 성공
- 같은 데이터셋에서 `mode=rail`: 404, 버스 노선을 철도 경로로 잘못 표시하지 않음
- `/health` version `1.6.0`: 통과

## 검증의 범위와 한계
- 테스트용 GTFS는 가상으로 작성했으며 실제 노선·시간표·지역 커버리지 테스트가 아닙니다.
- PostgreSQL Adapter의 실제 원격 DB 동작 및 동시 import/rollback 경합은 검증하지 않았습니다.
- 5MB 초과 ZIP 업로드는 현재 기능 범위 밖입니다.
- 정적 GTFS 이외의 실시간 데이터, 운행 중단, 임시 시간표, 역내 통로, transfer rules, frequencies는 완전하게 처리하지 않습니다.
- 외부 지도 타일, 장소검색 공급자, Google 인증, 모바일 화면은 이 버전에서 재검증하지 않았습니다.
