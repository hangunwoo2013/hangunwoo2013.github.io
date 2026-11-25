# B-ROUTE 2.0 Beta Test

현재 기준 소스는 **2.0.0-beta.2 비공개 베타 테스트 후보**입니다.

2.0 Beta Test는 정식 공개 전에 초대된 테스터가 기능과 사용성을 체험하고 피드백을 주는 단계입니다. 실제 API 공급자 연결이나 외부 서비스 배포가 아직 끝나지 않은 것은 이번 소스 검사 실패가 아니라, 이후 API 연결 작업에서 진행할 별도 항목입니다.

## 시작 안내

- 최신 변경 안내: `README-2.0.0-beta.2-Map-API-Fix.md`
- API 연동 계획: `NEXT-STEPS-2.0-BETA-API.md`
- 구현 현황: `IMPLEMENTATION-STATUS-2.0.0-beta.2.md`
- 테스트 보고서: `TEST-REPORT-2.0.0-beta.2.md`
- 환경변수 예시: `.env.example`

## beta.2 핵심 수정

- OpenStreetMap 타일 주소와 Referer 정책 수정
- 타일 요청 실패 시 Esri 지형도 레이어로 자동 전환
- `broute-config.js`로 별도 API 서버 주소 설정 지원
- FastAPI에 명시적 Origin 기반 CORS 및 credential 지원
- cross-origin 세션 쿠키 SameSite 설정
- GitHub Actions와 Cloud Run 구성 변수 연결

## 로컬 검사 결과

- `python -m pytest -q`: 1 passed
- `python scripts/run_regression.py`: 11개 독립 회귀 시나리오 통과
- Python 3.11 구문, JavaScript, HTML 참조, GitHub Actions YAML/Bash 검사 통과
- 허용/비허용 Origin, CORS preflight, Secure SameSite=None 쿠키 테스트 통과

실제 API 서버·키·외부 지도 타일·OAuth·메일·DB·COS·Cloud Run은 이 로컬 검사에서 연결했다고 주장하지 않습니다.

## API 서버 주소

- 같은 출처로 프런트엔드와 FastAPI를 Cloud Run에서 함께 운영하면 `broute-config.js`의 `apiBaseUrl`을 빈 문자열로 둡니다.
- GitHub Pages 등 정적 프런트엔드와 API 서버를 나누면 `broute-config.js`의 `apiBaseUrl`에 API 서버 Origin을 지정하고, 백엔드 `APP_ALLOWED_ORIGINS`에 프런트엔드 Origin을 정확히 등록합니다.
- 외부 API 서버는 실제로 실행 중이어야 합니다. 설정 파일에 URL을 입력하는 것만으로 서버가 생성되지는 않습니다.
- `DATA_GO_KR_SERVICE_KEY`와 `KAKAO_REST_API_KEY` 등은 브라우저 파일이 아니라 서버 Secret에만 저장합니다.

상세 설정, GitHub Pages와 Cloud Run 차이, 인증 쿠키 주의사항은 `README-2.0.0-beta.2-Map-API-Fix.md`를 참고하세요.
