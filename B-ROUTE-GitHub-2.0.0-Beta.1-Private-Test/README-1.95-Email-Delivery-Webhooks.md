# B-ROUTE 1.95 — Email Delivery Webhooks

## 이번 버전
- Resend 웹훅 `/api/webhooks/resend` 추가(내부 API 경로 `/webhooks/resend`를 단일 서버가 `/api` 아래에 마운트): `email.sent`, `email.delivered`, `email.delivery_delayed`, `email.bounced`, `email.complained`, `email.failed`, `email.suppressed` 처리
- Svix 서명 검증, 기본 5분 timestamp 허용 범위, 256KB 요청 본문 제한
- 이벤트 ID 중복 방지 및 늦게 도착한 이벤트가 상태를 되돌리지 못하도록 상태 우선순위 적용
- 발송 API 응답보다 웹훅이 먼저 도착하는 경합 상황을 메시지 ID 확인 후 재조정
- 기존 1.94 DB 자동 마이그레이션: 전달·반송·스팸 신고 시각과 마지막 이벤트 기록
- `broute.site.app@gmail.com`을 초대메일 Reply-To 및 문의 주소로 기본 지정
- 총괄자 관리판에 Reply-To, 웹훅 연결 여부, 전달 상태별 건수 표시

## Gmail 주소 사용 방법
사용자가 제공한 `broute.site.app@gmail.com`은 B-ROUTE의 회신·문의 주소로 설정한다. Resend의 `From` 주소는 Resend에서 인증한 도메인 주소를 사용해야 하므로 Gmail 주소를 `From`에 직접 넣지 않는다. 예를 들어 `B-ROUTE <invite@본인소유도메인>`을 `INVITE_FROM_EMAIL`에 설정하고 `INVITE_REPLY_TO_EMAIL=broute.site.app@gmail.com`으로 둔다. 도메인이 없다면 Gmail API/OAuth를 이용한 직접 발송 구현을 별도 선택지로 검토해야 한다.

## 서버 Secret
- `RESEND_API_KEY`: Resend API 키
- `INVITE_FROM_EMAIL`: Resend에서 인증한 도메인의 발신 주소
- `INVITE_REPLY_TO_EMAIL`: `broute.site.app@gmail.com`
- `RESEND_WEBHOOK_SECRET`: Resend 웹훅 설정에서 발급한 `whsec_...` 값
- `APP_ORIGIN`: 실제 서비스 HTTPS 주소

Resend 대시보드에서 Webhook URL을 `https://서비스도메인/api/webhooks/resend`로 등록하고 `email.sent`, `email.delivered`, `email.delivery_delayed`, `email.bounced`, `email.complained`, `email.failed`, `email.suppressed` 이벤트를 구독한다. 공개 엔드포인트지만 서명 검증이 통과해야만 이벤트를 처리한다.

## 상태 의미
- `accepted`: Resend API가 메일 요청을 접수한 상태(수신 서버 전달을 뜻하지 않음)
- `sent`: 공급자가 발송 처리
- `delivered`: 받는 쪽 메일 서버가 전달을 확인(받은편지함 도착까지 보장하지 않음)
- `delivery_delayed`: 전달 지연
- `bounced`: 반송
- `complained`: 스팸 신고
- `failed`: 공급자 발송 실패
- `suppressed`: 공급자의 억제 목록 등으로 발송 생략

반송·스팸 신고·실패·억제 상태의 초대 링크는 수락되지 않도록 차단한다. 소유자가 재전송하면 새 토큰이 발급되고 이전 링크는 무효화된다.

## 테스트
`python -m pytest -q`로 1.94의 기존 회귀 시나리오와 1.95 웹훅 서명·중복·이벤트 순서·경합 테스트를 함께 실행한다. 실제 Resend 발송과 실제 웹훅은 키 등록 후 비공개 베타 전 별도로 확인해야 한다.
