# B-ROUTE 1.9 테스트 보고서

실행 환경: 로컬 Python 환경, 테스트별 임시 SQLite DB, 합성 GTFS, HTTP 모의 클라이언트. EdgeOne 배포 및 실 API 호출은 하지 않았습니다.

## 실행 명령과 결과

```bash
python -m py_compile cloud-functions/api/index.py workers/gtfs_import_worker.py
python tests/test_transit_providers_18.py
python tests/test_data_go_http_19.py
python tests/test_gtfs_staging_17.py
python tests/test_rail_transfers_19.py
```

모든 명령 통과.

### 공급 API

- TAGO BusRoutespecificStopInformation의 URL/operation/query parameter 검증
- TAGO TrainInfo 직통 열차 조회 URL 및 `depPlaceId`, `arrPlaceId`, `depPlandTime`, `_type=json` 검증
- 인증키는 서버 요청에만 포함되고 응답/오류에 원문이 나타나지 않는지 검증
- 공급원 인증 오류, quota, HTTP 429/5xx, timeout, JSON 오류 매핑 검증
- 공급자 normalize/cache/관리자 전용 probe 검증

### 철도 환승

- 역 parent ID를 통한 승강장 alias 매칭
- 최소 환승시간 규칙
- 환승 금지 규칙
- 동일 차량 내 환승(type 4)
- 다른 stop ID를 사용하는 같은 역 승강장 간 차량 내 연결
- 이전 운행편 마지막 정류장/다음 운행편 첫 정류장 경계 검사
- 중간 정류장에서 잘못된 linked-trip 점프 차단
- 하차 후 재승차(type 5)
- 환승 규칙 우선순위 및 모호한 충돌 차단
- pathways 단방향/양방향 및 출입구→승강장 이동
- 버스 feed → 역 출입구 → 철도 feed 복합 경로
- bus/rail 개별 필터가 반대 교통수단을 섞지 않는지 확인
- 도보-only 결과가 transit으로 반환되지 않는지 확인

### GTFS 안전성

- station parent hierarchy
- location_type 범위
- transfer stop references와 location type
- transfer key 중복
- station node/exit gate/pathway 규칙
- stop_access=1 pathway endpoint 거부(직접 가져오기/Worker 일치)
- ZIP path traversal 등 대용량 import validator 회귀

### 구문/패키지

- Python compile 통과
- `index.html`, `admin.html` inline JavaScript parse 통과
- ZIP 무결성 확인 예정(패키징 전 최종 실행)

## 테스트가 입증하지 않는 내용

- 실제 공공데이터포털 계정/API 키가 정상인지
- 실제 TAGO API 실서버의 오늘 응답이 문서와 같은지
- 실제 전국 GTFS 데이터가 모두 존재하고 최신인지
- KTDB 파일의 재사용·재배포 권리
- 실제 역 내 환승 도보 시간과 접근성 정확도
- 실제 PostgreSQL/COS/EdgeOne 운영 환경에서의 부하·지속성
