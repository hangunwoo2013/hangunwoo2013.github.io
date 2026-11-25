# B-ROUTE 1.7 내부 테스트 보고서

## 테스트 환경
- Python 로컬 실행
- FastAPI TestClient
- SQLite 개발 DB
- Fake COS 객체/멀티파트 응답
- 합성 GTFS ZIP
- EdgeOne에 배포하지 않음
- 실제 COS/PostgreSQL 계정에 접속하지 않음

## 기본 통합 테스트
- COS multipart 초기화 API
- part URL 발급 API
- COS part 목록 기반 완료 확인
- queue 상태 등록
- Worker가 COS 가상 객체를 내려받음
- ZIP 경로/크기/압축 및 GTFS 구조 검사
- 5,000행 배치 importer 경로 실행(샘플은 소량 행)
- feed 비활성 적재 후 release 완료 시 활성화
- job completed 상태 및 SHA-256 기록
- heartbeat 생성 및 진행 상태 갱신

## 보안/실패 테스트 체크리스트
- 일반 Google 계정의 admin endpoint 접근 거부
- 미완료/누락된 part를 COS complete 전에 거부
- part 크기 불일치 거부
- 다른 사용자 세션의 staging 작업 목록/서명 URL 발급 거부 (실행)
- part 누락 및 part 크기 불일치 거부 (실행)
- ZIP 경로 탈출 거부 (실행)
- 중복 ID/참조 누락 GTFS, 압축 폭탄, Worker 중간 실패의 활성화 방지는 추가 시험 필요

실행한 모의 COS/TestClient 검사는 `tests/test_gtfs_staging_17.py`에 포함됩니다. 실제 제공자/COS/PostgreSQL/EdgeOne 테스트가 아닙니다.

## 정직한 제한
구조 검증은 GTFS가 실제 운영기관 시간표와 일치함을 보증하지 않습니다. 운영 데이터 수백만 행에 대한 성능은 검증되지 않았으며, Worker 디스크/CPU/메모리/비용을 실제 데이터로 측정해야 합니다.
