# B-ROUTE 2.0.0-beta.2 — 지도 및 API 연결 수정

## 이번 수정

- OpenStreetMap 타일 주소를 공식 canonical URL `https://tile.openstreetmap.org/{z}/{x}/{y}.png`로 변경했습니다.
- HTML과 FastAPI 응답의 Referrer-Policy를 `strict-origin-when-cross-origin`으로 바꿨습니다. 외부 타일 제공자에 사이트 Origin Referer를 보낼 수 있도록 한 설정입니다.
- 일반 지도 타일이 연속 실패하고 성공 타일이 하나도 없으면 기존 Esri 지형도로 자동 전환합니다. 지도 우측 상단에서 일반 지도를 다시 선택할 수 있습니다.
- `broute-config.js`를 추가했습니다. 화면과 관리자 페이지가 같은 API 주소 설정을 읽습니다.
- 백엔드에 정확한 Origin allowlist CORS를 추가했습니다. 와일드카드(`*`)는 사용하지 않습니다.
- 세션 쿠키 SameSite를 설정으로 바꿨고, `None`이면 Secure HTTPS 쿠키만 내보냅니다.
- 개발 서버, Docker 이미지, PWA 캐시에 `broute-config.js`를 포함했습니다.

## API 주소 설정

### 권장: 프런트엔드와 API를 같은 Cloud Run 출처에서 운영

`broute-config.js`를 아래와 같이 비워 둡니다.

```js
window.BROUTE_CONFIG = Object.freeze({
  apiBaseUrl: ""
});
```

이 경우 화면은 같은 출처의 `/api`를 사용합니다. 현재 B-ROUTE의 가장 단순하고 로그인 쿠키에도 유리한 배포 방식입니다. GitHub는 소스 저장소와 Actions 빌드/배포를 담당하고, 실행은 Cloud Run이 담당합니다.

### 별도 정적 프런트엔드 + 별도 API 서버

예를 들어 GitHub Pages로 화면을 제공하고 API는 별도 Cloud Run 서비스에 둔다면, `broute-config.js`의 `apiBaseUrl`에 API 서버 Origin만 넣습니다. `/api` 경로는 앱이 자동으로 붙입니다.

```js
window.BROUTE_CONFIG = Object.freeze({
  apiBaseUrl: "https://YOUR-API-SERVICE.run.app"
});
```

이 주소는 예시입니다. 실제 Cloud Run 서비스 주소로 바꿔야 합니다. API 서버의 Cloud Run IAM 설정이 브라우저 요청을 허용해야 하며, 베타 배포는 기본적으로 익명 접근이 꺼져 있으므로 테스터의 접근 방식도 별도로 설정해야 합니다.

Cloud Run 환경변수:

- `APP_ORIGIN`: 프런트엔드의 정확한 Origin (경로 제외)
- `APP_ALLOWED_ORIGINS`: 추가 허용 Origin을 세미콜론으로 구분 (예: `https://owner.github.io;https://tester.github.io`)
- `SESSION_COOKIE_SAMESITE`: 기본 `lax`; 서로 다른 사이트 간 세션 쿠키가 필요한 경우 HTTPS에서 `none`
- `API_PUBLIC_ORIGIN`: GitHub Actions 배포 시 OAuth callback 기본 주소를 둘 API 서버의 Origin으로 지정. 동일 출처면 프런트 Origin과 같게 둡니다.

Origin은 `https://`를 포함한 도메인만 입력하고 마지막 경로는 넣지 않습니다. 허용 목록에 `*`를 넣지 마세요.

**주의:** `SameSite=None`과 CORS를 설정해도 브라우저의 제3자 쿠키 차단 정책까지 우회하는 것은 아닙니다. GitHub Pages와 `run.app`처럼 서로 다른 사이트에서 Google/Naver/Microsoft 로그인 세션을 공유하면 브라우저에 따라 로그인이 유지되지 않을 수 있습니다. 인증을 포함한 전체 기능에는 같은 출처 Cloud Run 운영 또는 소유 도메인의 같은 사이트 하위 도메인 구성이 더 안정적입니다.

## 교통 API 및 경로 엔진

- `DATA_GO_KR_SERVICE_KEY`는 Cloud Run Secret Manager에만 등록합니다. `broute-config.js`, HTML, GitHub 공개 코드에 넣으면 안 됩니다.
- `KAKAO_REST_API_KEY`는 장소 검색 보조용 선택 설정입니다. 미등록 시 앱의 Photon 대체 검색 경로를 사용할 수 있습니다.
- TAGO 키가 있다고 전국 버스·철도 경로검색이 자동으로 완성되는 것은 아닙니다. 상품별 승인/요청변수/지역 커버리지 확인과 시간표 데이터가 필요합니다.
- 다중 환승 시간 계산은 운영 PostgreSQL의 유효한 GTFS 데이터셋이 준비되어야 합니다. 관리판의 공급자별 probe는 각각의 API 상품을 따로 확인하는 용도입니다.

## GitHub에 업데이트하는 방법

1. 압축을 풀어 `B-ROUTE-GitHub-2.0.0-Beta.2-Map-API-Fix` 폴더 안의 파일 전체를 기존 GitHub 저장소 파일 위에 덮어씁니다.
2. `broute-config.js`에서 API 주소를 설정합니다. 같은 출처 Cloud Run이면 빈 문자열 그대로 둡니다.
3. GitHub에 commit/push 합니다. 이 작업만으로 외부 Cloud Run이 자동 배포되지는 않습니다. 배포 workflow 조건과 GitHub Variables/Secrets가 준비된 경우에만 Cloud Run이 갱신됩니다.
4. 브라우저에서 강력 새로고침(Ctrl+Shift+R)을 하거나 설치형 앱을 완전히 종료 후 다시 엽니다. PWA 캐시 이름도 beta.2로 변경했습니다.

## 검사 범위

이 버전의 회귀검사는 로컬 테스트, 가짜 Origin을 이용한 CORS/쿠키 테스트, 프런트엔드 정적 검사와 로컬 HTTP 응답만 확인합니다. 실제 OSM/Esri 타일, TAGO/Kakao 공급자, OAuth, Cloud Run IAM, 실제 전국 노선 커버리지는 이 환경에서 외부 요청/실계정 없이 검증했다고 주장하지 않습니다.
