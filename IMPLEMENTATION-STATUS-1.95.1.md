# B-ROUTE 1.95.1 구현 현황

1.95 기준에서 발견한 세 가지 운영 오류를 보완했다.

1. Cloud Run 배포에서 Resend API Key, Webhook Secret, 인증된 발신 주소를 선택적 Secret Manager 변수로 전달한다. 미설정 상태에서는 이메일 기능이 비활성화된 채로 배포가 가능하다.
2. 서버 전체 외부 URL은 API 앱이 `/api` 아래에 마운트되므로 Resend Webhook URL은 `https://서비스도메인/api/webhooks/resend`이다. 관련 안내와 검사를 수정했다.
3. `email.suppressed`는 반송/스팸 신고보다 높은 종료 상태로 저장되며 초대 상태에도 반영된다.

Reply-To 기본값은 `broute.site.app@gmail.com`이다. Resend From 주소는 Resend에서 인증한 도메인의 주소여야 하며 Secret Manager의 `INVITE_FROM_EMAIL`에 별도로 등록한다.

실제 Cloud Run 배포, Secret Manager 연결, Resend 실제 발송/웹훅 전송, PostgreSQL 운영환경은 이번 로컬 수정만으로 검증되지 않았다.

## GitHub Actions / Secret Manager 연결 방법

Cloud Run 배포 workflow는 아래 Secret Manager 이름을 GitHub Repository 또는 Environment Variables로 선택적으로 받는다.

- `RESEND_API_KEY_SECRET_NAME` → Secret Manager의 `RESEND_API_KEY`
- `INVITE_FROM_EMAIL_SECRET_NAME` → Secret Manager의 `INVITE_FROM_EMAIL`
- `RESEND_WEBHOOK_SECRET_NAME` → Secret Manager의 `RESEND_WEBHOOK_SECRET`

각 GitHub Variable 값은 Secret Manager 리소스의 **이름**이며, 실제 API 키/웹훅 키/발신 주소 원문은 Secret Manager에만 저장한다. Reply-To는 기본적으로 `broute.site.app@gmail.com`이다.

웹훅 서명 Secret은 `whsec_` 접두사와 Base64 본문 형식까지 확인하도록 강화했다. 형식이 잘못된 키는 베타 준비 체크에서 미설정으로 표시한다.

추가 점검에서 발견한 빈 `whsec_` Secret 허용 가능성을 수정했다. readiness 화면과 실제 webhook verifier가 같은 형식 검증 함수를 사용하며, 빈 Base64 본문은 HTTP 503으로 거부한다. 또한 Cloud Run 웹앱 배포 시 GTFS worker 이미지가 자동 빌드되지 않도록 하고, `GTFS_WORKER_IMAGE_BUILD_ENABLED=true`로 명시한 경우에만 빌드하도록 변경했다.
