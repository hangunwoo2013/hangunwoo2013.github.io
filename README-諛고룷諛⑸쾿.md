# B-ROUTE 2.0 Beta Test — 개발·실행·배포 정책

현재 기준은 **2.0.0-beta.1**입니다.

## 버전 정책
- 1.9x: 2.0 이전 개발 및 소스 수준 오류 수정
- 2.0 Beta Test: 정식 공개 전에 초대된 테스터가 기능을 사용하고 피드백을 제공하는 비공개 베타 단계. 실제 API 연결과 베타 환경 준비는 이 단계에서 진행
- 2.0: 베타 피드백 반영 및 최종 점검 후 정식 공개

이번 2.0.0-beta.1 소스 검증에서는 외부 API 호출, Cloud Run 배포, 실계정 로그인을 수행하지 않았습니다. 이는 검증 범위 밖으로 둔 것이며 실패한 테스트가 아닙니다. 실제 API 연결은 `NEXT-STEPS-2.0-BETA-API.md`를 기준으로 2.0 베타 단계에서 시작합니다. 사용자의 별도 지시 전에는 실제 배포하지 않습니다.

## 권장 운영 구조
- GitHub Repository: 소스, 이력, 이슈 및 PR
- GitHub Actions: 자동 테스트, 컨테이너 빌드, 승인된 배포 및 롤백
- Google Cloud Run: FastAPI와 정적 화면을 동일 출처로 제공
- PostgreSQL: 계정·프로젝트·공유·문의·교통 데이터 메타데이터
- Tencent COS: `.broute` 파일 및 대용량 GTFS 원본 보관
- 별도 GTFS Worker: 대용량 GTFS 검증·배치 적재

GitHub Pages만으로는 FastAPI, OAuth 세션, 비밀키, DB 및 프로젝트 권한을 운영할 수 없습니다. 실제 런타임은 별도 서버가 필요합니다.

## 주요 프로젝트 구조
- `index.html`, `admin.html`, `manifest.json`, `sw.js`, `icon.svg`: 웹/PWA
- `cloud-functions/api/`: FastAPI 계정·교통·협업 API
- `server.py`: `/api` 및 정적 파일을 동일 출처로 제공
- `workers/`: GTFS Worker
- `tests/scenarios/`: 독립 회귀 테스트
- `scripts/run_regression.py`: 구문·정적·통합 검사
- `.github/workflows/`: CI, 승인 배포, 롤백

## 로컬 실행

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r cloud-functions/requirements.txt -r requirements-ci.txt
cp .env.example .env
# .env에 로컬 전용 값 설정
PYTHONPATH=.:cloud-functions uvicorn server:app --host 127.0.0.1 --port 8080
```

Windows PowerShell은 `$env:PYTHONPATH = ".;cloud-functions"`를 사용합니다. 로컬 SQLite는 개발·시험 전용입니다.

## 소스 검사

```bash
python -m pytest -q
python scripts/run_regression.py
```

이번 실행 환경에는 Docker Engine이 없어 컨테이너 이미지 빌드는 확인하지 않았습니다. CI workflow의 YAML과 내장 Bash 구문만 로컬에서 검사했습니다.

## 실제 베타 환경

실제 베타 테스터 제공을 준비할 때만 사용자 승인 하에 beta 브랜치·별도 DB/COS·Secrets·Cloud Run beta 서비스를 설정합니다. beta workflow는 `GCP_DEPLOY_ENABLED=true` 및 `BETA_DEPLOY_APPROVED=true` 등의 명시적 승인을 요구하고, 익명 접근은 기본 차단합니다. 운영/정식 서비스와 베타 데이터 및 비밀값을 공유하지 않습니다.
