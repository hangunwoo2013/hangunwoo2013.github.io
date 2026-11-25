# B-ROUTE 1.93 — GitHub 기반 개발·배포 구조

현재 프로젝트는 **1.93 개발 버전**입니다. 버전 정책은 다음과 같습니다.

- 1.9x(1.93, 1.94…): 실제 배포 전 기능 개발 및 오류 수정
- 2.0 Beta Test: 실제 서비스 기반의 비공개 지인 테스트
- 2.0: 베타 피드백 반영 및 최종 점검 후 정식 공개

2.0 Beta Test가 준비되기 전까지 실제 EdgeOne/Cloud Run 배포 테스트를 하지 않습니다. GitHub 저장소에 코드를 연결하고 CI를 사용하는 작업은 배포가 아닙니다.

## 권장 운영 구조

- **GitHub Repository:** 소스 코드, 이력, 이슈와 코드 리뷰
- **GitHub Actions:** 자동 테스트, 컨테이너 빌드, 승인된 배포 및 롤백 작업
- **Google Cloud Run:** FastAPI 서버와 정적 화면을 같은 출처에서 제공
- **Cloud SQL 또는 호환 PostgreSQL:** 계정·프로젝트·공유·문의·교통 데이터 메타데이터의 영구 저장
- **Tencent COS:** `.broute` 파일 및 대용량 GTFS 원본 보관
- **별도 GTFS Worker:** 대용량 GTFS 압축 해제·검증·배치 적재

GitHub는 코드 관리와 배포 자동화의 중심이고, 실제 FastAPI 앱을 실행하는 런타임은 Cloud Run입니다. GitHub Pages만으로는 현재 B-ROUTE의 FastAPI, OAuth 세션, 비밀키, 프로젝트 권한 및 데이터 처리를 운영하지 않습니다. GitHub Pages는 SaaS형 서비스의 백엔드 호스트를 대체하지 않습니다.

## 프로젝트 구조

- `index.html`, `admin.html`, `manifest.json`, `sw.js`, `icon.svg`: 프런트엔드 및 PWA 파일
- `cloud-functions/api/`: FastAPI API와 교통·계정·협업 기능
- `server.py`: `/api`와 정적 화면을 동일 출처로 제공하는 진입점
- `Dockerfile`: 웹/API 컨테이너
- `workers/`: 별도 GTFS 가져오기 Worker 및 컨테이너
- `tests/scenarios/`: 격리된 로컬 회귀 시나리오
- `scripts/run_regression.py`: 구문·정적·API·통합 회귀 검사 실행기
- `requirements-ci.txt`, `pytest.ini`: CI 전용 검사 환경
- `.github/workflows/ci.yml`: develop/beta/main 자동 검사
- `.github/workflows/deploy-cloud-run.yml`: 명시적으로 승인한 beta/main 배포
- `.github/workflows/rollback-cloud-run.yml`: 기존 Cloud Run Revision으로 트래픽 복구

`edgeone.json`은 1.92에서 제거했습니다. 기존 EdgeOne 전용 설정은 현재 배포 구조의 일부가 아닙니다.

## 로컬 실행

Python 3.11 이상을 사용합니다.

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r cloud-functions/requirements.txt -r requirements-ci.txt
cp .env.example .env
# .env에서 APP_ENV=development, SESSION_SECRET 등 로컬 값을 설정
PYTHONPATH=cloud-functions uvicorn server:app --host 127.0.0.1 --port 8080
```

브라우저에서 `http://127.0.0.1:8080`을 열고 상태 확인은 `/api/health`를 사용합니다. 코드 수정 후에는 배포 대신 먼저 `python -m pytest -q`로 전체 검사를 실행합니다. 로컬 SQLite는 개발·시험 전용입니다. 운영에서 `DATABASE_URL`이 PostgreSQL이 아니면 영구 기능은 차단됩니다.

## Docker 빌드

웹/API 이미지:

```bash
docker build -t broute-app:local .
```

GTFS Worker 이미지:

```bash
docker build -f workers/Dockerfile -t broute-gtfs-worker:local .
```

Worker 이미지를 빌드하는 것과 실제 Worker Job을 실행하는 것은 별개입니다. 운영 시 Cloud Run Job/Worker 실행 방식과 작업 스케줄을 따로 구성하고 실제 COS·PostgreSQL 통합 테스트를 통과해야 합니다.

## GitHub 설정

GitHub 설정은 `GITHUB-SETUP-1.92.md`를 참고합니다. 1.93 CI 검사 방법은 `README-1.93-테스트및협업안정화.md`를 참고합니다. 배포 Workflow는 기본적으로 꺼져 있습니다. GitHub Repository Variables의 `GCP_DEPLOY_ENABLED`, `BETA_DEPLOY_APPROVED`, `PROD_DEPLOY_APPROVED`가 모두 해당 환경에 맞게 켜져 있어야 동작합니다.

## 동일 주소 업데이트

기존 Cloud Run 서비스 이름(`broute-beta` 또는 `broute-prod`)에 새 이미지를 배포하면 새 Revision이 생성되고 서비스 URL은 유지됩니다. 문제가 생기면 `rollback-cloud-run.yml` 수동 Workflow에서 이전 Revision으로 트래픽을 돌릴 수 있습니다.

EdgeOne가 제공한 `*.edgeone.dev` 주소는 EdgeOne 소유 도메인이므로 GitHub/Cloud Run으로 이전할 수 없습니다. 본인이 소유한 도메인을 이미 사용하고 있다면 DNS/로드밸런서 구성을 한 번 변경해 새 호스트에 연결할 수 있습니다. 상세 내용은 `COST-AND-URL-MIGRATION-1.92.md`를 확인합니다.

## 현재 검증 범위

1.93에서는 Python/JavaScript 구문 검사, HTML ID 중복 검사, Workflow YAML/Bash 검사, 합성 OIDC/HTTP/COS 응답 테스트, 협업 권한과 동시 편집 충돌 테스트, DB 마이그레이션, 철도 환승 및 same-origin 통합 테스트를 자동 실행합니다. 실제 GitHub Repository 생성·push, Google Cloud 프로젝트·PostgreSQL·COS 연결, OAuth 실계정 승인 및 Cloud Run 배포는 아직 수행하지 않았습니다. Docker 이미지 빌드는 GitHub Actions CI에서 확인합니다. 실제 외부 인증/API/DB/COS 연결 및 Cloud Run 배포는 아직 수행하지 않았습니다. 이 패키지는 2.0 Beta Test 또는 정식 배포 파일이 아닙니다.
