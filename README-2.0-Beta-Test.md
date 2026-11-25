# B-ROUTE 2.0 Beta Test (2.0.0-beta.1)

## 이 패키지의 상태

이 ZIP은 1.95.1을 기반으로 만든 **비공개 베타 후보 빌드**다. 로컬 코드·회귀검사는 통과했지만, 실서비스 구성과 전국 시간표 데이터 커버리지는 아직 검증되지 않았다. 따라서 이 파일은 베타 환경을 준비하는 기준 패키지이며, 즉시 외부 테스터에게 배포해도 되는 완료 제품이라는 뜻은 아니다.

`BETA_RELEASE_APPROVED`는 `false`로 유지한다. Cloud Run 배포 workflow도 다음을 모두 요구한다.

- `GCP_DEPLOY_ENABLED=true`
- beta branch에 한해 `BETA_DEPLOY_APPROVED=true`
- beta 서비스는 기본적으로 Cloud Run 익명 접근을 차단한다. 승인된 테스터의 Google 계정에 `roles/run.invoker`를 부여해야 접근할 수 있다.
- 익명 인터넷 접근을 명시적으로 허용하기로 결정한 경우에만 `BETA_PUBLIC_ACCESS_APPROVED=true`를 설정한다. 이 값은 닫힌 베타와 양립하지 않으므로 신중하게 결정한다.

## 현재 작동 및 제한

- 지도, 장소 검색, GPS, 여러 경유지 및 경유지 체류시간, 저장/가져오기, 프로젝트 협업, 읽기 전용 공유, 사용자 피드백 UI와 API가 패키지에 포함되어 있다. 기능별 실계정 인증/운영 DB 테스트는 별도다.
- 실제 대중교통 경로 계산은 서버에 등록하고 활성화한 GTFS 시간표 데이터 범위에 따라 제한된다. TAGO API 키가 존재한다고 자동으로 전국 버스·철도 경로 데이터가 구성되는 것은 아니다.
- 가상 시연 예제는 개발 환경의 QA 화면에서만 동작하며 실제 교통 노선·시간표·소요시간이 아니다.
- 관리판 readiness는 설정 존재 여부와 기본 데이터 상태를 확인한다. 전국 커버리지, 라이선스 적법성, 시간표 정확성, COS 실제 업로드/다운로드 성공까지 보증하지 않는다.
- 현재 GTFS worker 이미지는 빌드될 수 있지만, workflow가 별도 Cloud Run Job을 생성하거나 스케줄링하지 않는다. Worker 실행 환경/작업 트리거/DB/COS 접근 권한을 별도로 준비해야 한다.

## 외부 베타 시작 전 필수 작업

1. GitHub private 저장소에 코드를 올리고 `beta` 브랜치를 만든다. CI를 원격 실행해 pytest와 Docker 이미지 빌드가 통과하는지 확인한다.
2. 운영과 완전히 분리된 beta 서비스, PostgreSQL DB, COS bucket, Secrets를 준비한다. 운영 DB와 beta DB를 절대 공유하지 않는다.
3. Google/Naver/Microsoft OAuth의 beta callback/origin을 등록하고 실제 계정으로 로그인·로그아웃·계정 구분·권한을 검증한다.
4. Resend에서 발신 도메인을 인증하고 실제 초대 메일 수신 및 webhook 전달·반송을 테스트한다. Reply-To 기본값은 `broute.site.app@gmail.com`이고, Resend From에는 인증된 사용자 소유 도메인 주소를 써야 한다.
5. 공공데이터 API 제품별 사용 승인을 점검하고 지역별 GTFS 출처·라이선스·갱신 기준일을 등록한다. 부산 외 테스트 지역을 포함해 버스만/철도만/버스+철도 경로를 실제 운행일 기준으로 비교 검증한다.
6. GTFS Worker를 별도 Cloud Run Job/서비스로 구성해 시작·중단·중복 실행·실패 재시도·heartbeat를 테스트한다. 이 저장소의 현재 배포 workflow는 worker 이미지만 선택적으로 빌드하며 Job 자체를 배포하지 않는다.
7. 비용 한도와 알림, DB 백업/복구, 개인정보 보관/삭제 안내를 확인한다. 무료 할당량 초과 자동 결제는 켜지 않는다.
8. 닫힌 베타 접근 제어를 결정한다. 기본 workflow는 익명 접근을 차단하며, Cloud Run Invoker 권한이 있는 테스트 계정만 접속할 수 있다.
9. 모든 필수 항목과 실제 교통 경로 커버리지를 확인한 뒤에만 `BETA_RELEASE_APPROVED=true`를 설정한다. 실제 beta 배포는 별도로 `GCP_DEPLOY_ENABLED`와 `BETA_DEPLOY_APPROVED` 승인이 필요하다.

## 로컬 실행 (개발 확인 전용)

Python 3.11 환경에서 다음을 실행한다. 운영용 데이터베이스·OAuth·메일 발송이 아닌 로컬 SQLite 개발환경이다.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r cloud-functions/requirements.txt -r requirements-ci.txt
# .env.example을 .env로 복사하고 필요한 로컬 값만 설정
set PYTHONPATH=cloud-functions
uvicorn server:app --host 127.0.0.1 --port 8080
```

macOS/Linux에서는 `export PYTHONPATH=cloud-functions`를 사용한다. 로컬 실행은 다른 테스터와 공유할 수 있는 서비스 환경이 아니다.

## 회귀검사

```bash
python -m pytest -q
python scripts/run_regression.py
```

Docker가 설치된 CI에서는 app 이미지와 GTFS worker 이미지를 별도로 빌드한다. 로컬 작업환경에서 Docker가 없다면 이미지 빌드 통과로 간주하지 않는다.

## 테스트 피드백 작성

오류 신고에는 사용 기기/브라우저, 테스트 지역, 이동 방식(버스/철도/혼합), 출발·도착 시각, 재현 단계, 예상 결과와 실제 결과를 적는다. API 키, 비밀번호, 초대 토큰, 개인 인증정보는 첨부하지 않는다.
