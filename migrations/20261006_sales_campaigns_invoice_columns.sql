-- 세일즈 캠페인: 월별 인보이스(브랜드사 승인용) 첨부 칸 추가
-- 변경 내용: public.sales_campaigns 에 컬럼 6개를 "추가"만 합니다. 기존 데이터·컬럼은 건드리지 않습니다.
--   invoice_url          : 최종 인보이스 링크 (Supabase 업로드 주소 또는 구글드라이브 링크)
--   invoice_name         : 인보이스 파일 이름
--   invoice_amount       : 인보이스 청구 금액(원) — 다음달 예측·마진율 계산에 쓰임
--   invoice_attached_by  : 인보이스를 첨부한 사람 (최종 인보이스는 담당자 김선재)
--   invoice_attached_at  : 첨부한 시각
--   brand_approved_at    : 브랜드사 승인일 (비어 있으면 아직 승인 전)
-- 안전성: IF NOT EXISTS 라서 여러 번 실행해도 안전합니다. 기존 캠페인은 모두 NULL(미첨부)로 남습니다.
-- 되돌리기: ALTER TABLE public.sales_campaigns
--             DROP COLUMN invoice_url, DROP COLUMN invoice_name, DROP COLUMN invoice_amount,
--             DROP COLUMN invoice_attached_by, DROP COLUMN invoice_attached_at, DROP COLUMN brand_approved_at;

ALTER TABLE public.sales_campaigns
  ADD COLUMN IF NOT EXISTS invoice_url         text,
  ADD COLUMN IF NOT EXISTS invoice_name        text,
  ADD COLUMN IF NOT EXISTS invoice_amount      numeric,
  ADD COLUMN IF NOT EXISTS invoice_attached_by text,
  ADD COLUMN IF NOT EXISTS invoice_attached_at timestamptz,
  ADD COLUMN IF NOT EXISTS brand_approved_at   date;
