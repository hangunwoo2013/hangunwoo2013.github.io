# B-ROUTE 1.9 — Rail Transfer Engine

## 목표

1.8에서 남아 있던 핵심 문제는 TAGO 열차 API가 출발역·도착역 사이의 열차를 조회할 뿐, 여러 열차·노선을 연결하는 전체 철도 환승 그래프를 제공하지 않는다는 점이었습니다.

1.9는 실제 철도 다중환승 계산을 GTFS 정적 시간표 그래프에서 수행하도록 보강합니다. TAGO API는 역·직통 열차 조회 보조 수단으로 유지하고, 버스·철도 통합 환승은 GTFS의 `stops.txt`, `trips.txt`, `stop_times.txt`, `transfers.txt`, `pathways.txt` 및 `parent_station` 정보를 이용합니다.

## 1. 철도 환승 계산

### 시간표 그래프

- `stop_times.txt`에서 운행편별 정류장 간 연결 edge를 구성합니다.
- `calendar.txt`와 `calendar_dates.txt`를 이용해 검색 날짜의 운행편을 선택합니다.
- 자정 이후 시간(`24:xx:xx` 등)을 포함한 GTFS 운행 시간을 처리합니다.
- 출발·도착 접근 도보를 포함하되, 실제 버스/철도 탑승이 하나도 없는 도보-only 결과는 대중교통 경로로 반환하지 않습니다.

### `transfers.txt`

다음 규칙을 처리합니다.

| transfer_type | 처리 |
|---|---|
| 0 | 권장 환승, 기본 환승 여유 시간 적용 |
| 1 | 시간 연계 환승, 공급 데이터가 제공하는 최소 시간 적용 |
| 2 | `min_transfer_time` 이상이어야 환승 허용 |
| 3 | 해당 환승 금지 |
| 4 | 동일 차량 내 환승, 환승 횟수에서 제외 |
| 5 | 하차 후 재승차, 하차·재승차 최소 시간 적용 |

- `from_trip_id`/`to_trip_id`, `from_route_id`/`to_route_id`의 GTFS 규칙 우선순위를 적용합니다.
- 동일한 최우선 규칙이 충돌하면 임의로 선택하지 않고 해당 연결을 거부합니다.
- linked trip의 `transfer_type=4/5`는 이전 trip의 마지막 정류장과 다음 trip의 첫 정류장 경계에서만 적용합니다.
- `transfer_type=4`는 다른 stop ID를 쓰더라도 같은 parent station 또는 100m 이내의 동일한 물리적 종점/시작점으로 확인되면 차량 내 연결 후보로 처리합니다. 임의 도보 환승을 만들지 않습니다.

### `pathways.txt`와 역 내부 환승

- 역 출입구(location_type=2), 플랫폼(location_type=0), 일반 역내 노드(location_type=3), 탑승구역(location_type=4)를 연결합니다.
- 단방향/양방향을 구분합니다.
- 계단, 에스컬레이터, 이동 보도, 엘리베이터, 요금 게이트, 출구 게이트의 이동 시간을 반영합니다.
- 출구 게이트는 GTFS에 따라 양방향 연결을 허용하지 않습니다.
- 역에 `pathways.txt`가 제공되면 플랫폼 간 임의 지름길을 만들지 않습니다.
- `stop_access=1` 노드는 pathways에 사용할 수 없도록 API 직접 가져오기와 대용량 Worker 검증을 일치시켰습니다.

### 버스 feed ↔ 철도 feed

- 별도 feed 사이 연결은 좌표가 가까운 정류장/역 출입구를 찾아 환승 후보를 만듭니다.
- 철도 출입구가 있으면 먼저 출입구에 연결하고, 없을 때만 승강장/탑승구역으로 보수적으로 fallback합니다.
- 같은 feed 내부에서는 단순 직선 거리로 플랫폼을 연결하지 않고 `pathways.txt`, `parent_station`, 명시적 환승 규칙을 우선합니다.
- 서로 다른 feed 사이의 도보 시간은 좌표 거리 기반 추정치입니다. 실제 보행 네트워크, 횡단보도, 출입 제한, 역사 내부 운영 동선까지 보장하지 않습니다.

## 2. 교통수단 필터

`/route/plan`은 세 모드를 지원합니다.

- `bus`: 버스만 탑승
- `rail`: 철도만 탑승
- `transit`: 버스와 철도 혼합 탑승

도보는 세 모드 모두 접근·환승·도착 이동에 사용할 수 있습니다. 선택한 교통수단 외의 차량이 결과에 섞이지 않습니다.

## 3. 실제 API 연결

### 공공데이터포털 / TAGO

서버 Secret:

```env
DATA_GO_KR_SERVICE_KEY=서버전용_인증키
TAGO_TRAIN_SERVICE_NAME=TrainInfo
DATA_GO_REQUEST_TIMEOUT_SECONDS=15
PROVIDER_RATE_LIMIT_PER_MINUTE=60
```

주요 요청은 1.8에서 연결한 공급원 어댑터를 유지합니다.

