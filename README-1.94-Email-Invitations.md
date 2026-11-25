# B-ROUTE 1.94 — 이메일 초대 및 프로젝트 참가

## 목표

프로젝트 초대의 이메일 소유 확인을 별도 인증번호 입력 대신 **초대 메일함의 `프로젝트 참가하기` 버튼**으로 처리한다. 메일 링크를 열어 메일함 접근을 확인한 다음, Google·네이버·Microsoft 중 사용자가 선택한 B-ROUTE 계정으로 로그인하고 참가를 확정한다.

## 사용자 흐름

1. 프로젝트 Owner가 구성원 초대에 수신 이메일과 `Editor` 또는 `Viewer` 권한을 입력한다.
2. B-ROUTE 서버가 Resend 이메일 API로 초대 메일을 보낸다.
3. 메일에는 `프로젝트 참가하기` 버튼이 들어간다. 링크는 7일 동안 유효한 일회용 capability token을 포함한다.
4. 버튼을 누르면 B-ROUTE가 초대 정보를 보여준다. 이 GET 요청만으로 구성원이 추가되거나 초대가 소비되지는 않는다.
5. 로그인하지 않았다면 원하는 Google·네이버·Microsoft 계정으로 로그인한다. 네이버·Microsoft OAuth 복귀 주소에는 초대 fragment가 보존된다.
6. 로그인 이메일과 초대 주소가 같으면 참가 버튼을 눌러 바로 수락할 수 있다. 다르면 현재 로그인 계정에 프로젝트 권한을 부여할 것인지 추가 확인한다.
7. 서버는 일회용 토큰, 만료/취소/재발송 상태, 현재 로그인한 계정, 프로젝트 상태와 구성원 한도를 다시 확인한 뒤 한 번만 수락한다.

### 이메일 주소와 B-ROUTE 계정이 다를 때

초대 메일의 일회용 링크를 여는 것이 **초대 메일함에 접근할 수 있다는 증거**다. OAuth 공급자가 알려주는 이메일을 모든 공급자에서 동일한 수준의 본인 확인 수단으로 간주하지 않는다. 특히 Microsoft 문서는 `email` claim이 변경 가능하고 정확성을 보장하지 않으며 권한 판단에 사용하지 말라고 설명한다.

따라서 현재 로그인 계정의 이메일이 초대 주소와 다르면 화면에서 계정 정보를 다시 보여주고, 사용자가 현재 B-ROUTE 계정에 권한을 붙이는 것을 명시적으로 확인해야 한다. 이 경우 프로젝트 구성원에는 실제 로그인된 계정의 고유 사용자 ID와 계정 이메일이 기록되고, 초대 기록에는 초대 대상 이메일이 남는다. 초대 메일 링크를 다른 사람에게 전달하면 그 사람에게 초대를 넘기는 것과 같으므로 링크를 전달하지 않아야 한다.

## 링크 보안

- 무작위 일회용 토큰은 메일에만 전달하고 DB에는 SHA-256 해시만 저장한다.
- 새 초대 메일을 재전송하면 새 토큰으로 교체하고 이전 메일 링크는 즉시 무효화한다.
- 초대 취소, 만료(7일), 이미 사용된 링크는 다시 수락할 수 없다.
- 초대 정보 조회는 GET이며 상태를 변경하지 않는다. 메일 보안 스캐너가 링크를 열어도 초대가 소비되지 않는다.
- 새 메일 링크는 `/#invite=...` URL fragment에 토큰을 넣는다. Fragment는 초기 페이지 요청/Referer에 포함되지 않는다. 프런트엔드는 토큰을 same-origin `POST /project-invites/preview` 및 `POST /project-invites/accept`의 JSON 본문으로 전달하며, 신규 UI는 토큰을 API URL 경로에 넣지 않는다.
- 구버전 1.9x 클라이언트 호환을 위해 토큰이 URL 경로에 들어가는 구형 GET/POST 라우트는 당분간 남겨두었지만 신규 UI에서는 사용하지 않는다.
- 참가 완료 후 브라우저 주소에서 초대 토큰을 지운다.
- POST 요청은 same-origin 검사와 로그인 세션 검사를 통과해야 한다.
- 초대 재전송 결과가 늦게 도착해도 이전 이메일 요청의 결과가 최신 초대 상태를 덮어쓰지 않도록 `current_email_event_id`를 확인한다.

## Resend 설정 (서버 Secret 전용)

`.env.example`을 참고해 운영 서버의 Secret/환경변수에 다음 값을 등록한다.

