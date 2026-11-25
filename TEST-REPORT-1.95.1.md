# B-ROUTE 1.95.1 테스트 보고서

검사 기준: 사용자가 업로드한 1.95 ZIP을 풀어 수정한 소스

## 결과

**결과: 로컬 자동검사 통과**

| 검사 | 결과 |
|---|---|
| Python compileall | 통과 |
| Python 3.11 문법 호환 파싱 | 통과 |
| index.html / admin.html 인라인 JavaScript | Node 구문검사 통과 |
| service worker JavaScript | Node 구문검사 통과 |
| HTML ID 중복 및 정적 JS 참조 | 통과 (index 95개 고유 ID / 96개 참조, admin 63개 / 63개 참조) |
| GitHub Actions Workflow YAML 및 내장 Bash | 3개 workflow 통과 |
| 릴리스 버전 및 비밀 파일 포함 여부 | 통과 |
| 독립 회귀 시나리오 | 10개 모두 통과 |
| pytest | 1 passed |
| ZIP 무결성 | 압축 후 `unzip -t` 통과 |

## 검증한 주요 기능

- TAGO 교통 API 요청/응답 형식, 오류·시간초과 처리 및 서버 키 관리
- Resend 웹훅 서명, 잘못된/빈 Secret, 오래된 timestamp, 중복 이벤트 처리
- delivered / bounced / suppressed 상태와 이벤트 역순 도착 보호
- 메일 API 응답보다 웹훅이 먼저 도착하는 경합 상황 보정
- 외부 웹훅 경로 `/api/webhooks/resend` 및 잘못된 루트 경로의 404 처리
- GTFS 파일 staging, COS mock, ZIP 경로 탐색 차단, 데이터 검증·가져오기와 worker heartbeat
- Google/Naver/Microsoft OIDC 토큰 검증
- 프로젝트 초대 이메일, 1회용 초대 링크, 재발송 토큰 교체 및 기존 DB 마이그레이션
- Owner/Editor/Viewer 협업, 편집 충돌 감지 및 읽기 전용 공유
- GTFS 철도 환승 및 버스-철도 연계 규칙
- 프런트/API 단일 출처 경로, 공개 health, 관리자 인증 및 readiness 일치
- 대중교통 데이터 제공자 요청 계약, 응답 정규화, 캐시, 권한, 비밀값 마스킹 및 rate limit

## 수행하지 못한 검사

- **Docker image build**: 이 실행 환경에 Docker 명령이 없어 실행하지 못했다.
- **브라우저 화면 테스트**: 로컬 서버 API의 HTTP health 응답은 확인했지만, headless 브라우저 실행이 환경 정책으로 `ERR_BLOCKED_BY_ADMINISTRATOR` 차단되어 실제 렌더링/클릭 검증은 하지 못했다. 이는 앱 자체 오류로 판정한 것이 아니다.
- **외부 서비스 운영 테스트**: GitHub Actions 원격 실행, Cloud Run 배포, Secret Manager 연결, Resend 실제 발송 및 webhook 전달, SPF/DKIM/DMARC, Google/Naver/Microsoft 실계정 OAuth, 운영 PostgreSQL 및 Tencent COS 연동은 하지 않았다.
- **실제 교통 API 전수 확인**: 자동화 시나리오는 계약/응답 처리를 모의 응답으로 검증했으며, 모든 지역의 실제 API 키·쿼터·데이터 최신성을 확인한 것은 아니다.

## 실행 환경 주의

`python -m pip check`는 B-ROUTE 의존성이 아닌 공용 실행환경의 `moviepy 2.2.1`과 `pillow 12.3.0` 간 요구 버전 충돌을 출력했다(`moviepy`가 `pillow<12` 요구). B-ROUTE의 `requirements-ci.txt` 및 `cloud-functions/requirements.txt`를 대상으로 한 앱 테스트는 위와 같이 통과했지만, 이 공용 환경의 전역 패키지 일관성은 별도 문제로 남는다.

## 결론

1.95.1의 로컬 회귀검사는 통과했다. 다만 사용자가 정한 원칙대로 2.0 Beta Test 준비 전까지 배포 검증은 보류하며, 위의 외부 서비스·컨테이너·브라우저 검증 항목을 완료한 것으로 간주하지 않는다.