- 버스 노선 목록: `BusRoute/getBusRoute`
- 노선별 경유 정류장: `BusRoutespecificStopInformation/getBusRoutespecificStopInformation`
- 열차 도시 코드: `TrainInfo/getCtyCodeList`
- 도시별 역 목록: `TrainInfo/getCtyAcctoTrainSttnList`
- 출발·도착 역 사이 열차: `TrainInfo/getStrtpntAlocFndTrainInfo`

API 키는 서버에서만 추가합니다. 브라우저나 API 결과에 인증키를 반환하지 않습니다.

중요: TAGO의 출발·도착역 직통 열차 조회는 하나의 역간 열차 정보를 반환합니다. 여러 열차/노선의 환승 네트워크를 자동으로 구성하지 않습니다. 철도 다중환승 그래프는 활성 GTFS feed에서 계산합니다.

### API 오류 처리

- HTTP 429 또는 공급원 quota 오류: 429
- API 인증/이용 권한 오류: 503
- 응답 시간 초과: 504
- 기타 HTTP/JSON/API 오류: 502
- 오류 문구와 로그에 인증키 원문이 포함되지 않도록 마스킹합니다.

1.9 테스트는 실제 HTTP 클라이언트를 모의해 서비스 경로, query parameter, 키 서버 전용 전달, quota/auth/timeout 처리 규약을 확인합니다. 실제 사용자 키로 외부 공급기관에 연결한 테스트는 아직 수행하지 않았습니다.

## 4. 전국 데이터 소스 전략

### 우선 검토 — 국가교통DB(KTDB) 전국 대중교통 GTFS 기반정보

KTDB는 2026-09-07부터 2025년 3월 기준 전국 대중교통 GTFS 기반정보를 제공한다고 공지했습니다. 공지된 범위는 전국(도서지역 포함), 시내/마을버스, 도시철도, 연안해운, 시외버스, 일반철도, 공항버스, 고속철도, 국내선 항공이며, 정차지·노선·운행회차·경유 정차지 도착/출발 시각표와 도시철도/철도 환승정보를 포함한다고 설명합니다.

중요한 제한:
- 기준 데이터는 2025년 3월 평일 1일입니다.
- 교통접근성 지표 분석용 내부 구축 파일럿이며, 자료 제공 목적이 아니라고 명시되어 있습니다.
- 데이터 ID 체계가 표준화되어 있지 않다고 명시되어 있습니다.
- 신청 자료의 이용조건, 재배포/서비스 활용 허용 여부를 확인하기 전까지 공개 서비스의 단독 원본으로 사용하지 않습니다.

활용 전략:
1. 총괄자가 KTDB 자료 신청 절차를 통해 실제 제공 파일과 이용조건을 확인합니다.
2. 원본 압축파일을 별도 보관하고 체크섬·기준일·라이선스를 기록합니다.
3. 데이터 사전과 ID 관계를 분석하여 B-ROUTE 공통 GTFS 구조로 변환합니다.
4. 1.6/1.7 GTFS 검증·버전 관리·Worker 가져오기 파이프라인을 사용합니다.
5. 2025년 3월 기준 자료는 기준 데이터/연결 검증에만 사용하고, 노선 개편 및 날짜별 시간표는 더 최신 공급원으로 갱신합니다.

### 보완 검토 — 철도산업정보센터(KRIC)

KRIC 철도 데이터 포털은 역사별 도시철도 시간표, 역사별 환승 정보, 환승 이동경로, 출입구-승강장 이동경로 등을 Open API로 목록화하고 있습니다.

- KRIC 역사별 시간표는 운영기관·노선·역·요일 정보를 이용하는 도시철도 보조 데이터 후보입니다.
- 역사별 환승정보와 교통약자 환승 이동경로는 역 내부 연결 그래프를 보완할 후보입니다.
- 데이터 포털에 표시된 일부 항목은 수정일이 오래되었으므로, 실제 등록 계정 응답, 제공 범위, 최신성, 라이선스를 확인한 후 통합합니다.
- 1.9에서는 KRIC 어댑터의 실제 호출·응답 파싱을 구현했다고 주장하지 않습니다. 해당 API의 세부 스키마와 계정 발급이 확인된 후 별도 단계에서 연결합니다.

## 5. 아직 지원하지 않는 항목

- `frequencies.txt` 기반 배차 간격 서비스
- GTFS Flex / 수요응답 교통
- `levels.txt`를 이용한 완전한 층별 이동 네트워크
- 모든 도시철도/철도 KRIC 환승 경로 API 자동 동기화
- 공급기관 전체의 실시간 열차 지연/운행중단 정보
- 보행자 도로망 기반 환승 보행시간의 실제 경로 계산
- 실제 전국 공급자료의 ID 체계 자동 추론 및 전체 지역 커버리지 보증

## 6. 로컬 테스트

프로젝트 루트에서 실행:

```bash
python -m py_compile cloud-functions/api/index.py workers/gtfs_import_worker.py
python tests/test_transit_providers_18.py
python tests/test_data_go_http_19.py
python tests/test_gtfs_staging_17.py
python tests/test_rail_transfers_19.py
```

테스트는 합성 GTFS 및 HTTP 모의 응답을 사용합니다. 실제 공공 API 키로 요청하지 않았고 EdgeOne 배포도 수행하지 않았습니다.
