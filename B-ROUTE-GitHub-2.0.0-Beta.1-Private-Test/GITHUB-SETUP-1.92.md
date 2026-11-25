# B-ROUTE 1.92 — GitHub Repository 및 자동 배포 설정

이 문서는 **사용자가 직접 GitHub/GCP 계정을 설정할 때** 필요한 안내입니다. 이 패키지 제작 과정에서는 GitHub 저장소를 만들거나 코드를 push하지 않았고 Cloud Run도 생성·배포하지 않았습니다.

## 1. GitHub 저장소 만들기

1. GitHub에서 새 Repository를 생성합니다. 처음에는 `Private`을 권장합니다.
2. 저장소 이름 예: `b-route`.
3. README, .gitignore, license를 GitHub에서 자동 생성하지 말고 빈 저장소로 시작합니다(현재 패키지에 문서와 .gitignore가 포함되어 있음).
4. ZIP을 원하는 작업 폴더에 풀고, 해당 폴더에서 다음을 실행합니다.

```bash
git init -b develop
git add .
git commit -m "B-ROUTE 1.92 initial production foundation"
git remote add origin https://github.com/YOUR_ACCOUNT/b-route.git
git push -u origin develop
```

`YOUR_ACCOUNT`와 저장소 주소는 본인 값으로 바꿉니다. 이 폴더에는 `.env`나 실제 API 키를 절대 복사하지 않습니다.

### 브랜치 운영

- `develop`: 1.92, 1.93… 개발. CI만 실행하고 배포하지 않습니다.
- `beta`: 2.0 Beta Test를 실제로 시작할 때 `develop`에서 분기/병합합니다. `BETA_DEPLOY_APPROVED=true`일 때만 베타 서비스 배포가 허용됩니다.
- `main`: 지인 베타 피드백과 최종 검증을 마친 후 정식 2.0 릴리스에 사용합니다. `PROD_DEPLOY_APPROVED=true`일 때만 운영 서비스 배포가 허용됩니다.

추천 보호 규칙: `beta`와 `main`은 직접 push를 제한하고 Pull Request + CI 통과를 요구합니다. `main` 병합은 별도 검토를 거치게 합니다.

## 2. Google Cloud 준비

1. Google Cloud 프로젝트를 만듭니다.
2. Billing Account를 연결합니다. Cloud Run 무료 제공량을 이용하더라도 Billing 설정이 필요할 수 있으며, 무료량 초과분이나 다른 서비스 비용은 청구될 수 있습니다.
3. Cloud Run, Artifact Registry, IAM Credentials, Secret Manager API를 활성화합니다.
4. Artifact Registry에 Docker 저장소 `broute`를 만듭니다.
5. Cloud Run에 사용할 배포 서비스 계정을 만들고 최소 권한을 부여합니다.
6. GitHub Actions가 서비스 계정 키 파일을 저장하지 않도록 Workload Identity Federation을 설정합니다.

GitHub Actions Secrets:

| Secret 이름 | 값 |
|---|---|
| `GCP_WIF_PROVIDER` | Workload Identity Provider 리소스 이름 |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | 배포 서비스 계정 이메일 |

배포 계정에는 Artifact Registry 이미지 업로드, Cloud Run 서비스 배포/수정, 해당 서비스 계정 사용, Secret Manager 비밀값 접근 권한이 필요합니다. 권한은 프로젝트 전체 Owner 대신 필요한 역할만 부여합니다.

## 3. GitHub Repository Variables

Repository → Settings → Secrets and variables → Actions → Variables에 아래 값을 등록합니다.

| Variable | 예시/설명 |
|---|---|
| `GCP_DEPLOY_ENABLED` | 처음에는 `false`, 배포 준비 완료 때만 `true` |
| `BETA_DEPLOY_APPROVED` | 베타 시작 승인 전 `false` |
| `PROD_DEPLOY_APPROVED` | 정식 공개 전 `false` |
| `BETA_RELEASE_APPROVED` | 실제 베타 체크리스트 통과 전 `false` |
| `GCP_PROJECT_ID` | Google Cloud 프로젝트 ID |
| `GCP_REGION` | `asia-northeast3` 권장(서울) |
| `GCP_ARTIFACT_REPOSITORY` | `broute` |
| `GCP_BETA_SERVICE` | `broute-beta` |
| `GCP_PROD_SERVICE` | `broute-prod` |
| `BETA_APP_ORIGIN` | 베타 서비스의 최종 HTTPS Origin |
| `PROD_APP_ORIGIN` | 정식 서비스의 최종 HTTPS Origin |
| `GOOGLE_CLIENT_ID` | Google Web OAuth Client ID |
| `GOOGLE_ADMIN_SUB` | 총괄자 Google 계정의 안정적인 `sub` 권장 |
| `GOOGLE_ADMIN_EMAIL` | `GOOGLE_ADMIN_SUB` 등록 전 임시 대체용(검증된 Google 이메일) |
| `NAVER_CLIENT_ID` | Naver Developers Client ID |
| `NAVER_REDIRECT_URI` | `https://베타주소/api/auth/naver/callback` |
| `MICROSOFT_CLIENT_ID` | Microsoft Entra Application Client ID |
| `MICROSOFT_TENANT` | 개인 Outlook + 조직 계정을 함께 허용하려면 `common` |
| `MICROSOFT_REDIRECT_URI` | `https://베타주소/api/auth/microsoft/callback` |
| `TAGO_TRAIN_SERVICE_NAME` | 기본 `TrainInfo` |

`NAVER_REDIRECT_URI`, `MICROSOFT_REDIRECT_URI`를 비워두면 Workflow가 `PUBLIC_ORIGIN`을 사용해 `/api/auth/{provider}/callback`을 자동 구성합니다. OAuth 공급자 콘솔에도 **동일한 주소**를 등록해야 합니다.

