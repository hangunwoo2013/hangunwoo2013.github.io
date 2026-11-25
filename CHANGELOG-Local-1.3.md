# B-ROUTE EdgeOne Local 1.3 — API / Google 로그인 기반

## 추가
- Google Identity Services 로그인 버튼: Google Client ID와 세션 비밀키 설정 시 표시
- Google ID 토큰을 FastAPI 백엔드에서 검증
- HttpOnly / SameSite=Lax 서명 세션 쿠키
- 세션 확인 및 로그아웃 API
- 총괄자 계정 식별 환경변수(GOOGLE_ADMIN_EMAIL / GOOGLE_ADMIN_SUB)
- 총괄자 전용 API 설정 상태 조회 API
- 서버 환경변수 설정 예시와 총괄자 설정 가이드

## 보안
- API 비밀값은 브라우저로 전달하지 않음
- 설정 상태 API는 비밀값 원문 대신 설정 여부만 반환
- 로그인 및 로그아웃 요청의 Origin 검사
- Google ID 토큰의 서명/발급자/audience/만료 검증을 google-auth 라이브러리에 위임
- 세션은 7일 만료, HttpOnly, SameSite=Lax 쿠키로 관리

## 현재 구현하지 않은 항목
- COS 실파일 저장, 사용자별 1GB 할당량
- 영구 DB, 클라우드 보관함 및 공유 권한 관리
- 웹 화면에서 EdgeOne 환경변수/Secret 자체를 수정하는 기능
- 완성형 총괄자 관리판 및 감사 로그

## 검증 범위
- Python 및 브라우저 JavaScript 구문 검사
- 로컬 FastAPI smoke test 및 인증 설정 미완료 시의 fail-closed 응답
- 실제 Google 계정 OAuth 로그인은 사용자의 Google OAuth Client ID 및 EdgeOne 환경변수 입력 후 검증 필요
- EdgeOne 배포는 사용자가 요청한 반복 배포 테스트 방침에 따라 이번 작업에서 수행하지 않음
