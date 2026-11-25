# B-ROUTE 1.91 내부 테스트 보고서

## 실행 환경

- 로컬 Python 환경
- FastAPI TestClient
- 합성 API 응답 및 mock HTTP client
- 로컬 SQLite 테스트 DB
- 합성 GTFS 테스트 파일
- EdgeOne 배포 및 외부 실 API 호출 미실행

## 실행 명령 및 결과

```bash
python -m py_compile cloud-functions/api/index.py workers/gtfs_import_worker.py
python tests/test_transit_providers_191.py
python tests/test_data_go_http_191.py
python tests/test_gtfs_staging_17.py
python tests/test_rail_transfers_19.py
```

결과:

- PASS: 공식 공급원 서비스/오퍼레이션 규약, 8개 총괄자 API 검사, 정류소 경유노선 파라미터 대소문자, 버스·철도 정규화, 캐시, 권한, 입력 검증, 키 비노출, 요청 제한
- PASS: TAGO HTTP URL/파라미터 계약, 서버 전용 키 처리, resultCode 매핑, 호출량/HTTP 오류, timeout 및 JSON 오류 처리
- PASS: COS 분할 업로드 모의, 비총괄자 거부, 업로드 part 검증, ZIP 경로 탈출 방지, GTFS 검증·가져오기·버전 활성화·Worker heartbeat
- PASS: GTFS 구조 검증 및 환승/경로 관련 회귀 테스트
- PASS: Python 구문 컴파일
- PASS: index.html/admin.html 중복 ID 없음 및 인라인 JavaScript `node --check`

## 범위 한계

위 결과는 API 계약을 로컬에서 모의 검증한 것입니다. 실제 API 키로 data.go.kr 호출 성공, 상품별 활용신청 승인, 실제 지역별 데이터 수신, 전국 pagination 완주, 실제 COS/PostgreSQL 연결, 모바일 브라우저 실사용, EdgeOne 배포는 확인하지 않았습니다.
