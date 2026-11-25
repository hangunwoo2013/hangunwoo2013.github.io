# B-ROUTE 1.7 구현 현황

## 구현된 내용
- 총괄자 전용 COS multipart staging API
- 브라우저에서 COS로 직접 part PUT 업로드
- 서버에서 COS part 목록과 실제 크기 검증 후 upload complete
- 작업 큐, 상태 조회, 재시도, 취소 및 COS 객체 정리
- 별도 Python GTFS Worker 및 Dockerfile
- 압축 ZIP 스트리밍 다운로드/해시 계산/안전성 검사
- GTFS 필수 파일·필수 열·중복 ID·노선/서비스/정류장/운행 참조 검사
- 검증용 SQLite 임시 인덱스 사용
- PostgreSQL/SQLite 개발환경 공통 adapter를 이용한 5,000행 기본 배치 적재
- 새 feed는 가져오기 완료까지 비활성, 완료 시 release와 feed 활성화를 최종 트랜잭션에서 수행
- Worker heartbeat 및 장시간 처리 중 작업 임대 갱신
- 관리자 화면에서 파일 업로드 진행률, 큐 상태, worker 상태, retry/cancel 확인
- staging 설정 상태 중복 키 제거, health readiness에 worker 상태 포함

## 확인된 로컬 테스트
- Fake COS를 이용한 init → sign → complete 흐름
- 합성 GTFS 다운로드/검증/배치 적재/release 활성화
- 작업 상태와 heartbeat 기록
- Python 컴파일 검사
- 메인/관리자 JavaScript 구문 검사
- 패키지 ZIP 무결성 검사

## 미완료/외부 연결 필요
- 실제 Tencent COS 계정/버킷/서명 URL/CORS 실검증
- 실제 PostgreSQL 실연결 및 동시 worker `SKIP LOCKED` 실검증
- 별도 Worker 호스트 구축, 재시작/로그/디스크 용량/비용 검증
- 대용량 운영 데이터셋으로 성능·실패 복구 테스트
- GTFS 실제 서비스 정확도 및 전국 커버리지 검증
- Worker가 마지막 처리 행부터 재개하는 체크포인트 기능 (현재 재시도는 동일 feed를 처음부터 재적재)
- GTFS frequencies/Flex 완전 지원, transfers/pathways 적용

## 출시 판단
1.7은 대용량 데이터 수집을 위한 개발 기반이며, 비공개 베타 승인 버전이 아닙니다. 실제 COS·PostgreSQL·Worker를 연결해 검증하기 전까지 `BETA_RELEASE_APPROVED=false`를 유지해야 합니다.
