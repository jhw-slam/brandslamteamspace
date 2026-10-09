-- 인보이스 발행일: 입금내역(은행)과 인보이스를 맞출 때 입금일과 비교하는 기준 날짜.
-- 영향: sales_campaigns에 칸 1개 추가(기존 데이터 변화 없음). 비어 있으면 '첨부일'로 대신 비교한다.
ALTER TABLE public.sales_campaigns
  ADD COLUMN IF NOT EXISTS invoice_issue_date date;
