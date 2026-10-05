# 브랜드슬램 내부 운영 플랫폼 — AI 코딩 도구 공통 작업 가이드

> Claude Code / Gemini CLI / VS Code의 AI 에이전트 등 **어떤 도구로 작업하든 이 규칙을 따릅니다.**
> 이 파일이 단일 원본(AGENTS.md)이고, CLAUDE.md·GEMINI.md는 이 파일을 불러오기만 합니다.
> 코드만 봐서는 알 수 없는 것(배경·원칙·함정)만 적었습니다. 코드는 직접 읽으세요.

## 1. 이게 뭔가
- 주식회사 브랜드슬램(인플루언서 마케팅 대행사)의 내부 업무 플랫폼. 대표: 장현우.
- OKR/KPI, 재무캘린더(은행거래·정산), 계약, 인플루언서 송금, 직원 업무보고를 한 곳에서 처리.
- 직원마다 역할이 달라 화면도 달라짐: 김선재(세일즈/B2B) · 곽재선(인플루언서) · 구정회(개발) · 이단우(중국 운영).
- **테스트 전용 계정 "가상인턴"** 이 있음(STAFF_NAMES + okr_org). 기능 테스트는 항상 이 이름으로 할 것.

## 2. 구조 (레포 2개 + Railway 서비스 여러 개)
| 레포 | 내용 | 배포 |
|---|---|---|
| `jhw-slam/brandslamContract` | 관리자용 멀티페이지 앱(`pages/`: 재무캘린더, OKR관리 등) + `scripts/`(크론 배치) | Railway 서비스 `brandslamContract` + 크론 서비스 `checkin&out_alram` |
| `jhw-slam/brandslamteamspace` | 직원용 독립 앱 `app.py`(약 2,000줄, 상단 가로 탭 구조) | Railway 서비스 `brandslamteamspace` (www.brandslam.cloud) |

- 스택: Streamlit + Supabase(project_id `grlayjybcxrcaufnwysb`) + Railway + Resend(메일) + 뱅크다(은행 API) + Claude API.
- `brandslamContract`는 GitHub Actions `sync.yml`로 코드가 Supabase `repo_files` 테이블에 자동 동기화됨. **repo_files를 직접 수정하지 말 것**(GitHub와 어긋남). 수정은 항상 git으로.
- 크론은 `scripts/scheduler.py` 하나가 10분마다 깨어나 KST 시각을 보고 작업을 분기(완성도체크, 아침/오후 메일, KPI 정렬).

## 3. 작업 규칙 (중요)
1. **`main` 브랜치에 직접 push 금지.** `staging` 브랜치에서 작업 → Railway staging에서 확인 → PR로 main 머지.
2. 커밋 전 반드시 `python -m compileall -q .` 통과 확인.
3. 비밀값(Supabase service key, API 키, 비밀번호)을 코드/커밋에 절대 넣지 말 것. 전부 환경변수.
4. 운영 DB를 직접 건드리는 SQL(UPDATE/DELETE)은 실행 전에 대상 건수를 SELECT로 먼저 확인하고 사용자에게 알릴 것.
5. 큰 변경은 먼저 계획을 설명하고 동의를 받은 뒤 구현.
6. 새 기능은 "가상인턴" 계정으로 끝까지 눌러보고(제출→관리자 화면에서 보이는지) 완료로 칠 것.
7. `app.py`(약 2,000줄) 같은 큰 파일은 **통째로 다시 쓰지 말고 필요한 부분만 수정**. 수정 후 `git diff`로 의도치 않게 지워지거나 바뀐 부분이 없는지 확인.
8. 사용자(장현우 대표)는 비개발자. **한국어로, 쉬운 말로** 무엇을 왜 바꿨는지 설명하고, 테스트 방법(어느 화면에서 무엇을 눌러보면 되는지)까지 알려줄 것.

## 4. 환경변수 (이름만. 값은 Railway Variables)
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `APP_PASSWORD`, `FINANCE_PASSWORD`,
`RESEND_API_KEY`, `RESEND_FROM`, `ADMIN_BCC_EMAIL`, `DAILY_REPORT_APP_URL`,
`BANKDA_API_KEY`, `DRIVE_FOLDER_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_OAUTH_CLIENT_ID/SECRET`.
- 서비스마다 변수가 따로임. 새 서비스(특히 크론/staging)에는 필요한 변수를 직접 복사해야 함.

