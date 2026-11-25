# B-ROUTE 비공개 베타 준비 체크리스트

## 버전 정책

- 1.9x(현재 1.95.1, 이후 1.9x 패치): 정식 배포 전 개발 및 오류 수정
- 2.0.0-beta.1: 비공개 베타 후보 빌드(현재 ZIP)
- 2.0 Beta Test: 필수 준비 항목을 검증한 뒤 지인 전용 실제 서비스 검증 단계
- 2.0: 베타 피드백 반영 및 최종 확인 후 공개 배포

1.9x 개발 중에는 실제 EdgeOne/Cloud Run 배포를 하지 않습니다. 로컬 구문 검사, 테스트 DB, 모의 HTTP, 합성 GTFS 및 통합 테스트로 다음 단계를 준비합니다.

## 코드/배포

- [ ] GitHub Repository 생성 및 private 설정
- [ ] 1.93 이후 각 코드 push/PR에서 자동 CI 통과
- [ ] develop/beta/main 브랜치 보호 규칙 및 PR 정책 설정
- [ ] Cloud Run beta/prod 서비스와 Artifact Registry 설정
- [ ] beta 서비스 익명 접근 차단 및 승인된 테스터의 Cloud Run Invoker 권한 확인
- [ ] GitHub Actions Workload Identity Federation 설정
- [ ] 배포 변수/Secrets 및 OAuth redirect URI 확인
- [ ] 같은 서비스 URL 업데이트와 rollback 리허설
- [ ] 이전 EdgeOne 도메인의 대체 주소/사용자 소유 custom domain 결정

## 인증/협업

- [ ] Google 로그인 실제 계정 테스트
- [ ] Naver OIDC 실제 계정 테스트
- [ ] Microsoft 개인 Outlook 계정과 조직 계정 테스트
- [ ] owner Google-only 권한 확인
- [ ] Naver/Microsoft 초대 수락 및 초대 취소 테스트
- [ ] 같은 이메일의 다른 공급자 계정이 별도 사용자라는 안내 확인
- [ ] owner/editor/viewer의 읽기/쓰기/공유 권한 검증
- [ ] 두 편집자의 동시 수정 충돌(409) 처리와 사용 안내 검증
- [ ] 1.92/1.93 DB에서 1.94 초대 메일 스키마 migration 검증
- [ ] 읽기 전용 공유 링크 만료/횟수/취소 테스트
- [ ] Resend 실제 도메인 인증(SPF/DKIM) 및 API 키 Secret 등록
- [ ] 초대 이메일의 `프로젝트 참가하기` 버튼 실제 수신 테스트
- [ ] 초대 링크 GET 미소비, 만료·재전송·취소·1회 수락 검증
- [ ] Google/Naver/Microsoft 중 다른 로그인 이메일을 선택한 경우 명시적 계정 연결 확인
- [ ] Resend accepted 상태와 실제 delivered/bounced 상태를 구분
- [ ] Resend delivery/bounce/suppressed webhook의 서명·중복·실제 전달 검증(코드 지원은 1.95.1, 실제 공급자 테스트 필요)

## 데이터/경로

- [ ] 실제 전국 교통 데이터 공급원 및 이용 조건 확인
- [ ] 지역별 버스 노선 coverage 및 정류장 ID 매핑 검증
- [ ] 도시철도/일반철도/고속철도 역·노선·시간표 coverage 검증
- [ ] 평일/토요일/공휴일/예외일 시간표 검증
- [ ] 버스만/철도만/버스+철도 검색 회귀
- [ ] 철도 다중 환승 및 역 내부 통로 검증
- [ ] 실제 API 인증 실패/빈 응답/호출 제한/시간 초과 처리 확인
- [ ] 시간표 데이터 변경 감지와 이전 버전 복구 테스트

## 영구 저장/운영

- [ ] PostgreSQL 실 연결, schema migration, backup/restore 테스트
- [ ] COS 실 버킷 권한, CORS, 업로드/다운로드/삭제 테스트
- [ ] GTFS Worker Job 배포 및 자동 실행 trigger 구현
- [ ] Worker 중복 실행/재시도/실패/heartbeat 테스트
- [ ] 1GB/user cloud quota와 계정간 파일 격리 테스트
- [ ] 비용 알림, 한도, fail-closed 동작 점검
- [ ] API 키가 브라우저/로그/오류 응답에 노출되지 않는지 확인
- [ ] 개인정보/로그 보관·삭제 정책 정리
- [ ] 모바일/PC 실기기 테스트 및 접근성 검사
- [ ] 주요 경로 유형의 실사용자 통합 검증

## 1.94 이메일 초대 기능 유의사항

- 메일함의 일회용 `프로젝트 참가하기` 링크가 메일함 접근 증거다. 사용자가 링크를 전달하면 초대를 전달한 것과 같으므로 링크 공유 금지 안내가 필요하다.
- 1.95.1은 Resend delivery/bounce/suppressed webhook을 처리한다. 실제 발송·웹훅 전달·DNS 인증은 아직 검증하지 않았으므로 베타 전에 실제 공급자 테스트가 필요하다.
- B-ROUTE 앱 일일 메일 상한은 80건(코드 최대 100)이다. 제공자 팀 내 다른 발송량은 별도다.

## 현재 후보 빌드 상태

2.0.0-beta.1은 코드·로컬 회귀검사를 확인하기 위한 비공개 후보 패키지다. 제작 시점에는 외부 로그인 공급자, Resend, 운영 PostgreSQL, COS, 실제 GTFS 전국 커버리지, GTFS Worker 배포 및 비용 제한이 검증되지 않았다. `BETA_RELEASE_APPROVED`와 `BETA_DEPLOY_APPROVED`는 기본적으로 꺼진 상태를 유지한다. 이 ZIP을 곧바로 공개하거나 실제 테스터에게 사용 가능한 전국 경로검색 서비스라고 안내하지 않는다.

## 베타 공개 승인 기준

위 항목 중 필수 항목이 완료되고, `GET /api/health`의 readiness가 사실에 맞게 표시되며, 운영 백업/복구와 비용제한이 검증되기 전에는 `BETA_RELEASE_APPROVED=true`로 설정하지 않습니다.
