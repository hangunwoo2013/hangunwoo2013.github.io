# B-ROUTE Local-first 1.3 — 구현 상태 및 사용 안내

## 이번 작업에서 구현한 내용
- Google 로그인 버튼을 설정값에 따라 표시하는 프런트엔드 흐름
- `/auth/config`, `/auth/google`, `/auth/me`, `/auth/logout` 인증 API
- `google-auth`를 이용한 Google ID 토큰의 서버 검증 구조
- 7일 만료 HMAC 서명 세션, HttpOnly / SameSite=Lax 쿠키
- `APP_ORIGIN`과 Origin 헤더 검사
- Google 이메일 또는 고정 subject ID로 총괄자 계정 식별
- 총괄자 전용 `/admin/config/status`
- 총괄자 전용 `admin.html` 설정 상태판
- EdgeOne 서버 환경변수 설정 템플릿 `.env.example`
- `.env`, DB, Python 캐시를 제외하는 `.gitignore`

## API 키와 로그인 작동 방식
- 교통 API 키는 EdgeOne Cloud Functions의 Environment Variables / Secrets에 총괄자가 등록합니다.
- 브라우저에는 교통 API 키가 전달되지 않습니다.
- Google 로그인은 계정 인증이며 Google Drive 저장 권한을 요청하지 않습니다.
- 일반 사용자는 Google Client ID 설정이 완료된 뒤 B-ROUTE에서 Google 로그인 버튼으로 로그인합니다.
- 총괄자는 `GOOGLE_ADMIN_EMAIL` 또는 `GOOGLE_ADMIN_SUB`로 지정합니다.
- 설정 상태 API는 키 원문을 반환하지 않고 연결 여부만 표시합니다.

## 아직 구현되지 않은 내용
- Tencent COS 실제 파일 저장 및 다운로드
- 사용자별 1GB 저장 용량 집계/강제
- 데이터베이스의 영구 저장 및 다중 인스턴스 동기화
- 웹 관리자 화면에서 EdgeOne Secret을 직접 생성/수정하는 기능
- 완성형 통계·감사 로그·시스템 롤백 UI

COS의 `COS_*` 환경변수는 향후 연동을 위해 상태 확인에만 쓰입니다. 이 값이 설정되어도 현재 빌드에서 COS 저장이 활성화되지는 않습니다.

## 검증
- Python 구문 검사 통과
- 메인 웹앱 및 관리자 화면 JavaScript 구문 검사 통과
- 로컬 FastAPI smoke test 통과
- 익명 사용자 관리자 접근 차단 확인
- 비총괄자 관리자 접근 차단 확인
- 총괄자 세션 접근 허용 확인
- 허용되지 않은 Origin 로그인 요청 차단 확인
- API 키 원문이 관리자 상태 API 응답에 포함되지 않는 점 확인
- 실제 Google 로그인은 Google OAuth Client ID 및 EdgeOne 환경변수 설정 후 확인 필요
- EdgeOne 재배포는 사용자의 요청에 따라 수행하지 않음
