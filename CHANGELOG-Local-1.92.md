# B-ROUTE 1.92 변경 사항

## 버전 정책

1.92는 1.9x 개발 단계입니다. 2.0 Beta Test 전까지 실제 배포를 하지 않습니다.

## GitHub 및 런타임 구조

- GitHub Repository + GitHub Actions CI/Deploy 도입 준비
- FastAPI와 정적 프런트엔드를 같은 Origin에서 제공하는 Cloud Run 컨테이너 진입점 추가/정비
- `develop`, `beta`, `main` 브랜치 흐름 문서화
- beta/production 배포 승인 변수를 별도로 분리
- 기존 서비스에 새 Cloud Run Revision을 배포하고 같은 서비스 URL을 유지하는 Workflow 구성
- 기존 Revision으로 트래픽을 돌리는 수동 rollback Workflow 추가
- EdgeOne 배포 마커 `edgeone.json` 제거

## 프로젝트 협업/공유

- Google, Naver OIDC, Microsoft Identity Platform 다중 공급자 로그인 구성
- owner/editor/viewer 프로젝트 권한과 서버 측 권한 확인
- 7일 유효 1회용 초대 링크, 권한 선택, 초대 취소·수락·재사용 차단
- 프로젝트 경로 생성/수정, 버전 이력 및 복구
- 프로젝트 경로의 읽기 전용 공개 공유 링크
- 일반 경로 공유는 읽기 전용·만료/열람 한도 적용
- 뷰어가 프로젝트 경로를 열면 planner 편집을 잠그고 자기 경로로 복사한 후 편집 가능
- 로그아웃 뒤 로그인 버튼을 다시 표시하도록 수정
- 초대 메일은 자동 발송하지 않으며 이메일은 전달 대상 표시용임을 UI에 명시

## 보안 및 안정성

- 글로벌 총괄자는 Google provider의 검증된 identity로만 지정
- Naver 사용자 키는 OIDC `sub`를 사용하고 프로필 API는 표시 정보로만 처리
- Naver 표시용 프로필 API가 실패해도 검증된 OIDC token이 유효하면 로그인 흐름을 계속함
- Microsoft ID token의 서명 검증 후 `tid`/`oid` 일치 확인
- 프로젝트/공유 quota 경합을 줄이는 DB lock 보호
- OAuth return URL의 외부 redirect 차단
- same-origin API + static UI smoke test 추가
- OIDC RS256 signature/issuer/audience/expiry/nonce/algorithm 검증 테스트 추가

## 아직 하지 않은 일

- GitHub Repository 생성 및 코드 push
- Google Cloud 프로젝트/Workload Identity 설정
- PostgreSQL/COS 계정 연결
- 실제 Google/Naver/Microsoft 계정 로그인
- 실제 교통 API 인증/호출
- Cloud Run deploy/EdgeOne deploy
- Cloud Run Job으로 GTFS Worker 실행 및 스케줄 등록
- 실제 메일 발송 서비스 연결
- 서로 다른 OAuth provider 계정의 안전한 계정 연결/병합
