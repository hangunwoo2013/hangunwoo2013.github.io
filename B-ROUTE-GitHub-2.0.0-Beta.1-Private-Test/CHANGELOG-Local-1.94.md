# Changelog — B-ROUTE 1.94

## 프로젝트 초대 메일
- 초대 링크 복사 방식을 Resend 기반 프로젝트 초대 메일로 교체
- 메일 HTML/텍스트에 `프로젝트 참가하기` 버튼/링크 추가
- 7일 만료 및 일회용 capability 토큰
- 실제 토큰은 이메일에만 포함하고 DB에는 SHA-256 해시 저장
- 새 링크를 재전송하면 이전 링크 즉시 무효화
- 메일 발송 실패 시 안전한 오류 코드 기록 및 재시도
- Owner만 초대 목록, 재전송, 취소 가능
- Resend 요청은 고유 `Idempotency-Key` 사용
- 일일 앱 발송 한도(기본 80, 최대 100) 적용

## 초대 수락/보안
- 메일 링크 GET 미리보기는 상태를 변경하지 않음
- 새 초대 토큰을 URL fragment로 이동해 HTTP 요청/Referer 노출 감소
- 초대 메일함 링크를 메일함 접근 증거로 사용
- Google·Naver·Microsoft 중 현재 로그인 계정에 초대 권한 부여
- 로그인 이메일이 다르면 현재 계정을 사용할지 명시적 확인
- DB에는 실제 참가 계정 provider subject/email 기록
- PostgreSQL에서 프로젝트 → 초대 행 순서로 잠금 순서를 통일
- 발송 완료가 늦게 도착한 이전 재전송이 최신 상태를 덮어쓰지 않도록 방어
- 프로젝트 이름/발신자 이름 메일 헤더 제어문자 정리
- OAuth 성공 URL에서 query/fragment 순서 수정, 로그인 후 초대 fragment 보존

## 테스트
- Resend MockTransport 시나리오 추가
- 기존 1.93 초대 DB 자동 마이그레이션 테스트
- 계정 이메일 불일치 선택/토큰 재사용/이전 링크 무효화 테스트
- 전체 9개 회귀 시나리오 통과
- 배포 테스트 미실행

- 보안 보강: 신규 UI의 초대 미리보기/수락 토큰은 URL path가 아닌 same-origin POST JSON body로 전달. 기존 URL path 기반 라우트는 1.9x 호환을 위해 deprecated 상태로 유지.
