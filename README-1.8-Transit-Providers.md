# B-ROUTE 1.8 — 실제 교통정보 공급원 어댑터

## 목표

1.7의 GTFS 대용량 수집 기반 위에 공공 교통 API를 서버 측에서 호출하는 어댑터를 추가합니다. 일반 이용자는 API 키를 입력하지 않습니다. `DATA_GO_KR_SERVICE_KEY`는 EdgeOne API의 서버 Secret에만 설정하고 브라우저/HTML/응답 JSON에 반환하지 않습니다.

이번 단계는 **공급원 연결 계층**입니다. 실제 전국 다중환승 경로 계산이 완성된 단계는 아닙니다.

## 연결한 공식 공급원 및 요청

### 1. 국토교통부 버스노선 API

- 서비스: `BusRoute`
- 기능: `getBusRoute`
- 요청: `opr_ymd`(운행일), `ctpv_cd`(시도 코드), 선택 `rte_id`, `pageNo`, `numOfRows`, `dataType=JSON`
- 구현 주소: `GET /transit/bus/routes`
- 지역·운행일 기준의 노선 목록 메타데이터를 반환합니다.
- 이 API 응답만으로 노선별 완전한 정류장 순서, 정류장 좌표, 배차/시간표, 노선 shape가 전부 제공된다고 가정하지 않습니다.

공식 명세: https://www.data.go.kr/data/15142030/openapi.do

별도 공식 자료인 `국토교통부_버스노선별 경유정류장`(식별자 15142031)은 노선별 정류장 순번/ID/이름을 제공 대상으로 설명하고 별도 서비스 경로 `BusRoutespecificStopInformation`을 안내합니다. 다만 현재 확인한 포털 명세 추출본에는 호출 operation 이름이 명확히 표시되지 않아 1.8에서는 임의의 operation을 추측해 연결하지 않았습니다. 다음 단계에서 제공 가이드 원문을 확인하고 정확한 operation/응답 필드를 검증한 뒤 연결합니다. 공식 명세: https://www.data.go.kr/data/15142031/openapi.do

### 2. TAGO 열차정보

- 서비스 기본값: `TrainInfo` (`TAGO_TRAIN_SERVICE_NAME`으로 경로 이름 재정의 가능)
- `getCtyCodeList`: 도시 코드 목록 — `GET /transit/rail/cities`
- `getCtyAcctoTrainSttnList`: 도시별 기차역 목록 — `GET /transit/rail/stations?city_code=...`
- `getStrtpntAlocFndTrainInfo`: 출발역·도착역 기준 열차 시간표 — `GET /transit/rail/trains?dep_station_id=...&arr_station_id=...&departure_date=YYYYMMDD`
- 열차 API는 KTX를 포함한 구간별 열차 시간표를 제공하지만, 현재 어댑터는 선택한 두 역 사이의 편성 목록을 반환합니다. 여러 열차 환승을 포함한 전체 철도 네트워크 검색은 하지 않습니다.

공식 명세: https://www.data.go.kr/data/15098552/openapi.do

### 3. TAGO 버스 도착정보

- 서비스: `ArvlInfoInqireService`
- 기능: `getSttnAcctoArvlPrearngeInfoList`
- 요청: `cityCode`, `nodeId`
- 구현 주소: `GET /transit/stops/{node_id}/arrivals?city_code=...`
- `arrtime`은 초 단위 도착예정시간이고 노선 번호, 남은 정류장 수, 차량 유형도 표준화합니다.
- 실시간 도착예정 정보와 정기 시간표는 별개의 데이터입니다.

공식 명세: https://www.data.go.kr/data/15098530/openapi.do

### 4. 보조 후보 — 한국교통안전공단 버스 노선/시간표 파일

한국교통안전공단의 TS-BIS 버스 노선 및 시간표 CSV는 운행요일, 일일 운행횟수, 기점 첫차/막차, 배차간격 등의 필드를 제공합니다. 공개 설명은 2026년 7월 기준 데이터를 안내하며 갱신 주기는 연간입니다. 이 CSV의 자동 다운로드·매핑·GTFS 변환은 1.8에 포함하지 않았고 후속 데이터 소스 통합 작업으로 남깁니다.

