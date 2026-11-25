# B-ROUTE 1.7.0 — COS 대용량 GTFS 스테이징

## 추가
- 총괄자 브라우저에서 Tencent COS multipart direct upload 시작/파트 URL 발급/완료 처리
- 각 파트 URL은 서버가 짧은 유효기간으로 발급하며 COS Secret은 브라우저에 노출하지 않음
- 업로드 완료 시 `queued` 상태로 GTFS 작업 대기열에 등록
- GTFS staging 작업 목록, 재시도, 취소/업로드 정리 API
- 별도 장기 실행 Worker CLI 및 Dockerfile
- ZIP 안전성·구조·참조관계 검사 후 DB 배치 삽입, feed 비활성 상태로 적재하고 완료 시점에만 활성화
- Worker progress phase/percent/processed rows 및 heartbeat 표시
- 장시간 처리에서 heartbeat가 작업 lease를 갱신해 정상 작업의 중복 회수 방지
- health/readiness에 Worker 연결상태 포함
- 10,000개 COS multipart 한도 검사

## 운영 구조
- EdgeOne Cloud Function은 multipart 업로드 조정과 signed URL만 담당
- 실제 압축 해제·대용량 검증·배치 import는 별도 Worker 프로세스가 수행
- Worker는 PostgreSQL과 COS에 접근할 수 있도록 서버 전용 환경변수 필요
- COS bucket CORS는 정확한 `APP_ORIGIN`에 대해 PUT/OPTIONS를 허용해야 함

## 주의
- 실제 Tencent COS, PostgreSQL, EdgeOne에 연결해 테스트하지 않음
- Worker를 실행할 별도 compute 환경이 없으면 파일은 `queued`에 머뭄
- Worker 재시도 시 동일 feed_id의 비활성 부분 데이터를 지우고 처음부터 다시 적재 (체크포인트 재개 미지원)
- GTFS Schedule 검증은 구조·참조 무결성에 한정하며 실제 운행 정확성/전국 커버리지 보증이 아님
- `frequencies.txt`/GTFS Flex는 현재 미지원, `transfers.txt`/`pathways.txt`는 완전 적용하지 않음
