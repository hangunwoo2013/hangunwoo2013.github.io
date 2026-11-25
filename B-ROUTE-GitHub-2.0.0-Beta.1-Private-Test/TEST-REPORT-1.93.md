# B-ROUTE 1.93 내부 테스트 보고서

## 실행 명령
```bash
python -m pip install -r cloud-functions/requirements.txt -r requirements-ci.txt
python -m pytest -q
```

pytest 단일 테스트가 `scripts/run_regression.py`를 실행합니다. 각 scenario는 독립 Python 프로세스에서 실행되어 환경변수와 임시 DB가 서로 오염되지 않습니다.

## 검사 항목 및 결과
| 검사 | 결과 |
|---|---|
| Python compileall | PASS |
| index.html inline JS | PASS |
| admin.html inline JS | PASS |
| sw.js JS | PASS |
| HTML ID 중복 | PASS |
| GitHub Actions YAML | PASS |
| Workflow 내부 Bash 문법 | PASS |
| 릴리스 버전/secret 파일 검사 | PASS |
| TAGO HTTP 계약·오류·키 비노출 | PASS |
| GTFS COS staging·검증·버전 복구 | PASS |
| OIDC 검증 | PASS |
| 프로젝트 역할·초대·공유 | PASS |
| 동일 버전 동시 편집 충돌 | PASS |
| 1.92 DB → 1.93 스키마 마이그레이션 | PASS |
| 철도 환승·버스+철도 회귀 | PASS |
| same-origin server smoke | PASS |
| 공급기관 어댑터 8종 검사 | PASS |

## 동시 편집 테스트
두 명의 편집자가 동일한 경로 버전 1을 열어 동시에 저장하도록 테스트했습니다. 프로젝트 잠금 후 버전을 비교한 결과 한 요청만 버전 2로 저장되고, 다른 요청은 HTTP 409로 거부되었습니다. 최종 데이터는 성공한 저장 내용이며 충돌 요청이 덮어쓰지 않았습니다. 이 테스트는 SQLite 로컬 환경의 병렬 요청으로 수행했습니다. PostgreSQL 실제 인스턴스에서의 잠금/격리 검증은 아직 수행하지 않았습니다.

## 실제 실행 검증과 구분
- 위 결과는 로컬 테스트 DB, 합성 데이터, Mock HTTP/OAuth/COS를 이용한 검증입니다.
- Docker CLI/daemon이 이 실행 환경에 없어 컨테이너 이미지 빌드는 로컬에서 수행하지 못했습니다. GitHub Actions CI Workflow에 Docker 빌드 단계를 포함했습니다.
- 실제 API 키, 외부 OAuth 계정, PostgreSQL, COS, Cloud Run 배포 테스트는 수행하지 않았습니다.
- EdgeOne/Cloud Run 배포 테스트는 요청에 따라 보류했습니다.
