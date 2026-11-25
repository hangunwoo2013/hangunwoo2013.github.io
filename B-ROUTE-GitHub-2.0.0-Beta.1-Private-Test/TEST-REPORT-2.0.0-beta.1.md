# B-ROUTE 2.0.0-beta.1 테스트 보고서

- 기준 코드: 1.95.1 Email Delivery Hotfix
- 버전: 2.0.0-beta.1
- 테스트 유형: 로컬 코드/통합 회귀 및 HTTP smoke
- 실제 배포: 미실행

## 통과한 검사

| 검사 | 결과 |
|---|---:|
| `python -m pytest -q` | 1 passed |
| 독립 회귀 시나리오 | 10 / 10 passed |
| Python 3.11 문법 호환성 및 compileall | 통과 |
| Node.js inline JavaScript / service worker 구문 | 통과 (Node v22.16.0) |
| HTML ID 중복 및 JavaScript DOM 참조 | 통과 · index 95개 ID / admin 63개 ID |
| GitHub Actions YAML 및 내장 Bash | 3개 workflow 통과 |
| API/웹/관리자/manifest/service worker HTTP smoke | 통과 |
| dotfile 및 서버 소스 정적 파일 노출 | 404 차단 확인 |
| GTFS Worker heartbeat version | API runtime version과 일치 확인 |
| Beta release/deploy/public access gate | 기본 승인·익명 접근 비활성화 확인 |
| manifest JSON / ZIP 무결성 | 통과 |

## HTTP smoke 핵심 결과

- `/`, `/manifest.json`, `/icon.svg`, `/sw.js`, `/admin.html`, `/api/health`, `/api/auth/config`: HTTP 200
- `/.env`, `/server.py`, `/cloud-functions/api/index.py`: HTTP 404
- `/api/health` version: `2.0.0-beta.1`
- 기본 `BETA_RELEASE_APPROVED=false`일 때 `readiness.beta_ready=false`
- 검사용 빈 데이터베이스에는 GTFS feed가 없어 `features.gtfs_routing=false`

## 아직 통과했다고 볼 수 없는 항목

- Docker Engine이 없는 현재 환경에서 app/worker 컨테이너 이미지 빌드 미실행
- GitHub Actions 원격 CI 실행 미실행
- Cloud Run 및 Secret Manager 실제 배포/권한 확인 미실행
- Google/Naver/Microsoft 실계정 OAuth 미검증
- Resend DNS 인증, 실제 초대 메일 발송 및 실제 webhook 전달 미검증
- 운영 PostgreSQL, 백업/복구 및 Tencent COS 실제 업로드/다운로드 미검증
- 지역별 실제 GTFS 출처/라이선스/시간표 정확성과 전국 커버리지 미검증
- GTFS Worker의 별도 Cloud Run Job 배포, 실행 트리거 및 운영 권한 미검증
- 모바일/PC 실기기 및 외부 테스터 피드백 미수집
- 운영 비용 알림/상한과 무료 할당량 초과 자동 결제 방지 미검증

## 판정

**로컬 회귀검사 통과 / 외부 베타 배포 보류.**

이 결과는 코드와 모의 데이터 기반 기능의 테스트 통과를 뜻한다. 실제 전국 교통 경로가 완성되었다거나 실서비스 운영이 검증되었다는 의미는 아니다. 특히 부산 외 테스터에게 실제 경로 검색을 제공하기 전, 그 지역의 시간표 데이터가 등록·활성화되어 있어야 한다.
