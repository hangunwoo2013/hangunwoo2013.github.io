# B-ROUTE 2.0.0-beta.1 소스 검증 보고서

- 기준 코드: B-ROUTE 1.95.1 Email Delivery Hotfix
- 버전: `2.0.0-beta.1`
- 검증 목적: 정식 공개 전 피드백을 위한 2.0 Beta Test 단계에 들어가기 전, 로컬 소스 수준에서 확인 가능한 사항 점검
- 외부 API 호출 및 실제 서비스 배포: 수행하지 않음 (이번 검증 범위 아님)

## 통과 결과

| 검사 | 결과 |
|---|---:|
| `python -m pytest -q` | 1 passed |
| `python scripts/run_regression.py` | 10 / 10 isolated scenarios passed |
| 독립 회귀 반복 실행 | 연속 2회 통과 |
| Python compileall / Python 3.11 문법 | 통과 |
| Node.js inline JS / service worker 구문 | 통과 (Node v22.16.0) |
| HTML ID 중복 및 literal DOM 참조 | 통과 (index 95개 ID, admin 63개 ID) |
| GitHub Actions YAML 및 내장 Bash | 3개 workflow 통과 |
| 버전 메타데이터 / Secret 파일 검사 | 통과 |
| TestClient 기반 웹/API 통합 회귀 | 통과 |
| 합성 GTFS / 철도 환승 / OIDC / 프로젝트 / 초대 / webhook | 통과 |
| ZIP 무결성 | 통과 |

## 발견 및 수정한 검사 실행 문제

최초 1.95.1 ZIP 재검사에서 `scenario_email_delivery_webhook_195.py`가 `from server import app`을 실행할 때 `ModuleNotFoundError: No module named 'server'`로 실패했습니다. 회귀 실행기가 하위 프로세스 `PYTHONPATH`에 `cloud-functions`만 추가하고 프로젝트 루트는 추가하지 않는 문제였습니다.

`scripts/run_regression.py`의 하위 프로세스 환경에 프로젝트 루트와 `cloud-functions`를 모두 전달하도록 수정했습니다. 이후 1.95.1 작업본과 2.0.0-beta.1 패키지에서 전체 `pytest` 및 10개 독립 시나리오를 다시 실행해 통과를 확인했습니다.

## 이번 단계에서 수행하지 않은 항목

다음은 실패가 아니라 이번 소스 검증 범위에서 의도적으로 제외한 작업입니다.

- 실제 공공데이터포털/TAGO/Kakao/Photon 외부 API 호출 및 실제 API 키 사용
- Google/Naver/Microsoft 실계정 OAuth
- Resend 실제 메일/웹훅 수신
- 운영 PostgreSQL / COS 연결
- 실제 전국 GTFS 수집, 라이선스 및 시간표 정확성 확인
- Cloud Run 배포, 원격 GitHub Actions 실행, 실제 트래픽/롤백
- 실기기 테스트 및 테스터 피드백 수집

Docker CLI/Engine이 이 실행 환경에 설치되어 있지 않아 이미지 빌드는 실행하지 않았습니다.

## 판정

**로컬 소스 검사 통과. 2.0 Beta Test 단계로 진행 가능.**

이 판정은 API 연결이나 실제 전국 경로 검색이 완료되었다는 의미가 아닙니다. 실제 API 연동 및 비공개 베타 테스터 제공은 2.0 Beta Test 단계의 다음 작업으로 진행합니다.
