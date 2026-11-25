# B-ROUTE 1.93 구현 현황

## 구현 완료
- 프로젝트 경로 optimistic concurrency (`expected_version`)
- PostgreSQL row lock / SQLite write reservation 기반 프로젝트 업데이트 직렬화
- 충돌 시 HTTP 409 응답
- 프런트엔드에 현재 route version 유지 및 전송
- 버전 이력에 title과 실제 이전 editor ID 보관
- restore 시 title/plan/result 동시 복구
- 1.92 DB에 project_route_versions.title을 추가하는 자동 호환 마이그레이션
- 고정된 regression suite 진입점 및 pytest wrapper
- JS/HTML/YAML/Bash/버전/secret hygiene 검사
- CI workflow에서 pytest 실행 후 두 컨테이너 이미지 빌드

## 로컬에서 통과한 확인
- Python 구문 검사
- index.html / admin.html inline JS 및 sw.js 구문 검사
- HTML 중복 ID 검사
- GitHub Actions YAML 및 embedded Bash syntax 검사
- 8개 격리 회귀 시나리오
- 동시 편집 테스트: 동일 expected_version으로 두 writer가 동시에 저장하면 하나만 성공, 하나는 409
- 1.92 DB 스키마에서 1.93 title 컬럼 자동 마이그레이션
- 기존 API, 인증, 프로젝트 권한, GTFS, 철도 환승 회귀 시나리오

## 미완료 / 외부환경 필요
- Docker 이미지 실제 빌드: 로컬 Docker CLI/daemon 부재로 미실행. GitHub Actions CI에서 수행하도록 설정
- 실제 GitHub 저장소 push 및 Actions 결과 확인 미실행
- Cloud Run 배포 및 URL 업데이트/롤백 리허설 미실행
- 실제 Google/Naver/Microsoft OAuth 실계정 검증 미실행
- 실제 PostgreSQL/COS/공공데이터 API 키를 이용한 연결 검증 미실행
- 초대 링크의 전달 대상 이메일 소유 검증(메일 OTP) 및 자동 이메일 발송 미구현
- 자동 병합은 미구현. 충돌을 감지하고 저장을 차단하는 방식

## 베타 진행 판단
1.93은 개발·검증 기반 버전이며 2.0 Beta Test 배포본이 아닙니다.
