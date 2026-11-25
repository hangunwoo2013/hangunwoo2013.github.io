# B-ROUTE 2.0.0-beta.1 구현 현황

## 패키지 상태
- 기준: B-ROUTE 1.95.1 Email Delivery Hotfix
- 채널: `private-beta-test`
- 버전: `2.0.0-beta.1`
- 목적: 정식 공개 전 비공개 테스터 피드백을 받는 2.0 Beta Test 단계의 기준 빌드
- 실제 외부 API 호출/배포: 이번 검증에서는 하지 않음
- 코드 수준 로컬 검사: 통과

## 이번에 정리한 항목
- 웹/API/관리자/manifest/service worker/GTFS Worker의 버전 표기를 `2.0.0-beta.1`로 정렬.
- GTFS Worker heartbeat는 API 런타임 버전을 사용.
- 베타 후보 표시 및 데이터 범위 안내.
- beta 배포 승인 및 익명 접근 제어는 기본 비활성화 상태 유지.
- 회귀 실행기의 하위 프로세스 `PYTHONPATH`에 프로젝트 루트와 API 디렉터리를 모두 포함해 테스트 실행 위치 의존 문제 수정.
- 2.0 Beta Test의 목표를 실 공개 전 피드백 단계로 문서에 명확히 반영.

## 확인된 검사
- pytest 1건 통과
- 10개 독립 회귀 시나리오 통과, 연속 반복 검사 통과
- Python/JavaScript 구문 및 Python 3.11 문법 검사
- HTML ID 및 JavaScript DOM 참조 검사
- GitHub Actions YAML/Bash 검사
- TestClient 기반 웹/API 통합 및 권한·경로·모의 교통 API 회귀
- ZIP 무결성

## 2.0 Beta Test 단계에서 시작할 작업
- 실제 공공 교통 API 연결 및 상품별 승인/응답 확인
- 실제 GTFS 전국 데이터 범위·라이선스·시간표 검토
- 실계정 OAuth, 이메일, PostgreSQL, COS 연동
- 별도 비공개 베타 환경 구성 및 초대 테스터 피드백 반영

위 외부 연결/운영 항목은 이번 로컬 검증에서 확인하지 않았으며 실패로 집계하지 않습니다. 실제 전국 경로검색 완성 또는 운영 안정성이 이미 검증되었다는 뜻도 아닙니다.
