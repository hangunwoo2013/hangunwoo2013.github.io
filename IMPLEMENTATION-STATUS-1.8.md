# B-ROUTE 1.8 구현 현황 — 교통정보 공급원 어댑터

## 구현
- 공공데이터포털 API 호출을 위한 공통 HTTPX 서버 어댑터
- DATA_GO_KR_SERVICE_KEY 서버 측 사용 및 키/URL 비노출 처리
- 공급원 오류 코드, 시간 초과, 429 등 오류 분리
- 공급원별 응답 TTL 캐시
- 대략적 인스턴스 단위 IP 요청 제한 및 Retry-After 응답
- GET `/transit/providers/status`
- GET `/transit/bus/routes` — BusRoute/getBusRoute
- GET `/transit/rail/cities` — TrainInfo/getCtyCodeList
- GET `/transit/rail/stations` — TrainInfo/getCtyAcctoTrainSttnList
- GET `/transit/rail/trains` — TrainInfo/getStrtpntAlocFndTrainInfo
- TAGO 정류장 실시간 도착정보 응답의 표준화 필드 추가
- 총괄자 전용 POST `/admin/providers/probe`
- 관리자 페이지에 버스/철도 공급원 연결 검사 UI 추가
- 서비스 워커 캐시 버전을 1.8로 증가
- `.env.example`에 TrainInfo 서비스 이름, 요청 timeout, 보조 호출 제한 추가

## 표준화 결과 예시

- Bus route: route id/number/name, origin/destination, province code, mode, source
- Rail station: station id/name, city code, coordinates, mode, source
- Rail train: train number/type, departure/arrival station and time, duration, adult fare, mode, source
- Bus arrival: route, arrival seconds/minutes, remaining stops, vehicle type, stop name, mode, source

실제 API 응답에 따라 필드 이름이 다를 수 있어 여러 표기 후보를 지원하지만, 실제 계정 응답으로 매핑을 최종 확인해야 합니다.

## 아직 구현되지 않은 것
- 1.8 공급원 데이터와 `/route/plan` GTFS 그래프 자동 통합
- TAGO 철도 API 데이터를 이용한 다중 환승 철도 그래프 생성
- 모든 지역의 버스 정류장 순서와 route shape 수집
- TS-BIS 시간표 CSV 자동 수집/정규화
- 각 운영기관별 시간표 예외/공휴일/운행중지 처리
- 실제 API 키로 공급원 샘플 응답 확인
- 여러 서버 인스턴스에서 공유되는 분산 rate limit / API 쿼터 관리
- API 사용량의 일/월간 집계와 무료 한도 자동 차단
- EdgeOne 실제 배포/공급원 네트워크 검사

## 동작상 주의

- 공급원 API 어댑터가 작동한다고 해서 통합 경로 탐색도 자동으로 작동하는 것은 아닙니다.
- 열차 endpoint는 직접 출발역-도착역 구간 시간표입니다.
- 버스 route endpoint는 노선 목록 응답입니다. 정류장 순서 및 시간표는 별도 데이터 공급/수집이 필요합니다.
- 실시간 도착정보는 정기 운행 시간표를 대체하지 않습니다.
- 현재 rate limit은 인스턴스 내부 메모리 기반의 보조 방어입니다. 운영 gateway limit이 별도로 필요합니다.
