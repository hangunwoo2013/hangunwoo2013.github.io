# B-ROUTE 1.92 — 비용, 주소 유지 및 업데이트/롤백 설계

## 1. GitHub를 어디에 사용하는가

GitHub는 다음 역할을 담당합니다.

- 비공개 Repository: 소스 코드와 개발 이력 보관
- GitHub Actions: 자동 회귀 테스트, 컨테이너 빌드 및 승인된 배포
- Pull Request: 1.92/1.93 개발을 검토한 뒤 beta/main에 병합

GitHub Pages를 B-ROUTE 전체 호스트로 쓰는 것은 권장하지 않습니다. GitHub Pages는 정적 사이트용이며, GitHub 정책상 온라인 사업 또는 SaaS를 제공하는 무료 웹호스팅으로 사용하는 것은 허용 대상이 아닙니다. B-ROUTE는 서버 인증, 프로젝트별 권한, API 비밀키, 개인정보 및 사용자 데이터가 있으므로 정적 페이지 서버만으로는 요구사항을 충족하지 못합니다.

권장 구조:

```text
개발자 → GitHub Repository
             │
             ├─ GitHub Actions CI
             │    └─ 구문/단위/통합/Docker 빌드 검사
             │
             └─ 승인된 branch push
                  └─ GitHub Actions Deploy
                       └─ Cloud Run (FastAPI + 정적 화면, 같은 Origin)
                            ├─ PostgreSQL
                            ├─ COS Object Storage
                            └─ 별도 GTFS Worker Job
```

GitHub Pages는 문서·소개 페이지 같은 완전 공개 정적 콘텐츠가 필요할 때만 별도 검토합니다. 핵심 앱은 FastAPI 서버와 같은 Origin에서 운영합니다.

## 2. 같은 주소로 업데이트할 수 있는가?

가능합니다. 핵심은 주소를 새 빌드 파일에 붙이는 것이 아니라 **오래 유지할 서비스 이름**에 연결하는 것입니다.

현재 Workflow가 사용하는 안정적인 서비스:

- Beta: `broute-beta`
- Production: `broute-prod`

동일 서비스를 다시 배포하면 Cloud Run은 새 불변 Revision을 만들고 서비스 URL은 그대로 유지합니다. 배포가 완료되면 새 Revision으로 트래픽을 전환합니다. 이전 Revision은 삭제하지 않는 한 남아 있어, 필요하면 트래픽을 이전 Revision으로 돌릴 수 있습니다.

예시:

```text
https://broute-beta-....run.app
  ├─ Revision broute-beta-00001 (이전 버전)
  ├─ Revision broute-beta-00002 (새 버전)
  └─ 서비스 URL은 동일, 트래픽만 새 Revision으로 변경
```

공식 문서:
- Cloud Run Revision은 배포/설정 변경 때 생성되며 Revision은 immutable입니다.
- 트래픽 롤백 예시: `gcloud run services update-traffic SERVICE --to-revisions REVISION=100`.

GitHub Actions에서 `rollback-cloud-run.yml`을 수동 실행하도록 패키지에 준비했습니다.

## 3. 기존 EdgeOne 주소는 유지할 수 있는가?

`*.edgeone.dev`는 EdgeOne가 제공하는 플랫폼 도메인이므로 사용자가 소유한 도메인이 아닙니다. GitHub나 Cloud Run으로 그 도메인의 소유권을 옮길 수 없습니다. 따라서 이 주소를 직접 유지하는 것은 불가능하다고 보는 것이 맞습니다.

주소 변경을 최소화하려면:

1. 사용자가 직접 구매·소유한 도메인을 준비합니다.
2. Cloud Run에 새 서비스 URL을 먼저 준비합니다.
3. 도메인/DNS 또는 HTTPS 로드밸런서 설정을 한 번 전환합니다.
4. 이후 같은 도메인을 계속 사용하고 GitHub Actions가 동일 Cloud Run 서비스를 업데이트하게 합니다.

사용자 소유 도메인이 아직 없다면 Cloud Run의 서비스 URL(`run.app`)을 베타 URL로 사용할 수 있습니다. 같은 서비스를 업데이트할 때 URL은 유지됩니다. 나중에 도메인을 도입하면 한 번 더 주소 전환이 필요합니다.

도메인 연결 방식은 서비스의 리전/요구사항/가격을 확인한 뒤 확정합니다. Cloud Run Domain Mapping의 지원 상태를 생산 환경에 바로 전제하지 말고, 필요한 경우 Google Cloud Load Balancer 또는 적절한 프런트 도어를 별도 구성합니다.

## 4. 비용 목표와 한계

