# B-ROUTE 2.0.0-beta.2 테스트 보고서

검사일: 2026-11-26
검사 기준: 새로 추출한 2.0.0-beta.2 소스 폴더의 로컬 검사. 외부 API/Cloud Run 배포 테스트는 범위에 포함하지 않음.

## 결과 요약

- `python -m pytest -q`: **1 passed**
- `python scripts/run_regression.py`: **11개 독립 회귀 시나리오 모두 통과**
- Python 컴파일 및 Python 3.11 문법 호환 검사: 통과
- Node.js v22.16.0 구문 검사: 메인 페이지, 관리자 페이지, Service Worker, `broute-config.js` 통과
- HTML 요소 ID 및 JavaScript 참조 검사: 메인 95개 ID / 96개 참조, 관리자 63개 ID / 63개 참조 모두 통과
- GitHub Actions YAML 및 workflow 내 Bash 구문 검사: 3개 workflow 통과
- 단일 출처 FastAPI + 정적 화면 smoke test: 메인 페이지, 관리자 페이지, manifest, API config JS, `/api/health`, 보호된 경로 및 준비상태 일관성 통과
- CORS 격리 테스트: 허용 Origin의 GET/OPTIONS/POST 통과, 미허용 Origin의 상태 변경 요청 403, 허용되지 않은 Origin에는 CORS 허용 헤더 미발급
- HTTPS cross-origin 세션 쿠키 테스트: `SameSite=None; Secure` 확인
- 비밀 파일 검사: `.env` 없음, `broute-config.js`에 공급자 API 키 없음
- ZIP 무결성: 생성한 최종 압축본에 `unzip -t` 실행, 오류 없이 통과

## 수정 사항

1. OSM 타일 주소를 `https://tile.openstreetmap.org/{z}/{x}/{y}.png`로 교체.
2. 메인 HTML과 FastAPI 응답 Referrer-Policy를 `strict-origin-when-cross-origin`으로 변경.
3. OSM 타일 오류가 일정 수준 이상이고 정상 타일보다 실패가 많으면 기존 Esri 지형도 레이어로 자동 전환.
4. `broute-config.js`에 API 서버 Origin을 입력할 수 있도록 설정 파일 추가. 빈 문자열은 현재 출처 `/api`를 사용.
5. 메인/관리자 화면의 API 요청이 같은 출처 또는 외부 API Origin을 선택하고, 외부 API면 credentials를 포함.
6. FastAPI CORS를 명시적 Origin 목록으로 설정. 허용 Origin 외부에는 credentialed CORS를 제공하지 않음.
7. `APP_ALLOWED_ORIGINS`, `SESSION_COOKIE_SAMESITE` 및 OAuth callback용 `API_PUBLIC_ORIGIN` 배포 설정 추가.
8. 세션 쿠키의 생성과 삭제에 동일한 SameSite 설정을 사용하며, HTTPS가 아닐 때 `None`을 `lax`로 낮춰 개발 쿠키가 거부되지 않도록 처리.
9. 로컬 정적 파일 허용 목록, Docker 이미지 및 Service Worker 캐시에 새 브라우저 설정 파일 포함.

## 확인하지 않은 사항

- 외부 인터넷 요청으로 OSM/Esri 타일이 실제 브라우저에 표시되는지 여부. 현재 작업 환경에서 외부 타일 서버를 실시간 확인하지 않았음.
- 실제 공공데이터포털/TAGO/Kakao API 연결 및 키별 상품 승인 상태.
- Google/Naver/Microsoft 실계정 OAuth, 실메일 발송, PostgreSQL, Tencent COS, GTFS Worker 운영 연결.
- Cloud Run IAM 권한, 별도 API 서버 배포 및 실제 GitHub Actions 실행.
- Docker 이미지 빌드. 현재 작업 환경에 Docker 실행 파일이 설치되어 있지 않음.
- 여러 브라우저에서 cross-site 쿠키가 유지되는지. 일부 브라우저는 제3자 쿠키를 자체 정책으로 차단할 수 있으므로 인증은 같은 출처 또는 같은 사이트 하위 도메인 구성을 권장.

## 산출물

- 업데이트 폴더: `B-ROUTE-GitHub-2.0.0-Beta.2-Map-API-Fix/`
- 패키지 파일 수: 103개
- 폴더 크기: 약 1.1 MB
- ZIP 크기: 약 296 KB

## 판정

소스 코드와 로컬 회귀검사는 통과했다. 이 결과는 지도 공급자 서버가 실제 요청을 허용한다거나 교통 API가 실계정으로 연결되었다는 뜻이 아니다. 실제 API 공급자 연결은 서버 주소와 서버 Secret을 구성한 다음 별도 작업으로 시작한다.
