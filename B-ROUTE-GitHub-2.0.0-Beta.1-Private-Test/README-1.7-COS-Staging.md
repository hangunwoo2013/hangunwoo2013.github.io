# B-ROUTE 1.7 — COS 대용량 GTFS 스테이징 및 배치 가져오기

## 목적

1.6의 GTFS 출처/검증/릴리스 관리 기능에 대용량 파일 경로를 추가합니다. 브라우저는 GTFS ZIP 본문을 EdgeOne API에 보내지 않고 COS에 직접 분할 업로드합니다. EdgeOne API는 업로드 초기화·짧은 유효기간의 서명 URL 발급·완료 검증·작업 대기열 등록만 담당합니다. 별도 GTFS Worker가 COS에서 ZIP을 내려받아 검증하고 PostgreSQL에 배치 적재합니다.

**이번 개발 단계에서는 EdgeOne 배포 테스트와 실제 Tencent COS/PostgreSQL 연결 테스트를 하지 않았습니다.** 로컬에서는 모의 COS와 SQLite, 합성 GTFS로 통합 흐름을 검사했습니다.

## 구성

- EdgeOne API: 총괄자 권한 확인, COS multipart 시작, part URL 발급, 업로드 조각 확인, 큐 생성, 재시도/취소
- Tencent COS: 비공개 GTFS 원본 ZIP 보관
- PostgreSQL: source, staging job, progress, feed, release, audit log 저장
- GTFS Worker: 별도 실행 환경에서 ZIP 스트리밍 다운로드/검증, DB 배치 삽입, 활성 릴리스 전환

## 총괄자 사용 순서

1. 총괄자 계정으로 B-ROUTE에 로그인하고 관리판을 엽니다.
2. `데이터 출처`에 GTFS 정적 데이터 출처를 먼저 등록합니다. 제공기관, 국가/지역, 라이선스, 출처 URL, 갱신 주기를 사실에 맞게 적습니다.
3. `대용량 GTFS 업로드`에서 출처, 원본 ZIP, 출처 버전, 적용 기준일을 선택합니다.
4. 브라우저가 COS에 16MB 단위로 직접 전송합니다. 서버 Secret은 브라우저에 내려가지 않습니다.
5. 모든 part 크기를 COS에서 확인한 뒤 업로드를 완료하면 작업 상태가 `queued`가 됩니다.
6. 별도 Worker가 실행 중이어야 작업을 가져옵니다. Worker가 없으면 작업은 `queued` 상태로 대기합니다.
7. Worker가 ZIP 안전성·GTFS 필수 파일/열·정류장/노선/운행 참조·시간표 참조를 검사합니다.
8. 데이터는 5,000행 기본 배치로 비활성 feed에 적재됩니다. 전체 처리가 성공한 마지막 단계에서 새 release만 활성화됩니다.
9. 실패하면 활성 데이터는 그대로 유지됩니다. 재시도는 동일 feed의 부분 데이터를 정리한 뒤 **처음부터 다시 가져옵니다**.
10. 관리판에서 작업 단계, 처리량, Worker heartbeat, 오류를 확인할 수 있습니다.

## 서버 설정

`.env.example`을 기준으로 EdgeOne API와 Worker에 서버 전용 환경변수를 각각 설정합니다.

필수:
- `DATABASE_URL`: 운영용 PostgreSQL 접속 문자열
- `COS_SECRET_ID`, `COS_SECRET_KEY`, `COS_BUCKET`, `COS_REGION`
- `APP_ORIGIN`: 실제 사이트의 정확한 HTTPS Origin
- Google 로그인 및 owner 설정은 기존 1.3 이후 문서 참고

선택/한도:
- `GTFS_STAGING_MAX_BYTES=2147483648` (압축 ZIP 최대 2GiB)
- `GTFS_STAGING_PART_SIZE_MB=16` (최소 8MiB; 2GiB 기준 128개 part)
- `GTFS_WORKER_MAX_UNCOMPRESSED_BYTES=4294967296` (압축 해제 전체 크기 최대 4GiB)
- `GTFS_WORKER_MAX_MEMBER_BYTES=3221225472` (개별 파일 최대 3GiB)
- `GTFS_WORKER_BATCH_ROWS=5000` (500~20,000 범위로 제한)
- `GTFS_WORKER_POLL_SECONDS=15`
- `GTFS_WORKER_HEARTBEAT_TTL_SECONDS=120`
- `GTFS_WORKER_ID`: 여러 Worker를 운용할 때 구분할 고유 ID

