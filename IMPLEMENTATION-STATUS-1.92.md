# B-ROUTE 1.92 구현 현황

## 구현 및 로컬 테스트 대상

- `server.py`: `/api`와 프런트엔드를 같은 Origin에 마운트
- `Dockerfile`: 비특권 사용자로 FastAPI+정적 프런트엔드 실행
- `.github/workflows/ci.yml`: develop/beta/main CI
- `.github/workflows/deploy-cloud-run.yml`: 승인된 beta/main Cloud Run 배포
- `.github/workflows/rollback-cloud-run.yml`: 이전 Revision으로 수동 트래픽 복구
- Google, Naver OIDC, Microsoft OAuth 로그인 구성
- 프로젝트 owner/editor/viewer 권한, 프로젝트 경로, 버전/복구, 초대 링크
- 일반 공유 및 프로젝트 경로 읽기 전용 공유
- 프로젝트 뷰어 planner 읽기 전용 UI
- 사용자별 프로젝트/클라우드/공유 기본 사용량 제한
- 같은 Origin 정적 화면 + API 테스트

## 프로젝트 권한 정책

- 프로젝트 사용자 최대 5개
- 프로젝트 멤버 10명(소유자 포함)
- 프로젝트 경로 100개
- 프로젝트 대기 초대 10개
- 초대 링크 7일, 1회 사용
- 공유 링크 기본 7일/100회, 설정 가능 범위 1~30일/1~500회
- 사용자 기본 클라우드 용량 1,000MB, 파일 최대 5MB

## 신원 및 보안 정책

- 글로벌 서비스 총괄자는 Google 계정만 허용
- 일반 프로젝트 사용자는 Google, Naver, Microsoft 로그인 지원
- Naver: OIDC `sub`를 provider-stable user ID로 사용
- Microsoft: 서명 검증한 `tid` + `oid`를 우선 사용
- Google/Naver/Microsoft는 동일 이메일이어도 기본적으로 별도 B-ROUTE 계정
- 계정 연결/병합 UI 및 검증 절차는 아직 미구현
- 초대 이메일은 발송되지 않으며 수동 복사 링크의 대상 메모
- 초대 토큰은 bearer link이므로 링크를 가진 사람이 지원 계정으로 수락 가능. 잘못 전달 시 취소 필요.
- API 키/Client Secret은 서버 Secret Manager 환경변수로만 취급

## 로컬 테스트 결과

- Python compileall
- 모든 `tests/test_*.py` 회귀 스크립트
- RS256 OIDC 토큰 서명/claims 검증 테스트
- 프로젝트 cross-provider invite, role authorization, share caps tests
- frontend/API same-origin TestClient smoke test
- index/admin inline JavaScript `node --check`
- GitHub Actions YAML syntax load

## 실제 연결 전 남은 일

- GitHub 저장소 생성/push 및 Actions 설정
- GCP Workload Identity Federation / Artifact Registry / Cloud Run 연결
- PostgreSQL 실제 연결 및 마이그레이션/백업 테스트
- COS 실제 버킷과 CORS, 서명 URL, worker 권한 테스트
- Naver/Microsoft app registration과 redirect URI 실제 계정 검증
- Google OAuth GIS 실제 계정 검증
- 교통 API 키 실서버 테스트 및 지역 coverage 확인
- Cloud Run Job/Scheduler로 GTFS Worker 운영 연결
- Cloud cost guardrails/alert/limits 검증
- 접근성·모바일 실기기 테스트, 보안 검토, 부하 테스트

이 버전은 2.0 Beta Test가 아닙니다. EdgeOne/Cloud Run 배포는 실행하지 않았습니다.
