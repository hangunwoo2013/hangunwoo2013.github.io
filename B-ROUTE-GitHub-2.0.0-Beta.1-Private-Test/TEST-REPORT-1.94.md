# B-ROUTE 1.94 테스트 보고서

## 테스트 명령

```bash
python -m pytest -q
python scripts/run_regression.py
```

## 결과

- `python -m pytest -q`: 1개 통합 테스트 엔트리 통과
- 회귀 러너: 9개 격리 시나리오 전체 통과
- Python `compileall`: 통과
- Node.js 인라인 JavaScript `--check`: 통과
- `sw.js` 구문 검사: 통과
- `index.html`: 95개 고유 ID, 중복 없음
- `admin.html`: 63개 고유 ID, 중복 없음
- GitHub Actions YAML 및 내장 Bash 구문: 3개 Workflow 통과
- 버전 메타데이터/실제 `.env` 미포함 검사: 통과

## 9개 격리 시나리오

1. TAGO HTTP API 요청 계약 및 오류 처리
2. COS 대용량 GTFS 스테이징/검증/배치 가져오기
3. OIDC 서명·발급자·Audience·만료·Nonce 검증 및 fragment 복귀 URL
4. Resend 초대 메일, 메일함 링크 증명, 계정 선택, 재전송·실패·한도·DB 마이그레이션
5. 프로젝트 경로 버전 스키마 마이그레이션
6. Google·Naver·Microsoft 프로젝트 권한/공동편집/읽기 공유
7. GTFS 철도 환승·버스/철도 연결 및 교통수단 필터
8. 단일 출처 프런트엔드/API 실행 및 보호된 경로
9. 교통 공급자 API 계약/정규화/권한/비밀키 비노출

## 초대 메일 세부 검증

- `RESEND_API_KEY`가 서버 요청 Authorization 헤더에만 포함되는지
- `Idempotency-Key`가 요청마다 고유한지
- HTML과 텍스트 메일에 `프로젝트 참가하기`가 포함되는지
- API 응답에 `invite_url` 또는 원문 토큰이 없는지
- 토큰이 `#invite=` fragment에 들어가고 초기 페이지 요청/Referer에 포함되지 않는지
- 신규 미리보기·수락 API가 토큰을 POST JSON 본문으로 받고 URL 경로에 포함하지 않는지
- 신규 Preview POST를 반복해도 초대가 수락되지 않는지
- 구형 GET Preview 호환 경로도 상태를 변경하지 않는지
- 초대 메일과 다른 계정 이메일이면 409 후 명시적 확인을 요구하는지
- 확인 후 현재 로그인 계정 subject에 권한을 부여하는지
- 수락한 토큰 replay가 410인지
- 재전송이 이전 링크를 무효화하는지
- 이전 발송의 늦은 완료가 새 발송 상태를 덮어쓰지 않는지
- Resend 실패 메시지 본문/키가 외부로 누출되지 않는지
- 일일 제한과 미설정 fail-closed 동작

## 한계

- Resend는 MockTransport로 대체했으며 실제 메일을 보내지 않았다.
- 실제 메일 배달/반송은 확인하지 않았다.
- 실 OAuth 공급자, PostgreSQL, COS, Cloud Run/GitHub 배포 테스트를 하지 않았다.
- Docker 실행 환경 부재로 이미지 빌드는 이 환경에서 실행하지 않았다.
- EdgeOne/GitHub/Cloud Run 배포는 사용자 요청에 따라 중단했다.
