# B-ROUTE Local 1.6 — Data Governance & GTFS Validation

## 목적
1.5의 운영 기반을 유지하면서 교통 데이터 출처·품질·버전 이력을 관리하는 기반을 추가합니다. 이 버전은 전국 데이터 자동 수집 또는 비공개 베타 승인 버전이 아닙니다.

## 추가 사항
- 관리자 전용 교통 데이터 출처 등록/활성화 관리 API 및 관리판 UI
- GTFS Schedule 사전검증: 필수 파일/열, 정류장 좌표, 기본 ID 중복, route/trip/stop 참조, 시간·정류장 순서 형식 확인
- ZIP 경로 탈출·암호화·중복 파일·비정상 압축률·압축 해제 용량 검사
- 데이터 파일 SHA-256 및 파일 크기/행 수/게시자/route_type 검사 결과 기록
- `data_import_jobs` 가져오기 및 사전검증 이력
- `feeds`에 출처, 버전, 적용 기준일, 라이선스, 원본 URL, checksum, 활성 여부 메타데이터 추가
- 데이터 릴리스 기록과 출처별 활성 버전 교체
- 이전 GTFS 데이터 릴리스 활성화/복구
- 경로 탐색은 활성 feed만 이용하도록 변경
- 관리자 페이지에서 출처 등록, GTFS 사전검증, 소형 파일 가져오기, import 이력, 릴리스 복구 지원
- API/관리판/서비스워커/manifest 버전 1.6 갱신

## 제한
- 일반 EdgeOne 함수 업로드는 5MB, 압축 해제 데이터는 30MB, stop_times는 20만 행 이내만 직접 가져오기 가능
- 대용량 GTFS COS staging 및 배치 import는 아직 구현되지 않음
- GTFS-Realtime, TAGO 실시간 도착, 철도 별도 시간표 원본을 GTFS Static importer가 자동 가져오지는 않음
- `frequencies.txt`와 GTFS Flex 자료는 현재 엔진 미지원으로 직접 활성화 차단
- `transfers.txt`/`pathways.txt`는 경고만 제공하며 완전 적용하지 않음
- 실제 전국 커버리지·운행 현장 정확성은 보증하지 않음
- EdgeOne 배포/실제 PostgreSQL/COS/API 키 연결은 이 단계에서 테스트하지 않음