공식 자료: https://www.data.go.kr/data/15150451/fileData.do

## 서버 API 사용

### 공급원 상태 (공개, 비밀값 미포함)

`GET /transit/providers/status`

### 관리자 연결 검사

`POST /admin/providers/probe`

예시 본문:

```json
{"provider":"tago_rail"}
```

버스 지역 노선 API 확인:

```json
{"provider":"tago_bus","province_code":"26","operation_date":"20261124"}
```

이 검사는 실제 공급원에 요청을 보냅니다. 올바른 API Secret을 입력한 뒤 총괄자 계정으로 실행하세요. 일반 계정은 403으로 차단됩니다.

### 노선 및 열차 검색

```text
GET /transit/bus/routes?province_code=26&operation_date=20261124&page=1&page_size=100
GET /transit/rail/cities
GET /transit/rail/stations?city_code=21&page=1&page_size=100
GET /transit/rail/trains?dep_station_id=NAT010000&arr_station_id=NAT014445&departure_date=20261124
GET /transit/stops/DJB8001/arrivals?city_code=21
```

예시 ID는 API 형식 설명용이며 실제 공급원에서 반환된 유효 ID를 확인해 넣어야 합니다.

## 환경변수

```env
DATA_GO_KR_SERVICE_KEY=서버전용_공공데이터포털_인증키
TAGO_TRAIN_SERVICE_NAME=TrainInfo
DATA_GO_REQUEST_TIMEOUT_SECONDS=15
PROVIDER_RATE_LIMIT_PER_MINUTE=60
```

일부 오래된 승인 계정이 다른 열차 서비스 경로로 발급되어 있는 경우에만 실제 승인 문서를 확인한 후 `TAGO_TRAIN_SERVICE_NAME`을 변경합니다. 기본값을 임의로 바꾸지 마세요.

## 보안과 호출 제한

- 인증키는 서버에서만 요청 파라미터로 전달합니다.
- 요청 URL/예외 전문을 로그나 오류 메시지로 반환하지 않습니다.
- 공급원 오류 메시지에 키 원문이 포함되면 `[REDACTED]`로 대체합니다.
- 동일 공급원 응답은 종류별 TTL 캐시를 적용합니다. 실시간 도착정보는 캐시하지 않습니다.
- 인스턴스 단위 보조 요청 제한을 적용합니다. 서버리스 인스턴스가 여러 개일 때 이 제한만으로 전체 쿼터가 보호되지는 않습니다. 운영 전 EdgeOne Gateway/WAF에 IP/계정별 글로벌 제한을 별도로 설정해야 합니다.
- 공급원 개발/운영 계정의 실제 트래픽 한도와 신청 조건은 사용자가 발급한 계정에서 확인해야 합니다. 공공데이터포털의 버스노선 API와 TAGO 열차 API는 신청 트래픽/운영 계정 조건이 서로 다를 수 있습니다.

## 중요한 기능 경계

- `/route/plan`은 계속 활성 GTFS 정적 feed를 사용합니다.
- 1.8에서 추가한 TAGO 열차 직접 구간 조회와 버스 노선 카탈로그는 아직 GTFS 경로 그래프에 자동 편입되지 않습니다.
- 따라서 실제 TAGO API 키가 설정되어도 이것만으로 전국 버스+철도 통합 다중환승 길찾기가 완료되지는 않습니다.
- 다음 단계에서는 버스 노선별 정류장 순서 자료, 역/철도 구간 연결, 서비스 달력, 시간표, transfer mapping, GTFS source의 라이선스/범위를 확인해 공통 그래프에 편입해야 합니다.
- 버스 시간표 CSV는 별도 파일 데이터이며 연간 갱신이므로 실시간 도착정보로 취급하지 않습니다.

## 로컬 테스트

프로젝트 루트에서 실행:

```bash
python -m py_compile cloud-functions/api/index.py workers/gtfs_import_worker.py
python tests/test_transit_providers_18.py
python tests/test_gtfs_staging_17.py
```

테스트는 합성 응답만 사용합니다. 실제 API 키 및 EdgeOne 배포는 사용하지 않습니다.
