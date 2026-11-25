# B-ROUTE 1.94 구현 현황

## 구현됨

- 프로젝트 생성자 Owner 전용 초대 메일 생성/목록/재전송/취소
- Resend `POST /emails` 서버 측 REST 연동 어댑터
- 발신 API 키 서버 전용 Secret 처리
- HTML 및 plain-text `프로젝트 참가하기` 초대 메일
- 7일 만료, 무작위 일회용 토큰, DB에는 토큰 해시만 저장
- 이메일 링크 GET 조회는 초대를 소비하지 않음
- 신규 링크는 URL fragment(`/#invite=`) 사용
- 프런트엔드 초대 토큰 미리보기/수락은 JSON POST 본문으로만 전달(구형 URL 토큰 API는 호환용 유지)
- 새 클라이언트에서 API 접근 로그에 원문 초대 토큰이 들어가지 않도록 정적 회귀 검사 추가
- Google·네이버·Microsoft 중 선택한 로그인 계정으로 초대 수락
- 이메일 불일치 시 현재 로그인 계정에 권한을 부여할지 명시적 확인
- 수락 시 실제 B-ROUTE provider subject 및 로그인 계정 이메일 기록
- 재전송 시 이전 토큰 폐기
- 프로젝트 단위/일일 이메일 한도, Resend 실패 코드 기록 및 재시도
- 발송 요청 결과의 비동기 경합 보호(`current_email_event_id`)
- 이전 1.93 DB의 초대 테이블 자동 마이그레이션
- OAuth 로그인 완료 후 초대 fragment를 보존하도록 success URL 수정
- 프런트엔드 초대 상태/재전송/취소 UI

## 미완료 / 운영 전 필요

- Resend 실제 API 키 및 인증된 발신 도메인으로 외부 배달 테스트
- Resend delivery/bounce webhook 및 서명 검증
- 실제 Naver/Microsoft/Google OAuth 계정별 콜백·메일주소 제공 범위 확인
- 실제 PostgreSQL 병행 수락/재전송 경쟁 조건 테스트
- 관리판에서 배달/반송 이벤트 보기
- 메일 주소별 초대 남용 방지·억제목록 연동
- 실제 운영 배포 전 보안 검토 및 배포 파이프라인 검증

## 중요 의미

`email_status=accepted`는 Resend API 발송 요청 수락 상태이며 실제 받은편지함 배달 확인 상태가 아니다. Delivery webhook은 후속 버전에 남겨져 있다.
