# B-ROUTE 1.95 내부 테스트 보고서

## 실행 결과
- `python -m pytest -q`: 통과 (통합 테스트 진입점 1개)
- `python scripts/run_regression.py`: 전체 통과
- 독립 회귀 시나리오: 10개 통과
- Python compileall: 통과
- Node.js 인라인 JavaScript 및 서비스워커 구문 검사: 통과
- HTML ID 중복 검사: 통과
- GitHub Actions YAML 및 Workflow 내 Bash 구문 검사: 통과
- 릴리스 버전·환경변수 예시·비밀 파일 포함 여부 검사: 통과
- ZIP 패키지 무결성 검사: 패키징 후 별도 실행 예정

## 1.95 신규 검증
- Resend/Svix 서명 유효성 및 잘못된 서명 거부
- 웹훅 타임스탬프 허용 범위 초과 거부
- 같은 webhook event ID 재전송 중복 처리 방지
- `email.delivered`, `email.bounced` 상태 반영
- 이벤트 순서가 뒤바뀌어도 더 낮은 상태로 회귀하지 않음
- 메일 발송 API 응답보다 웹훅이 먼저 도착하는 경합 상황 복구
- Gmail 업무용 주소가 Reply-To로 전송 payload에 포함됨
- 기존 1.94 DB 자동 마이그레이션

## 미실시 / 남은 검증
- 실제 Resend API 키를 사용한 이메일 발송
- 실제 수신 메일함 도착 확인 및 실제 Resend 웹훅 전달
- Resend 발신 도메인 DNS 인증(SPF/DKIM/DMARC)
- 실제 PostgreSQL 운영 DB 동시성 및 마이그레이션
- Docker 이미지 빌드(현재 실행 환경에서 Docker 엔진 사용 불가)
- 실제 GitHub Actions 실행 및 Cloud Run 배포
- Google·네이버·Microsoft 실계정 OAuth, COS, 교통 API 실서버 호출

따라서 이번 결과는 **로컬 자동검사 통과**를 의미하며, 실제 이메일 전달·운영 인프라 검증 완료를 의미하지 않는다.
