# B-ROUTE 2.0.0-beta.2 변경 사항

- OSM tile URL을 공식 canonical URL로 변경.
- HTML meta 및 FastAPI 응답의 Referrer-Policy를 `strict-origin-when-cross-origin`으로 조정.
- OSM 타일 오류가 연속 발생하면 Esri 지형도로 자동 대체.
- 새 브라우저 설정 파일 `broute-config.js`로 API 서버 Origin을 설정할 수 있도록 변경.
- 메인 화면과 관리자 화면 API 호출이 설정된 API Origin을 사용하고, cross-origin이면 credentials include 적용.
- FastAPI에 명시적 허용 Origin 기반 CORS, OPTIONS preflight, credentials 지원 추가.
- `APP_ALLOWED_ORIGINS`, `SESSION_COOKIE_SAMESITE` 설정 추가 및 쿠키 생성/삭제에 일괄 적용.
- GitHub Actions Cloud Run 변수에 CORS 및 쿠키 환경변수, API OAuth callback Origin 설정 추가.
- Docker, 로컬 정적 자산 허용목록, PWA shell cache에 브라우저 설정 파일 포함.
- CORS 허용/거부와 Secure SameSite=None 쿠키 회귀 시나리오 추가.

API 키/외부 교통 공급자 실연결, OAuth 실계정, Cloud Run 배포 및 외부 지도 타일의 실제 수신은 이번 로컬 작업에서 실행하지 않았습니다.
