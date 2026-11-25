# 1.95.1 변경 사항

- Cloud Run 배포에서 Resend API 키, 웹훅 Secret, 인증된 발신 주소를 선택적으로 Secret Manager에서 주입하도록 수정
- Cloud Run에 업무용 Reply-To(`broute.site.app@gmail.com`), 발신자 이름, 일일 발송 제한, 웹훅 timestamp 허용 범위를 전달
- 공개 Resend 웹훅 주소를 실제 단일 서버 경로인 `/api/webhooks/resend`로 문서화
- `email.suppressed` 상태 우선순위 추가 및 초대 이메일 상태/오류 코드에 반영
- 실제 외부 `/api` 마운트 경로와 잘못된 루트 경로(404)를 통합 테스트에 추가
- 패치 버전 메타데이터 및 PWA 캐시 이름을 1.95.1로 갱신
- 웹훅 Secret의 `whsec_` 접두사뿐 아니라 Base64 형식도 베타 준비 상태에서 검사
- 빈 Base64 웹훅 Secret도 실제 서명검증 단계에서 HTTP 503으로 거부하도록 보강
- GTFS worker 이미지 빌드는 `GTFS_WORKER_IMAGE_BUILD_ENABLED=true`일 때만 실행하도록 안전장치 추가
