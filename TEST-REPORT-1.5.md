# B-ROUTE 1.5 내부 테스트 보고서

테스트 목적: 정식 배포 직전 비공개 베타를 위한 기반 기능의 로컬/모의 테스트. 실제 외부 서비스 배포 인증은 아님.

## 통과한 테스트

- Python 백엔드 `py_compile`
- 메인 페이지 및 관리자 페이지 인라인 JavaScript `node --check`
- HTML 요소 ID 중복 없음
- FastAPI TestClient `/health` 버전 및 베타 승인 게이트 기본 false
- 비로그인 관리자 API 접근 401
- 로그인한 일반 계정의 관리자 API 접근 403
- 모의 총괄자 설정 조회/변경/감사 로그/설정 롤백
- 이용자 피드백 접수/본인 내역 조회/총괄자 답변 및 상태 변경
- 모의 COS 객체를 이용한 `.broute` 업로드/목록/다운로드 링크 생성/삭제
- 계정 A가 올린 파일을 계정 B가 다운로드·삭제하려 할 때 404로 차단
- 잘못된 `.broute` 좌표 구조 업로드 시 400 거부
- 운영 `APP_ENV=production`에서 PostgreSQL 미연결 시 영구 쓰기 작업 503 차단
- COS 모의 객체 테스트에서 업로드 성공 후 메타데이터 조회 및 소유권 경계 확인

## 테스트에 사용한 모의 구성

- 데이터베이스: 로컬 SQLite 테스트 파일
- 사용자: 테스트용 서명 세션 클레임
- COS: 메모리에서 객체를 보관하는 FakeCOS 테스트 더블
- 네트워크: 실제 Google, PostgreSQL, Tencent COS 공급자에는 연결하지 않음

## 테스트하지 않은 항목

- 실제 PostgreSQL 드라이버 설치·접속 및 운영 스키마 마이그레이션
- 실제 Tencent COS 버킷·권한·서명 URL·요금 검증
- Google 실계정 ID 토큰 검증 및 모바일 브라우저 로그인
- IndexedDB를 실제 Chromium/Android 브라우저에서 실행하는 UI 테스트 (JavaScript 문법 검사만 통과)
- EdgeOne 실제 배포, Python 3.10 환경 설치 및 Cold Start
- 전국 GTFS/철도 데이터 수집·갱신·경로 정확성
- 동시성 부하, API rate limit, 백업 복구, 취약점 점검

따라서 이 보고서의 '통과'는 로컬 모의 테스트 범위에만 해당합니다. 실제 배포나 비공개 베타 준비 완료를 의미하지 않습니다.
