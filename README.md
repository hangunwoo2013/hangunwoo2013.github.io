# B-ROUTE 2.0.0-beta.2

지도 타일 정책 문제와 프런트엔드/API 연결을 개선한 비공개 베타 후보입니다.

## 먼저 읽을 문서

1. `README-2.0.0-beta.2-Map-API-Fix.md` — GitHub Pages와 Cloud Run 구성, API 주소, 지도 문제 해결 방법
2. `README-2.0-Beta-Test.md` — 2.0 비공개 베타 테스트 안내
3. `TEST-REPORT-2.0.0-beta.2.md` — 로컬 자동검사 및 회귀검사 결과
4. `IMPLEMENTATION-STATUS-2.0.0-beta.2.md` — 구현된 기능과 외부 연결이 남은 항목
5. `NEXT-STEPS-2.0-BETA-API.md` — 교통 API 연동 다음 단계

## 업데이트

ZIP을 풀고 `B-ROUTE-GitHub-2.0.0-Beta.2-Map-API-Fix` 폴더의 파일 전체를 기존 GitHub 저장소 파일에 덮어쓴 뒤 commit/push 합니다. 프런트엔드와 API가 별도 서버라면 `broute-config.js`에서 `apiBaseUrl`을 실제 API 서버 Origin으로 지정해야 합니다.

## API 호스팅 핵심

GitHub 저장소/Pages는 소스를 저장하거나 정적 HTML을 제공할 수 있지만 Python/FastAPI 서버를 실행하지 않습니다. 실제 API는 Cloud Run 등에서 실행해야 합니다. 가능하면 `server.py`가 프런트엔드와 `/api`를 같은 출처에서 제공하는 단일 Cloud Run 구성을 권장합니다.

## 로컬 실행

Python 3.11 이상 환경에서:

```bash
python -m pip install -r cloud-functions/requirements.txt -r requirements-ci.txt
# Windows PowerShell
$env:PYTHONPATH = ".;cloud-functions"
# macOS/Linux
# export PYTHONPATH=.:cloud-functions
python -m uvicorn server:app --host 127.0.0.1 --port 8080
```

브라우저에서 `http://127.0.0.1:8080`을 엽니다. 로컬 SQLite는 개발/테스트용입니다.

## 검사

```bash
python -m pytest -q
python scripts/run_regression.py
```

실제 API 공급자 키는 `broute-config.js`나 HTML에 넣지 말고 서버 Secret Manager에 저장합니다.
