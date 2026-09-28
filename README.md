# 브랜드슬램 업무보고 (직원용 독립 앱)

메인 관리자 앱(brandslamContract)과 **같은 Supabase DB**를 그대로 사용하는, 직원 전용 데일리 업무보고 페이지입니다.
사이드바 없이 이 화면 하나만 뜨는 독립 앱입니다.

## Railway 배포 시 필요한 환경변수

| 변수명 | 설명 |
|---|---|
| `SUPABASE_URL` | 메인 앱과 동일한 Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_KEY` | 메인 앱과 동일한 Supabase 서비스 롤 키 |
| `APP_PASSWORD` | (선택) 입장 비밀번호. 비워두면 비번 없이 누구나 접속 가능 |

메인 앱(brandslamContract)의 Railway 프로젝트에서 위 두 값을 그대로 복사해서 넣으면 됩니다 — **같은 DB를 봐야 하므로 값이 100% 동일해야 합니다.**

## 이 앱이 쓰는 테이블

- `influencer_placements` — 업체별 캠페인/인플루언서 배치 카드
- `daily_activity_log` — 오늘 빠른 기록
- `fin_cash_forecasts` — 예정입출금 신고

이 테이블들의 데이터는 메인 앱의 "재무캘린더"·"종합상황판"에서도 그대로 보입니다.
