# B-ROUTE 2.0.0-beta.1 변경 기록

## 버전 전환
- 1.95.1 기준 코드를 유지한 채 비공개 베타 후보 버전 `2.0.0-beta.1`로 버전 정보를 통일했다.
- API, 웹, 관리자 화면, PWA manifest/service worker, GTFS worker heartbeat가 같은 런타임 버전을 사용한다.
- 2.0 Beta Test 후보임을 웹 화면과 관리자 화면에 표시하고 실제 시간표 데이터가 등록된 범위에서만 경로 검색이 가능하다는 안내를 추가했다.

## 베타 배포 보호
- `BETA_RELEASE_APPROVED=false` 기본값을 유지한다.
- GitHub Actions의 beta 배포는 기존 `GCP_DEPLOY_ENABLED` 및 `BETA_DEPLOY_APPROVED` 이중 승인 조건을 유지한다.
- beta branch의 Cloud Run 배포는 기본적으로 `--no-allow-unauthenticated`를 사용한다. 승인된 테스터만 Cloud Run Invoker 권한을 받아야 접근할 수 있다. `BETA_PUBLIC_ACCESS_APPROVED=true`는 익명 접근을 허용하기로 명시적으로 결정한 경우에만 설정한다.
- main/production 배포 동작은 기존 공개 서비스 정책을 유지한다.

## 추가 검사
- GTFS Worker heartbeat 버전이 API 버전과 일치하는지 회귀검사를 추가했다. 이전 worker 코드에 남아 있던 `1.94.0` 하드코딩 버전을 제거했다.
- 베타 버전 metadata와 배포 승인/접근 게이트를 검사하도록 release metadata 검사를 강화했다.

- Cloud Run workflow의 버전 주입을 브랜치별로 분리했다. `beta` 브랜치는 `2.0.0-beta.1`, `main` 브랜치는 안정 버전 `2.0.0`으로 표시되며, 기존 수동 배포 승인 조건은 유지한다.