## 5. 설계 원칙 (대표가 정한 것)
- 직원 **본인 기록**에 대한 AI 제안은 본인 확인으로 즉시 반영. **신규 계정 생성** 같은 회사 전체 영향 건만 대표 승인.
- **결제 정보는 절대 추측/자동완성하지 않는다.** 통화, 페이팔 결제 이메일 vs 안내메일 주소는 별개 필드. 불완전하면 등록 자체를 막는다(해외송금에서 하나라도 안 맞으면 신청이 안 되는 것처럼).
- 급여·인건비 데이터는 AI 스캔/리포트에서 완전 제외. 다른 직원의 대화·회의 내용 노출 금지(세일즈 회의 알림은 "등록된 업체명이 언급된 회의"만).
- 사용자는 "감시당한다"가 아니라 "도움받는다"고 느껴야 함. 문구는 간결·구체·담백하게(오글거리는 표현 금지).
- 직원에게 에러가 나면 **원인을 숨기지 말고** 무엇이 문제인지/어떻게 해결하는지 화면에 보여줄 것.

## 6. 이미 겪은 함정 (반복 금지)
- **엑셀 한글 깨짐**: CSV 다운로드는 반드시 `.encode("utf-8-sig")`(BOM). 안 하면 한국 윈도우 엑셀에서 깨짐.
- **날짜 파싱**: `26.09.28`(YY.MM.DD)을 `pd.to_datetime`에 맡기면 엉뚱한 날짜가 됨. 명시적 포맷(`%y-%m-%d`)을 먼저 시도.
- **금액 파싱**: `₩70,000`, `350,000.00₩` 형태가 섞여 들어옴. `₩`/`원`/`,` 제거 후 파싱.
- **시트 열 위치 고정 금지**: 구글폼 기반 시트는 헤더가 질문 문장이고 시트마다 열 의미가 다름. 위치 대신 AI 의미추출 + 사용자 확인 단계.
- **Railway 크론은 UTC**: 한국 9–18시 평일 = `*/10 0-9 * * 1-5`. 코드 안에서는 KST로 변환해서 판단.
- **Resend Suppressed**: 한 번 반송된 주소는 조용히 발송이 막힘. 이상하면 resend.com > Suppressions 확인.
- **스크린샷 업로드 400 에러**: 큰 이미지는 API가 거부. Pillow로 1568px 이하로 줄여서 전송(`Pillow`가 requirements에 있어야 함).
- **st.tabs 안의 위젯 key**: 같은 key를 두 번 쓰면 터짐. 새 위젯엔 고유 key.
- **Python 3.13 / f-string**: 중첩 따옴표 f-string은 피하고 변수로 분리.

## 7. DB 주요 테이블 (public)
- 직원/업무: `okr_org`, `okr_items`(is_recurring=KPI, due_date), `daily_activity_log`, `assigned_tasks`, `data_completeness_prompts`, `ai_drafted_updates`, `kpi_alignment_suggestions`, `kpi_data_sources`, `company_vision`
- 역할별 도구: `sales_accounts/issues/campaigns/campaign_tasks/meeting_alerts`, `dev_tasks`, `influencer_pool`, `casting_funnel`
- 재무: `bank_transactions`(dedup_hash 유니크), `bankda_*`, `cash_events`, `fin_*`, `tax_invoices`, `fin_cash_forecasts`(예정입출금 신고), `payment_requests`(인플루언서 송금: 통화·페이팔/안내메일 분리·dedup_key·batch_id·report_complete)
- 메일/드라이브: `email_log`, `drive_file_index`, `drive_scan_log`, `meetings`
- ⚠️ `drive_*`, `campaigns`, `brands`, `sales_brands`, `sales_revenue_monthly`, `assistant_notifications` 등은 다른 세션에서 만들어진 것으로 보임 — 사용 전 스키마와 쓰임 확인.

## 8. 알려진 미해결 / 확인 필요
- 크론의 Google Drive 서비스계정 스캔(`kpi_context_sync.py`)이 결과 0건. (대화형 Claude의 Drive 커넥터는 정상 → 서로 다른 경로.) 근본 원인 미확정.
- 원칙상 "재무 완료 상태는 은행거래 매칭으로만" 인데, 현재 `payment_requests`엔 수동 "송금완료 처리" 버튼이 있음. 둘의 정합성 정리 필요.
- `support_chat_staff` 테이블 RLS 비활성(보안): `ALTER TABLE public.support_chat_staff ENABLE ROW LEVEL SECURITY;` 및 정책 설계 필요.
- 지출기안서 링크는 현재 선택사항. 추후 승인 플로우에서 필수화 예정.
- 직원이 실제로 쓰는 시트/양식이 제각각이라 송금정보 읽기 정확도는 계속 개선 대상.
