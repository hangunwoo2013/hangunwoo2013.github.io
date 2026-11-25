# B-ROUTE 1.6 — 구현 상태

## 이번 버전의 목적
정식 배포 전 비공개 베타를 준비하기 위한 교통 데이터 출처 관리와 GTFS 품질·버전 관리 기반입니다. `?demo=1` 화면 시연만을 위한 빌드가 아니며, 전국 교통정보가 탑재된 최종 베타 버전도 아닙니다.

## 구현됨
- `data_sources`: 총괄자 전용 교통 데이터 공급원 등록/조회/활성화
- 출처별 제공기관, 자료 종류, 교통수단, 국가/지역, 원본 URL, 라이선스, 갱신 주기, 메모 기록
- GTFS ZIP 사전검증 API `/admin/gtfs/validate`
- GTFS 사전검증 이력 `data_import_jobs`
- 데이터 출처를 필수로 지정한 GTFS 가져오기 `/admin/gtfs/import`
- GTFS 파일 checksum SHA-256, 파일 크기, 주요 테이블별 행 수 기록
- GTFS 기본 데이터 관계 및 좌표/시간 구조 검증
- ZIP path traversal, 암호화 ZIP, 중복 텍스트 파일, 비정상 압축률/크기 거부
- `feeds` 출처/버전/적용일/라이선스/원본/체크섬/활성 상태 추가 및 기존 DB 마이그레이션
- `data_releases`에 feed와 source 연결, validation report, 활성화 시각 기록
- 같은 출처에서 새 feed 가져오면 이전 feed 보존 후 신규 버전만 활성화
- 이전 릴리스 재활성화 API `/admin/data/releases/{release_id}/activate`
- 활성 feed만 경로 탐색에 포함
- 관리자 관리판에 데이터 출처 등록, GTFS 검증/가져오기, import 이력, 릴리스 복구 화면 추가
- 버전 1.6.0, Service Worker 캐시 변경

## 직접 가져오기 한도
- 업로드 ZIP: 최대 5MB
- ZIP 전체 압축 해제 용량: 최대 250MB 안전 검사
- 단일 파일 압축 해제: 최대 150MB
- 직접 가져오기 가능: 압축 해제 전체 30MB 이하 + stop_times 200,000행 이하
- 한도보다 크면 검증 결과를 `requires_staging`으로 기록하고 직접 import를 차단합니다.
- 대용량 직접 COS 업로드와 시간 제한에 안전한 배치 importer는 다음 개발 단계입니다.

## 검증에서 지원하지 않는 GTFS 기능
- `frequencies.txt` 기반 빈도 운행: 사전검증 경고 + 직접 가져오기 차단
- GTFS Flex (`locations.geojson`, `booking_rules.txt` 등): 직접 가져오기 차단
- `transfers.txt`, `pathways.txt`: 경고만 제공, 현재 환승 계산에 완전 적용하지 않음
- Asia/Seoul 이외 시간대: 경고 표시
- 확장 route_type은 기록하되, 현재 경로 엔진이 버스/철도로 분류하지 못하는 유형은 검색에서 제외될 수 있음

## 내부 테스트 통과
- Python compile 및 Python 3.10 문법 AST 검사
- main/admin inline JavaScript `node --check`
- HTML ID 중복 검사
- 소형 GTFS 샘플 사전검증 및 import
- invalid ZIP 거부
- 출처 등록/목록/비활성화
- 동일 출처 feed 교체 시 구버전 보존 및 신규 활성화
- 이전 release 복구 후 활성 feed 전환
- import jobs 및 releases 조회
- 버스 데이터만 있을 때 bus mode 경로 성공, rail-only가 버스를 반환하지 않음
- API health 버전 1.6.0 응답

## 아직 실제 검증하지 않은 항목
- 관리형 PostgreSQL 실연결/마이그레이션
- Tencent COS 실버킷 업로드/다운로드 및 대용량 staging
- EdgeOne 배포와 Python 런타임 설치
- 실제 GTFS 공급처별 데이터/라이선스 검증
- 전국 버스·철도 커버리지
- GTFS 실시간/ TAGO 실시간 도착정보 통합
- 모바일/PC 실브라우저 UI/GPS/지도 타일

## 베타 시작 가능 여부
`BETA_RELEASE_APPROVED=false` 유지. 실제 API, 인프라, 데이터셋, 전국 범위 및 현장 경로 검증 전에는 지인 비공개 베타를 시작하지 않습니다.
