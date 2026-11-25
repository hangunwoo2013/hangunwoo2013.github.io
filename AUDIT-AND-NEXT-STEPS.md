# B-ROUTE 1.94 감사 및 다음 단계

## 1.94에서 강화된 항목
- Resend 기반 프로젝트 초대 메일 발송
- 메일에 `프로젝트 참가하기` 버튼 및 7일 만료 일회용 링크
- GET 미리보기 비소비, POST 수락만 1회 처리
- 토큰을 브라우저 fragment에 넣어 HTTP 요청/Referer 노출 축소
- Google·네이버·Microsoft 중 선택 계정으로 초대 수락
- 초대 메일 주소와 로그인 계정 이메일이 다르면 현재 계정에 권한을 부여할지 명시적 확인
- 재전송 시 이전 링크 폐기, 발송 실패/재시도, 일일 무료 한도
- 이전 발송 결과가 최신 초대 상태를 덮어쓰지 않도록 이벤트 ID 보호
- 프로젝트 잠금 순서를 project → invite로 통일해 재전송/수락 데드락 위험 완화
- OAuth 복귀 시 초대 fragment 보존
- 자동 회귀검사에 초대메일/fragment/OAuth 복귀/재전송 경합 테스트 추가

## 다음 단계(1.95 후보)
1. Resend delivery/bounce webhook 서명 검증 및 상태 반영
2. 실제 PostgreSQL에서 초대 수락·재전송·취소 경쟁 조건 테스트
3. Google/Naver/Microsoft 실제 OAuth 테스트와 계정 연결/병합 재인증 UX
4. 계정/프로젝트 공유 접근 로그와 관리판에서 메일 발송·배달 이벤트 보기
5. API rate limit을 인스턴스 메모리 대신 중앙 저장소 기반으로 통합
6. GitHub Actions의 Docker 이미지 빌드 및 취약점 검사 실제 CI 결과 확인(배포는 별도 보류)
7. 무료 한도 초과 시 이메일 발송 fail-closed 검증

## 미해결 운영 한계
- 실제 Resend API 키/발신 도메인/메일 배달은 테스트하지 않음
- `email_status=accepted`는 API 수락이지 메일함 배달이 아님
- Delivery/Bounce webhook 미구현
- 실 OAuth·공공 API·PostgreSQL·COS 키가 연결되지 않음
- Cloud Run Worker Job/Scheduler 운영 설계와 비용은 별도 검증 필요
- 월 0원 운영은 아직 보장되지 않음

## 배포 정책
2.0 Beta Test 전까지 실제 EdgeOne/GitHub/Cloud Run 배포는 수행하지 않는다. 로컬 테스트 및 모의 HTTP를 계속 강화한 뒤, 베타 승인 시 실제 외부 계정과 인프라 통합 테스트를 진행한다.

## 1.94 추가 보안 점검
- 신규 프런트엔드는 초대 토큰을 POST JSON body로 미리보기/수락 API에 보낸다. 신규 UI가 API URL path에 원문 토큰을 넣지 않도록 회귀 검사한다.
- 기존 1.9x URL-token endpoints는 호환용으로 유지하되 신규 UI에서는 사용하지 않는다. 구버전 클라이언트 종료 이후 제거 후보다.