## 4. Google / Naver / Microsoft 로그인 콘솔

### Google

- OAuth Client 유형: Web application
- Authorized JavaScript origins: `BETA_APP_ORIGIN`, 나중에 `PROD_APP_ORIGIN`
- 이 앱은 Google Identity Services ID credential을 같은 출처의 `/api/auth/google`로 POST합니다. 임의 callback URL을 별도로 만들지 않습니다.
- 글로벌 총괄자는 Google 계정만 가능하도록 제한되어 있습니다.

### Naver

- Naver Developers에서 로그인/OIDC를 활성화합니다.
- Callback URL을 `https://베타주소/api/auth/naver/callback`으로 등록합니다.
- Client ID는 Repository Variable, Client Secret은 Secret Manager에 둡니다.
- Naver OIDC 고유 ID `sub`를 계정 키로 사용합니다. 프로필 이메일은 권한 확인 키가 아닙니다.

### Microsoft

- Entra App Registration의 Supported account types에서 개인 Microsoft 계정(Outlook.com/Hotmail 등)을 포함하는 멀티테넌트 + 개인 계정 유형을 선택합니다.
- Redirect URI(Web): `https://베타주소/api/auth/microsoft/callback`
- `MICROSOFT_TENANT=common`은 위 앱 등록 설정과 함께 사용합니다.
- Client Secret은 Secret Manager에 둡니다. `tid`와 `oid`를 계정 식별자로 사용합니다.

## 5. Secret Manager에 저장할 비밀값

기본 필수 Secret 이름:

- `DATABASE_URL`: PostgreSQL 연결 문자열(SSL 권장)
- `SESSION_SECRET`: 무작위 32바이트 이상 비밀값
- `DATA_GO_KR_SERVICE_KEY`: 공공데이터포털 서비스 키

선택 Secret:

- `NAVER_CLIENT_SECRET`
- `MICROSOFT_CLIENT_SECRET`
- `KAKAO_REST_API_KEY`
- `COS_SECRET_ID`, `COS_SECRET_KEY`, `COS_BUCKET`, `COS_REGION`, `COS_SESSION_TOKEN`

Workflow는 선택 Secret을 다음 Repository Variables에 지정된 Secret Manager 이름으로 연결합니다. 미등록 선택 기능은 비활성으로 유지할 수 있습니다.

- `NAVER_CLIENT_SECRET_NAME`
- `MICROSOFT_CLIENT_SECRET_NAME`
- `KAKAO_REST_API_KEY_NAME`
- `COS_SECRET_ID_NAME`, `COS_SECRET_KEY_NAME`, `COS_BUCKET_NAME`, `COS_REGION_NAME`, `COS_SESSION_TOKEN_NAME`

기본 Secret 이름을 바꾸려는 경우 `DATABASE_URL_SECRET_NAME`, `SESSION_SECRET_NAME`, `DATA_GO_KR_SERVICE_KEY_NAME`을 설정합니다.

실제 비밀값은 GitHub Repository Variables가 아니라 GitHub Secrets 또는 Google Secret Manager에 저장합니다. 현재 Workflow는 Secret Manager를 Cloud Run 서비스에 직접 연결합니다. `.env` 파일은 절대 commit하지 않습니다.

## 6. Cloud Run 서비스

- Beta: 서비스명 `broute-beta`
- Production: 서비스명 `broute-prod`
- 같은 서비스 이름으로 새 이미지를 배포하면 동일 서비스 URL에 새 Revision이 만들어집니다.
- API와 프런트엔드는 같은 Origin에 두고 `/api` 경로로 통신합니다.
- 컨테이너는 포트 8080을 사용합니다.
- PostgreSQL 없이는 운영 프로젝트/공유/클라우드/문의 API가 fail-closed 상태가 됩니다.

Workflow 파일은 배포 전에 `GCP_DEPLOY_ENABLED=true` 및 해당 브랜치 승인 변수를 확인합니다. 베타 배포는 `beta` 브랜치와 `BETA_DEPLOY_APPROVED=true`, 정식 배포는 `main`과 `PROD_DEPLOY_APPROVED=true`가 모두 필요합니다.

## 7. 자동 업데이트와 롤백

- `develop` push/PR: CI만 실행, 서버 배포 없음.
- `beta` push: `GCP_DEPLOY_ENABLED=true`와 `BETA_DEPLOY_APPROVED=true`일 때만 `broute-beta`에 배포.
- `main` push: `GCP_DEPLOY_ENABLED=true`와 `PROD_DEPLOY_APPROVED=true`일 때만 `broute-prod`에 배포.
- 배포는 동일 Cloud Run 서비스의 새 Revision을 생성하므로 URL을 바꾸지 않습니다.
- Actions → `Roll back B-ROUTE Cloud Run revision` → beta/production 선택 → 이전 Revision 이름 입력 → Run workflow.

실제 롤백 전 해당 Revision에 현재 Secret 이름, DB schema 호환성 및 데이터 migration 호환성이 남아 있는지 확인해야 합니다. 코드 Revision만 롤백해도 이미 적용된 데이터베이스 스키마 변경은 자동으로 되돌아가지 않습니다.

## 8. 중요한 미완료 운영 작업

이 패키지는 앱 컨테이너와 GTFS Worker 컨테이너를 빌드·push하는 Workflow를 준비하지만, Worker를 실행하는 Cloud Run Job과 반복 트리거(예: Scheduler)는 아직 생성하지 않습니다. GTFS 대용량 가져오기를 베타에서 사용하려면 별도 Job 실행·권한·비용·중복 실행·재시도 테스트를 완료해야 합니다.
