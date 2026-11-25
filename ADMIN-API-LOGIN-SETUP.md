# B-ROUTE 1.95.1 총괄자 API 및 로그인 설정 참고

실제 운영에서는 GitHub Actions가 배포하는 서버(Cloud Run 등)의 Secret Manager/서버 환경변수를 사용한다. 브라우저 JavaScript와 GitHub 저장소에는 비밀값을 넣지 않는다. GTFS worker 이미지는 기본적으로 빌드하지 않으며, 별도 준비가 끝난 뒤 `GTFS_WORKER_IMAGE_BUILD_ENABLED=true`로 명시적으로 켤 수 있다.

## 공개 설정값(Repository Variables → 서버 환경변수)

- `GOOGLE_CLIENT_ID`
- `GOOGLE_ADMIN_SUB` (권장) 또는 검증된 `GOOGLE_ADMIN_EMAIL`
- `NAVER_CLIENT_ID`, `NAVER_REDIRECT_URI`
- `MICROSOFT_CLIENT_ID`, `MICROSOFT_TENANT`, `MICROSOFT_REDIRECT_URI`
- `APP_ORIGIN`
- `INVITE_REPLY_TO_EMAIL` (기본 `broute.site.app@gmail.com`)
- `INVITE_FROM_NAME` (기본 `B-ROUTE`)
- `INVITE_EMAIL_DAILY_LIMIT` (기본 80, 코드상 최대 100)
- `RESEND_WEBHOOK_TOLERANCE_SECONDS` (기본 300초)

## 서버 전용 Secret Manager 비밀값

- `SESSION_SECRET`
- `DATABASE_URL` (운영은 PostgreSQL 필요)
- `DATA_GO_KR_SERVICE_KEY`
- `RESEND_API_KEY` (프로젝트 초대 메일)
- `INVITE_FROM_EMAIL` (Resend에서 발신 인증을 완료한 도메인의 이메일)
- `RESEND_WEBHOOK_SECRET` (Resend 웹훅 서명키 `whsec_...`)
- 선택: `NAVER_CLIENT_SECRET`, `MICROSOFT_CLIENT_SECRET`, `KAKAO_REST_API_KEY`
- 선택: `COS_SECRET_ID`, `COS_SECRET_KEY`, `COS_BUCKET`, `COS_REGION`, `COS_SESSION_TOKEN`

## Resend 초대 메일 설정

1. Resend 계정에서 B-ROUTE 전용 발신 도메인을 추가한다.
2. DNS에 Resend가 제시하는 SPF·DKIM 레코드를 등록하고 도메인을 인증한다. DMARC도 권장한다.
3. Sending 권한에 필요한 최소 권한으로 API 키를 발급한다.
4. `RESEND_API_KEY`, `INVITE_FROM_EMAIL`, `RESEND_WEBHOOK_SECRET`을 서버 Secret Manager에 등록한다.
5. Cloud Run GitHub Actions의 Repository/Environment Variables에 Secret Manager 리소스 이름을 지정한다: `RESEND_API_KEY_SECRET_NAME`, `INVITE_FROM_EMAIL_SECRET_NAME`, `RESEND_WEBHOOK_SECRET_NAME`. 각 값은 Secret Manager에 만든 Secret 이름이며 비밀 원문이 아니다.
6. `INVITE_REPLY_TO_EMAIL`은 기본값 `broute.site.app@gmail.com`을 사용하거나 환경 변수로 변경한다.
7. Resend 대시보드에서 Webhook URL을 `https://서비스도메인/api/webhooks/resend`로 등록하고 위의 전달·반송·스팸·억제 이벤트를 구독한다.
8. 베타 준비 단계에서 Owner가 테스트 프로젝트에 Viewer 초대를 보내고, 수신·링크 미리보기·로그인 후 수락·전달 상태 갱신까지 확인한다.
9. `INVITE_EMAIL_DAILY_LIMIT=80`을 유지한다. 다른 프로젝트가 같은 Resend 팀을 사용하면 제공자 사용량을 공유할 수 있으므로 전용 팀 사용을 권장한다.
10. Resend의 유료 플랜/Transactional Overages/자동 초과 결제를 활성화하지 않는다.

Resend Free는 현재 공식 가격 안내에서 월 3,000건·일 100건을 표시한다. B-ROUTE 앱은 하루 80건을 상한으로 둔다. 다만 이 앱 상한은 Resend 팀 전체의 다른 발송량을 계산하지 않으므로, 제공자 대시보드도 확인해야 한다.

`email_status=accepted`는 Resend API가 이메일 요청을 수락했다는 뜻이며 실제 받은편지함 도착을 보장하지 않는다. 1.95.1은 서명된 delivery/bounce webhook을 지원하지만, 실제 전달 여부는 Resend 이벤트 로그와 B-ROUTE 관리판의 전달 상태를 함께 확인한다.

## 로그인 제공자

- Google GIS: 일반 이용자 로그인 및 글로벌 총괄자 식별
- Naver OIDC: `sub` 기반 사용자 식별
- Microsoft OIDC: 검증된 `tid` + `oid` 기반 사용자 식별

총괄자는 Google 계정만 허용한다. 서로 다른 공급자의 동일 이메일은 기본적으로 별도 B-ROUTE 계정이다.

## 프로젝트 초대 메일 흐름 (1.94)

- Owner가 초대 이메일과 Editor/Viewer 권한을 선택하면 서버가 Resend로 메일을 발송한다.
- 메일의 `프로젝트 참가하기` 버튼에 7일 만료 일회용 링크가 들어간다.
- 링크를 여는 GET 요청은 미리보기만 하며 초대를 수락하지 않는다.
- 메일 링크의 토큰이 메일함 접근 증거다. 로그인 후 Google·네이버·Microsoft 중 원하는 B-ROUTE 계정으로 참가를 확정한다.
- 로그인 이메일이 초대 이메일과 다르면 현재 로그인 계정에 권한을 부여할지 추가 확인한다.
- 재전송하면 새 토큰으로 바뀌고 이전 링크는 즉시 무효화된다.
- 메일 링크를 다른 사람에게 전달하면 초대 권한을 넘기는 것과 같으므로 전달하지 않는다.

## 배포 전 준비

Google/Naver/Microsoft의 OAuth redirect/origin에 베타·정식 도메인을 정확하게 등록한다. 실제 공급자 계정 인증, Resend 실제 발송, PostgreSQL/COS 연결, Cloud Run 배포는 1.95.1 제작 과정에서 실행하지 않았다. 2.0 Beta Test 준비 전까지 배포 검증은 보류한다.

## 공식 문서

- Resend 가격/무료 한도: https://resend.com/pricing
- Resend 발신 도메인·SPF/DKIM/DMARC: https://resend.com/guides/email/deliverability/why-emails-go-to-spam
- Resend 중복 발송 방지(Idempotency-Key): https://resend.com/changelog/idempotency-keys
- Microsoft ID 토큰의 email claim 주의사항: https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference
