# B-ROUTE EdgeOne Local-first 1.1 변경사항

- 기준 원본: 사용자가 제공한 `B-ROUTE-EdgeOne-Package.zip`
- 지도 레이어(OSM/Esri)와 Leaflet 구성은 수정하지 않음
- Supabase SDK, config.js, 로그인 UI 및 인증 코드를 제거
- 경로 저장을 localStorage 전용으로 통일
- 저장 경로 JSON 백업/복원 추가
- 피드백 저장을 기기 내부 전용으로 통일
- GTFS 안내 링크를 실제 배포 README 파일명으로 수정
- 경로 계산 안내 문구를 등록된 GTFS 지역 기준으로 정확화
- 배포 ZIP에서 Python `__pycache__` 제거

## 의도적으로 미완료인 사항
- GTFS 자료 자체는 포함하지 않음
- EdgeOne `/tmp` SQLite의 영구성 문제는 해결하지 않음
- 따라서 전국 실경로 서비스가 완성되었다고 볼 수 없음

- 기존 Supabase 계정 저장 경로는 자동 이전되지 않음을 문서에 명시
