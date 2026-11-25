# B-ROUTE Local 1.91 변경사항

- TAGO TrainInfo 오퍼레이션 대소문자 공식 표기 수정
- TAGO 정류소별 경유노선 API 서비스 루트와 `nodeid` 파라미터 수정
- 정류소 경유노선 응답 정규화·페이지네이션·캐시 추가
- 관리자 화면에서 실제 API 작업 7종을 개별 검사하도록 확장
- TAGO 주변 정류소 500m 제공 범위와 로컬 필터 경계 일치
- data.go.kr `resultCode=03`를 정상 빈 결과로 처리
- API 권한·호출량·IP 관련 오류 매핑 정리
- 테스트 추가: HTTP URL/파라미터 계약, 권한, 정규화 샘플, 캐시 및 오류처리
- 버전 표기·문서·Service Worker 캐시를 1.91로 갱신
- EdgeOne 배포 테스트는 수행하지 않음
