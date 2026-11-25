# B-ROUTE 1.95.1 핫픽스 안내

이 ZIP은 사용자가 제공한 `B-ROUTE-GitHub-1.95-Email-Delivery-Webhooks.zip`을 기준으로 기존 기능을 유지하면서 오류를 보완한 1.95.1 패치다.

## 수정한 항목

1. **Cloud Run의 Resend 설정 연결**: `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `INVITE_FROM_EMAIL`을 Secret Manager에서 서버 환경변수로 연결할 수 있도록 배포 workflow를 수정했다. GitHub Variables에는 Secret 원문이 아니라 Secret Manager 리소스 이름을 넣는다.
2. **Webhook URL 안내 오류**: 외부에서 등록할 주소를 `https://서비스도메인/api/webhooks/resend`로 바로잡았다. API 앱 내부 경로는 `/webhooks/resend`이지만 웹앱 서버가 `/api` 아래에 마운트한다.
3. **억제 이벤트 상태 반영**: `email.suppressed`를 종료 상태 우선순위에 추가해 프로젝트 초대의 전달 상태 및 오류 코드에 반영한다.
4. **빈 웹훅 Secret 거부**: `whsec_`만 있고 Base64 본문이 비어 있거나 잘못된 Secret은 준비 상태에서만이 아니라 실제 서명 검증 요청에서도 HTTP 503으로 거부한다.
5. **배포 준비 상태 일관화**: 공개 health와 총괄자 관리판에서 동일한 readiness 기준을 사용한다.
6. **GTFS worker 이미지 빌드 안전장치**: 기본 웹앱 배포에서 worker 이미지가 자동 빌드되지 않는다. 별도 준비가 끝나고 `GTFS_WORKER_IMAGE_BUILD_ENABLED=true`를 지정한 경우에만 실행한다.
7. **회귀검사 보강**: Python 3.11 문법 호환성, HTML DOM 참조, Workflow YAML 및 내장 Bash, Webhook 경로·서명·상태, 주요 API와 프로젝트 협업 동작을 검사한다.

## Resend 설정 요약

- `RESEND_API_KEY`: Secret Manager에 저장
- `INVITE_FROM_EMAIL`: Resend에서 발신 도메인 인증을 마친 주소로 설정하고 Secret Manager에 저장
- `RESEND_WEBHOOK_SECRET`: Resend에서 발급한 `whsec_...` 값으로 Secret Manager에 저장
- `INVITE_REPLY_TO_EMAIL`: 기본값 `broute.site.app@gmail.com`
- GitHub Variables: `RESEND_API_KEY_SECRET_NAME`, `INVITE_FROM_EMAIL_SECRET_NAME`, `RESEND_WEBHOOK_SECRET_NAME`에 각 Secret Manager 리소스 이름 입력
- Resend Webhook URL: `https://서비스도메인/api/webhooks/resend`

Gmail 주소는 회신 주소로만 사용한다. Resend의 `From` 주소로 직접 사용하지 않는다.

상세 절차는 `ADMIN-API-LOGIN-SETUP.md`, 상세 변경 목록은 `CHANGELOG-Local-1.95.1.md`를 참고한다.

## 검사 결과와 한계

로컬 검사에서는 Python 3.11 문법 구문검사, Node 기반 프런트엔드 구문검사, HTML ID 연결, GitHub Actions YAML/Bash 구문검사, 10개 독립 회귀 시나리오 및 pytest를 통과했다. 다만 이 작업 환경에서는 Docker 실행파일이 없고 브라우저 자동화가 관리자 정책에 막혀 있어 실제 컨테이너 빌드와 화면 렌더링 검증은 수행하지 못했다. Cloud Run, GitHub Actions 원격 실행, Resend 실발송/실 webhook, 실제 OAuth, PostgreSQL 및 Tencent COS 운영 연결도 실행하지 않았다. 따라서 이 패치는 로컬 코드·회귀검사 수정본이며 배포 검증 완료를 의미하지 않는다.
