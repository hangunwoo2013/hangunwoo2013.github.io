# B-ROUTE 1.95 구현 현황

- Resend Delivery Webhook 수신 API 구현
- Svix HMAC 서명 및 timestamp 검증
- 이벤트 중복 처리 방지, 이벤트 순서 역전 보호
- delivered / delayed / bounced / complained / failed 상태 저장
- 1.94 DB 마이그레이션 추가
- 비즈니스 이메일 `broute.site.app@gmail.com` Reply-To 기본값 반영
- API/웹/PWA 버전 표시 1.95로 갱신
- 기존 프로젝트·OAuth·GTFS·철도·공유 회귀 테스트 유지

실제 Resend 계정, 도메인 인증, 웹훅 secret, PostgreSQL 운영 DB, COS, OAuth 실계정, Docker 빌드 및 배포는 아직 검증하지 않았다.
