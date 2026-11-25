# B-ROUTE 1.92 내부 테스트 보고서

## 수행한 로컬 테스트

| 테스트 | 결과 |
|---|---|
| Python compileall (API/server/worker/tests) | PASS |
| 기존 TAGO HTTP 계약 테스트 | PASS |
| GTFS 대용량 staging/validator 회귀 | PASS |
| OIDC RS256, kid, issuer, audience, expiry, nonce, algorithm | PASS |
| OAuth return URL 외부 redirect 방어 | PASS |
| 프로젝트 owner Google provider 제한 | PASS |
| Naver 편집자 / Microsoft viewer 초대 수락 | PASS |
| owner/editor/viewer 역할별 route read/write 제한 | PASS |
| project route version/restore | PASS |
| project read-only share/view cap/revoke | PASS |
| normal read-only share/view cap/revoke | PASS |
| rail transfers regression | PASS |
| transit provider contract regression | PASS |
| same-origin static frontend `/` + API `/api/health` | PASS |
| unauthenticated project API rejection | PASS |
| GitHub Actions workflow YAML parse | PASS |
| inline JS node --check | PASS |
| Docker image build | NOT RUN — local environment has no Docker CLI/daemon |

## 테스트 환경/제약

- DB: 테스트별 임시 SQLite
- OAuth: 생성한 RSA 키로 서명한 합성 ID token
- Google/Naver/Microsoft: 실제 identity provider와 통신하지 않음
- Invitation: 실제 이메일을 보내지 않고 invite URL 복사 방식 테스트
- Cloud storage: COS 실 버킷 없음
- PostgreSQL: 실제 외부 DB 연결 없음
- Cloud Run/GitHub: 저장소 생성, push, 배포 및 rollback 미실행
- 교통 API: 실제 API key 사용 호출 없음

따라서 이 보고서는 로컬 코드/모의 통합 검사 결과이며, 운영 배포 가능성이나 외부 서비스 연결 성공을 보증하지 않습니다.
