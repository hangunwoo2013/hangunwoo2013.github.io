# B-ROUTE 2.0.0-beta.1 구현 현황

## 패키지 요약
- 기준: B-ROUTE 1.95.1 Email Delivery Hotfix
- 채널: `private-beta-candidate`
- 버전: `2.0.0-beta.1`
- 실제 배포: 하지 않음
- 베타 승인 게이트: 기본 `false`
- 익명 Cloud Run 접근: beta branch 기본 차단

## 이번 버전에서 추가/정리한 점
- 웹·API·관리자·manifest·service worker 버전 표기를 2.0.0-beta.1로 맞춤.
- GTFS Worker heartbeat는 API의 런타임 버전을 사용해 불일치했던 1.94.0 하드코딩을 제거.
- UI에 후보 버전과 시간표 데이터 범위 제한을 표시.
- beta 배포 시 익명 접근은 기본 비활성화하고, 승인된 테스터를 위한 Cloud Run Invoker 권한을 요구.
- 베타 승인/배포/공개 접근은 각각 별도 설정값으로 분리.

## 검증된 범위
- 로컬 pytest 및 10개 독립 회귀 시나리오
- Python 구문/런타임 모듈 import
- Node 기반 HTML inline JS와 service worker 구문 검사(회귀 runner)
- HTML id/reference 검사
- GitHub Actions workflow YAML 및 내장 Bash 문법 검사
- API/웹/관리자/manifest/service worker 기본 HTTP smoke test
- dotfile 및 서버 소스 정적 파일 노출 차단 smoke test
- GTFS Worker heartbeat 버전 일치 회귀검사
- beta release/deploy/public access gate 정적 검사

## 미검증 / 차단 항목
- GitHub 원격 CI 및 실제 Docker image build
- Google/Naver/Microsoft 실계정 OAuth
- Resend DNS 인증, 실발송, 실 webhook 전달
- 운영 PostgreSQL, backup/restore, COS 실제 업로드·다운로드
- 전국 지역별 버스/철도 GTFS 수집 범위, 라이선스, 실제 시간표 경로 정확성
- GTFS Worker Cloud Run Job 배포/스케줄/권한/재시도
- 실제 모바일/PC 기기 및 외부 테스터 테스트
- Cloud Run 비용 경보와 결제 한도 정책

따라서 `2.0.0-beta.1`은 후보 코드 패키지이며, 외부 테스터에게 전국 경로 검색이 가능한 서비스로 안내하거나 공개 배포하면 안 된다.