| 변수 | 설명 |
|---|---|
| `RESEND_API_KEY` | Resend API 키. 브라우저나 GitHub 저장소에 넣지 않는다. |
| `INVITE_FROM_EMAIL` | Resend에서 발신용 인증을 마친 도메인의 주소 |
| `INVITE_FROM_NAME` | 발신자 표시 이름(기본 B-ROUTE) |
| `INVITE_EMAIL_DAILY_LIMIT` | B-ROUTE 앱 자체 일일 제한. 기본 80, 서버 코드에서 최대 100으로 제한 |
| `APP_ORIGIN` | 사용자가 실제 접속하는 HTTPS 서비스 주소 |

Resend 대시보드에서 도메인을 추가한 뒤 DNS에 SPF·DKIM 레코드를 등록하고 발신 도메인을 인증해야 한다. DMARC도 설정하는 것을 권장한다. `INVITE_FROM_EMAIL`은 인증된 발신 도메인에 속해야 한다.

Resend API 키는 서버에서만 Bearer 인증으로 사용한다. 이메일 요청에는 고유 `Idempotency-Key`를 포함해 동일 요청 재시도에 따른 중복 발송을 줄인다.

### 무료 한도 보호

Resend 공식 가격 안내는 Free 요금제에 월 3,000건과 일 100건 한도를 표시한다. B-ROUTE는 일일 상한을 기본 80건으로 낮춰 여유를 둔다. 다만 Resend 팀/계정에서 다른 앱도 이메일을 보내면 해당 사용량은 같은 제공자 한도를 공유할 수 있다. 따라서 B-ROUTE 전용 Resend 팀을 사용하거나 제공자 대시보드 사용량을 함께 확인한다. 유료 플랜·Transactional Overages·자동 초과 결제는 켜지 않는다.

## 발송 상태의 의미

현재 `email_status=accepted`는 **Resend API가 발송 요청을 받아 이메일 ID를 반환했다**는 뜻이다. 수신자 메일함 도착(Delivered)을 보증하는 뜻은 아니다. 스팸함/프로모션/기타함, 회사 메일 보안 격리, 주소 오타, 반송 등이 있을 수 있다. 총괄자는 Resend 대시보드의 이메일 기록으로 실제 전송·배달·반송 상태를 확인해야 한다.

1.94에는 Resend Delivery/Bounce Webhook 연동이 아직 없다. 추후 웹훅 서명 검증과 이벤트 상태 반영을 추가하면 관리판에서 `요청 접수 / 배달 / 지연 / 반송 / 억제`를 구분할 수 있다.

## 로컬 테스트

실제 이메일은 발송하지 않는다. `tests/scenarios/scenario_project_invite_email_194.py`가 `httpx.MockTransport`로 Resend API 응답을 가로채며 다음을 확인한다.

- 1.93 DB에서 초대 이메일 컬럼 자동 마이그레이션
- 발신 API 요청/키/Idempotency-Key 구성
- 메일 HTML과 텍스트에 참가 버튼 포함
- API 응답에 원문 초대 토큰/URL 미노출
- Fragment 초대 링크, POST 본문 기반 미리보기/수락(토큰 URL 비노출), GET 미소비, no-store/referrer 정책
- 초대 대상과 다른 로그인 계정의 명시적 계정 선택
- 일회용 수락, 재전송 시 이전 토큰 무효화
- 이메일 전송 실패, 재전송, 일일 한도, 권한 차단
- 늦게 완료된 이전 발송 결과가 최신 초대 상태를 덮어쓰지 않는지

전체 로컬 검사 실행:

```bash
pip install -r cloud-functions/requirements.txt -r requirements-ci.txt
python -m pytest -q
```

실제 Resend 키, 인증된 도메인, PostgreSQL, OAuth 실계정, 운영 호스팅을 연결한 테스트는 별도다. 2.0 Beta Test 전까지 배포 테스트는 보류한다.

## 공식 참고 자료

- [Resend 가격 및 무료 발송 한도](https://resend.com/pricing) — Free 월 3,000건, 일 100건 표시
- [Resend 도메인 인증 및 DNS 안내](https://resend.com/guides/email/deliverability/why-emails-go-to-spam) — SPF·DKIM과 DMARC 설정 참고
- [Resend Idempotency Keys](https://resend.com/changelog/idempotency-keys) — 재시도 중 중복 이메일 방지
- [Microsoft ID token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference) — `email` claim은 변할 수 있고 정확성이 보장되지 않으므로 사용자 식별에는 `sub`/`oid` 사용
