# B-ROUTE 1.5 — 구현 상태

## 이 버전의 목적
정식 배포 전 비공개 베타를 위한 운영 기반을 구성합니다. 데모나 MVP가 아니며, 아직 베타를 시작해도 되는 최종 릴리스는 아닙니다.

## 구현된 기반
- PostgreSQL 연결 어댑터 및 SQLite 로컬 개발 모드
- 운영 APP_ENV에서 DATABASE_URL 미설정 시 로그인/영구 쓰기 기능을 제한하는 fail-closed 처리
- DB 자동 초기화/기존 feedback 컬럼 마이그레이션
- Google 로그인 시 users 레코드 생성 및 갱신
- 사용자별 COS 클라우드 파일 API: 업로드, 목록, 다운로드 URL, 삭제
- 계정당 1,000MB 기본 용량, 총괄자가 50~1,000MB 범위 내 일반 설정으로 조정
- 단일 클라우드 파일 1~5MB 범위 내 제한
- 사용자 문의 서버 접수, 본인 문의 이력 조회, 총괄자 답변/상태 갱신
- 관리자 일반 설정 업데이트 + 사유 + audit log + rollback
- admin.html 운영 설정, 피드백 큐, 변경 로그/롤백 화면
- 메인 앱에서 `.broute`를 COS 보관함에 저장하고 내려받는 UI (실제 계정/DB/COS 연결 필요)
- IndexedDB 기기 저장 및 기존 localStorage 경로 자동 병합 이전, 브라우저 영구 저장 권한 요청 시도
- COS 업로드 전 `.broute` JSON과 좌표 구조 검증, DB 메타데이터 기록 실패 시 COS 객체 정리 시도
- GTFS 업로드 5MB 제한으로 EdgeOne 요청 한도 내에서 안전 처리
- 비공개 베타 승인 게이트 기본 false

## 내부 검증
- Python 3.13에서 py_compile 통과
- 메인 HTML inline JavaScript `node --check` 통과
- 관리자 페이지 inline JavaScript `node --check` 통과
- HTML ID 중복 없음, JS에서 참조하는 ID 누락 없음
- FastAPI TestClient: `/health` 1.5.0 응답
- 비로그인 관리자 상태 접근 401
- 모의 관리자 세션으로 설정 조회/수정/감사로그 조회/설정 롤백 성공
- 모의 이용자 세션으로 피드백 제출, 본인 피드백 조회, 관리자 답변/상태 변경 성공
- COS 자격 증명 미설정 시 클라우드 업로드 503으로 비활성 처리
- FakeCOS 모의 객체로 업로드/목록/다운로드 링크/삭제 및 다른 계정의 접근 차단 테스트 통과
- 잘못된 `.broute` 좌표 구조 서버 검증 테스트 통과
- APP_ENV=production + DATABASE_URL 미설정 시 피드백 영구 저장 503으로 차단

## 아직 실기 검증하지 못한 항목
- PostgreSQL 실제 연결 및 스키마 마이그레이션
- COS 버킷 실제 업로드/다운로드/삭제 및 IAM 권한 (가짜 COS 모의 객체로 경로/소유권 테스트만 통과)
- Google OAuth 실계정 로그인
- EdgeOne 배포 및 EdgeOne Python 3.10 런타임 의존성 설치
- 실제 브라우저에서 IndexedDB 저장·새로고침·localStorage 병합 이전 확인 (문법 검사 외 실브라우저 테스트는 미실행)
- 모바일/PC 실제 브라우저 UI, GPS, 지도 타일 로딩
- 대용량 GTFS 직접 업로드 및 전국 데이터셋 importer

## 비공개 베타 시작 불가 사유
- API 자격 증명 미입력
- 운영 PostgreSQL / COS 실연결 미검증
- 실제 지역별 GTFS·철도 시간표가 포함되지 않음
- 전국 커버리지 및 경로 정확도 검증 미완료
- BETA_RELEASE_APPROVED=false

## 아직 완성되지 않은 저장 관련 기능
- 파일별 동기화 상태(미동기화/수동/자동), 충돌 감지 및 해결
- 클라우드 파일 버전 이력 및 복구
- 클라우드 공유 링크 생성/만료/취소를 메인 UI에 연결
- 장기 자동 백업 및 orphan COS object 정리 작업
- 현재 `.broute` 스키마는 버전 1만 지원하며, 향후 스키마 마이그레이션 필요
- IndexedDB를 사용할 수 없는 환경에서는 localStorage 예비 저장소를 사용하므로 저장 용량이 제한될 수 있음

## 다음 개발 단계
1. COS staging upload + 대용량 GTFS 배치 import
2. GTFS/KTDB/TAGO 데이터 변환·출처·날짜·라이선스 기록 파이프라인
3. 실제 전국 범위 검증 및 갱신 버전/롤백 시스템
4. 실시간 도착정보와 정적 시간표 분리 통합
5. 운영 통계·백업·장애 알림 및 베타 수락 테스트