Worker가 임시 디스크에 압축 ZIP, 검증용 SQLite 인덱스, 런타임 파일을 만듭니다. 최소 여유 디스크는 압축파일과 압축 해제 데이터의 합계보다 넉넉하게 확보해야 합니다. 4GiB 제한을 그대로 쓰려면 이보다 큰 임시 디스크가 필요합니다.

## COS 설정 및 보안

- 버킷은 반드시 비공개로 둡니다.
- 별도 최소권한 계정/역할을 만들고 `gtfs-staging/` 접두어에서 필요한 multipart 업로드·조회·완료·중단·다운로드·삭제 작업만 허용합니다.
- Bucket CORS는 `APP_ORIGIN` 정확한 주소만 허용하고 `PUT`, `OPTIONS`, 필요한 요청 헤더를 허용합니다. 운영에서 Origin `*` 사용은 피합니다.
- part 서명 URL은 15분 후 만료됩니다. 브라우저는 최대 8개씩 URL을 요청합니다.
- 서버는 브라우저가 보내는 ETag 값을 믿지 않고 COS의 part 목록과 실제 part 크기를 확인합니다.
- 미완료 multipart upload 정리와 staging 객체의 보관/만료 기간을 COS Lifecycle로 정합니다. 현재 애플리케이션은 완료된 원본 ZIP을 자동 삭제하지 않습니다.

## GTFS 지원 범위와 한계

현재 Worker는 기본적인 GTFS Schedule의 `agency.txt`, `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt` 및 `calendar.txt` 또는 `calendar_dates.txt`를 다룹니다. `shapes.txt`는 선택적으로 가져옵니다.

현재는 `frequencies.txt`와 GTFS Flex 파일을 가져오지 않고 거부합니다. `transfers.txt`와 `pathways.txt`가 있으면 경고하지만 모든 환승 제약이나 역 내부 통로를 경로 엔진에 반영하지 않습니다. 한국 이외 시간대는 경고합니다.

검증 통과는 파일 구조와 일부 참조 무결성 검사 통과를 뜻합니다. 실제 노선 운행 여부, 지역 커버리지 완전성, 공휴일 예외, 현장 시간표 정확성, 실시간 도착정보를 보증하지 않습니다. 데이터 원본의 이용약관/라이선스도 총괄자가 확인해야 합니다.

## 재시도, 복구, 운영 주의사항

- Worker는 별도 컴퓨팅 환경에서 계속 실행해야 합니다. EdgeOne API 요청 종료 후에도 Worker가 자동으로 실행되는 구조가 아닙니다.
- Worker 처리 중에는 heartbeat와 job 임대 시간을 갱신합니다. 15분 이상 heartbeat/작업 업데이트가 끊긴 processing job은 다음 Worker가 회수할 수 있습니다.
- 재시도는 마지막 행부터 이어서 하는 체크포인트 재개가 아닙니다. 동일 feed의 부분 적재 데이터를 지우고 처음부터 다시 가져옵니다.
- 새 feed는 최종 완료 전까지 비활성입니다. 완료 시 마지막 DB 트랜잭션에서 이전 활성 feed를 보관 상태로 전환하고 새 feed를 활성화합니다.
- staging ZIP은 기본적으로 COS에 남습니다. 저장 비용/개인정보/라이선스 조건에 맞는 자동 만료 정책을 설정해야 합니다.
- 별도 Worker의 상시 실행 비용이 생길 수 있습니다. 월 0원 목표에 맞는 무료 실행 환경이 실제로 있는지, sleep/cold start/실행 한도와 비용을 검증한 뒤 채택해야 합니다. 무료를 보장하지 않습니다.

## 로컬 모의 테스트

프로젝트 루트에서 API/Worker 의존성을 설치한 후 개발용 SQLite와 Fake COS를 사용하는 테스트를 실행합니다. 테스트는 합성 GTFS만 사용하며 운영 서버를 호출하지 않습니다.

```bash
python -m py_compile cloud-functions/api/index.py workers/gtfs_import_worker.py
python tests/test_gtfs_staging_17.py
```

운영 배포 전에는 별도 staging 환경에서 PostgreSQL·COS·Bucket CORS·실제 Worker를 함께 검증해야 합니다. 이번 버전 제작 중에는 EdgeOne 배포 테스트를 진행하지 않았습니다.
