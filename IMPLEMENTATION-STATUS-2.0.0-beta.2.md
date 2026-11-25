# B-ROUTE 2.0.0-beta.2 구현 현황

## 코드에 반영된 항목

- OpenStreetMap canonical tile URL 및 Referer 전송 정책 수정
- OSM 일반 지도 타일 장애 시 Esri 지형도 자동 전환
- 메인/관리자 페이지의 API 서버 Origin 설정 기능
- FastAPI exact-origin CORS allowlist 및 credentials 지원
- cross-origin cookie SameSite 설정 및 HTTPS Secure 처리
- Cloud Run workflow의 APP_ALLOWED_ORIGINS / SESSION_COOKIE_SAMESITE / API_PUBLIC_ORIGIN 연결
- 새 `broute-config.js`를 Docker 및 PWA 캐시에 포함
- CORS 허용/거부, preflight, cookie 및 정적 설정파일에 대한 회귀검사 추가

## 실행 구조

- GitHub: 소스 코드, 버전 관리, CI
- 프런트엔드: `index.html`, `admin.html`
- API: `cloud-functions/api/index.py` (FastAPI)
- 같은 출처 서비스 실행: `server.py`
- Cloud Run 컨테이너: `Dockerfile`
- 별도 프런트와 API를 연결하는 공개 브라우저 설정: `broute-config.js`

GitHub Pages는 정적 파일만 제공합니다. Python/FastAPI API 서버를 실행하지 않으므로 별도 API 서버가 필요합니다. `broute-config.js`는 이미 실행 중인 API 서버를 가리키는 연결 설정이지, API 서버 자체를 대신하지 않습니다.

## 외부 연결 단계에서 설정해야 할 항목

- 실제 Cloud Run API 서버 주소 및 접근 권한
- `APP_ORIGIN`과 `APP_ALLOWED_ORIGINS`의 정확한 Origin 목록
- 필요한 경우 HTTPS cross-site cookie 설정. 단, 브라우저별 제3자 쿠키 차단 영향은 별도 확인
- TAGO `DATA_GO_KR_SERVICE_KEY` 및 공급자별 실제 상품 승인
- 선택적인 Kakao Local API 키
- OAuth redirect URI 실제 공급자 등록값
- PostgreSQL, Tencent COS, GTFS Feed 및 Worker 구성
- 외부 OSM/Esri 타일 서버에서 실제 타일 응답 확인

현재 검증은 로컬 소스 및 회귀검사이며, 위 외부 운영 연결이 완료됐다고 의미하지 않습니다.
