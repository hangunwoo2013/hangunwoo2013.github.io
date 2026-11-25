# B-ROUTE 1.93 변경 사항

## 버전 정책
- 1.9x: 실제 정식 배포 전 개발·오류 수정·기반 강화
- 2.0 Beta Test: 실제 서비스에 가까운 비공개 지인 테스트
- 2.0: 베타 피드백 반영 후 정식 공개
- 1.93에서도 EdgeOne/Cloud Run 실제 배포 테스트는 하지 않음

## 프로젝트 공동 편집 안정성
- 프로젝트 경로 수정 요청에 `expected_version` 필수
- 프로젝트 단위 DB 잠금 후 현재 버전 비교
- 최신 버전과 다른 요청은 HTTP 409 Conflict로 거부
- 성공한 업데이트만 이전 스냅샷을 이력에 기록
- 버전 이력에 제목과 실제 이전 편집자 ID 저장
- 이전 버전 복구 시 제목·경로 설정·검색 결과를 함께 복원
- 기존 1.92 `project_route_versions` 테이블에 `title`을 추가하는 호환 마이그레이션
- 프런트엔드는 열어 둔 버전을 보관하고 저장 시 함께 전송

## 지속적인 실행 검사
- 기존 테스트 스크립트를 독립 프로세스의 scenario로 분리
- `python -m pytest -q` 단일 진입점 추가
- Python compileall 검사
- index/admin/service worker JavaScript 구문 검사
- HTML ID 중복 검사
- GitHub Actions YAML 및 포함된 Bash 문법 검사
- 앱/관리자/manifest/service worker 버전 일치 검사
- `.env` 실파일 포함 여부 점검
- API·OAuth·GTFS·철도 환승·권한·동시 편집·DB 마이그레이션 시나리오 실행
- CI에서 애플리케이션 및 GTFS Worker Docker 이미지 빌드

## 테스트에서 발견하여 반영한 문제
- 기존 테스트 모듈이 pytest 수집 단계에 실행되어 import path와 환경변수 상태에 따라 실패할 수 있던 문제를 분리
- route history가 과거 경로 제목을 저장하지 않던 문제 수정
- 버전 이력의 `saved_by`에 이전 편집자가 아닌 현재 저장 요청자를 기록하던 문제 수정
