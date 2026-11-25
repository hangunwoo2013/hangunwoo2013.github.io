# B-ROUTE 2.0.0-beta.1 변경 기록

## 버전 전환
- 1.95.1 기준 코드를 `2.0.0-beta.1`로 전환.
- API, 웹, 관리자 화면, PWA manifest/service worker, GTFS Worker heartbeat 버전을 일치.
- 2.0 Beta Test를 정식 공개 전 비공개 테스터 피드백 단계로 명확히 정의.

## 테스트 실행 안정화
- 재검사에서 회귀 시나리오 하위 프로세스의 `PYTHONPATH`에 프로젝트 루트가 빠지는 문제를 발견.
- 프로젝트 루트와 `cloud-functions` 경로를 모두 전달하도록 수정.
- 수정 후 pytest 1건, 독립 회귀 10개 시나리오 및 반복 검사를 통과.

## 베타 보호와 범위
- `BETA_RELEASE_APPROVED=false` 기본값 유지.
- beta Cloud Run 배포 workflow는 명시적 승인 변수 조건을 유지.
- beta Cloud Run 익명 접근은 기본 차단.
- 실제 외부 API/계정/메일/DB/COS 연결 및 실제 배포는 이번 소스 검증에서 실행하지 않음. 이 작업은 2.0 Beta Test 단계의 다음 개발 항목으로 분리.