월 0원은 목표이지 보장된 결과가 아닙니다. 각 서비스의 무료 한도는 다르고 변경될 수 있습니다.

2026년 11월 확인한 공식 안내 기준 예시:

| 서비스 | 무료 제공 예시 | 주의 사항 |
|---|---|---|
| GitHub Actions | Public repo의 standard runner는 무료. Private Free 계정은 월 포함 실행 시간 제공 | Private repo는 포함량 초과 시 과금 가능. 현재 GitHub Free 표에는 2,000분/월 표시 |
| Cloud Run | Request-based billing 무료 제공량: 월 2백만 요청, 180,000 vCPU-second, 360,000 GiB-second | 무료량은 Billing Account 단위로 합산. 서울 리전·다른 리소스·초과 사용은 비용이 날 수 있음 |
| Neon PostgreSQL Free | 프로젝트당 100 CU-hour/월, 1GB 저장, 5GB public network transfer | 무료 한도 소진 시 compute가 다음 기간까지 suspend될 수 있음. 정식 서비스 SLA/성능 보장은 아님 |
| Tencent COS 새 사용자 혜택 | Seoul을 포함한 지정 리전에서 Standard 저장 50GB, 180일 혜택 자료 | 요청·인터넷 트래픽·다른 스토리지 클래스 등은 포함되지 않으며 180일 후 종료 |

Cloud Run 무료 제공량은 다른 Cloud Run 리소스 및 같은 Billing Account 사용량과 합산될 수 있습니다. Cloud Run을 사용하려면 Billing Account 설정이 필요합니다. 예산 알림(Budget Alert)은 지출을 알려주는 기능이지 모든 초과 사용을 자동 차단하는 하드캡이 아닙니다.

### B-ROUTE에서 적용할 비용 안전 원칙

- Cloud Run min instances 0, max instances 1로 시작
- 요청 시간·동시성·메모리 제한
- GitHub Actions 배포 flag 기본 false
- COS 파일 크기/계정별 한도 및 공유 링크 view cap 유지
- DB/worker/API 호출량을 통계로 수집
- 무료 저장소가 suspend/쿼터 초과하면 새 업로드/갱신 중지, 유료 플랜 자동 전환 금지
- 결제 한도는 결제수단/청구 계정 설정을 별도로 점검
- Worker는 상시 켜 두지 않고 필요한 때 실행하는 Job 방식으로 검토

현재 프로젝트의 기본 클라우드 파일 한도는 계정당 1,000MB, 단일 `.broute` 파일 5MB입니다. 데이터베이스 1GB 무료량과 사용자 파일 1GB 한도는 서로 다른 용량입니다. 총 이용자 수만큼 1GB가 무제한 생성되는 것은 아니며, 실제 COS 전체 용량/요청/전송 한도와 연결해 제한해야 합니다.

## 5. DB / Object Storage 선택

코드는 PostgreSQL 호환 `DATABASE_URL`과 Tencent COS 환경변수를 받도록 되어 있습니다. Neon Free는 현재 PostgreSQL 호환 무료 옵션 후보로 쓸 수 있지만 사용량 한도에 도달하면 서비스가 중단될 수 있습니다. 정식 2.0의 안정성/백업/RPO/RTO를 확보하려면 유료 DB나 다른 보장된 운영 저장소가 필요할 수 있습니다.

Tencent COS 무료 혜택은 새 사용자 180일 Standard storage 제공 예시일 뿐, 장기 무과금 약속이 아닙니다. 실제 선택은 배포 전에 트래픽·요청 수·지역·저장량을 계산해 결정합니다.

## 6. 운영 배포 시 주의

- DB 스키마를 변경한 뒤 이전 Revision으로 코드를 롤백해도 DB migration이 자동 역행하지 않습니다.
- 하위 호환 가능한 expand → migrate → contract 방식으로 DB 변경을 진행합니다.
- 새 Revision 배포 전 `/api/health` readiness를 확인합니다.
- 실제 API/DB/COS/Worker를 검증하기 전 `BETA_RELEASE_APPROVED=true`를 설정하지 않습니다.

## Official sources

- GitHub Pages policy: https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- Cloud Run pricing: https://cloud.google.com/run/pricing
- Cloud Run rollbacks: https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration
- Cloud Run service URL: https://docs.cloud.google.com/run/docs/triggering/https-request
- Neon Free limits: https://neon.com/docs/introduction/plans
- GitHub Actions billing: https://docs.github.com/en/actions/concepts/billing-and-usage
- Tencent COS free tier: https://staticintl.cloudcachetci.com/doc/pdf/product/pdf/tencent-cloud_436_6229_en.pdf
