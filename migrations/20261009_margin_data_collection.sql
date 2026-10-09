-- 마진율·현금기준 이익 관리를 위한 데이터 수집 (10/9)
-- 영향: ① sales_campaigns에 칸 2개 추가(기존 데이터 변화 없음)  ② 새 테이블 campaign_deposit_links 1개 추가.
-- 모두 IF NOT EXISTS라 여러 번 실행해도 안전합니다.

-- ① 인보이스 발행일 + 청구 금액의 부가세 구분(마진은 부가세 뺀 금액으로 계산해야 함)
ALTER TABLE public.sales_campaigns
  ADD COLUMN IF NOT EXISTS invoice_issue_date date,
  ADD COLUMN IF NOT EXISTS invoice_vat_type   text;   -- '별도 …' | '포함 …' | '해당없음 …'

-- ② 입금 확인: 은행 입금 1건 ↔ 캠페인 N개 (김선재가 '맞아요'를 눌러 확정한 것만 저장)
--    한 입금이 여러 캠페인 몫이면 여러 줄(ratio·allocated_amount로 나눔). 현금기준 캠페인 매출의 근거가 된다.
CREATE TABLE IF NOT EXISTS public.campaign_deposit_links (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bank_transaction_id uuid NOT NULL REFERENCES public.bank_transactions(id) ON DELETE CASCADE,
  campaign_id         uuid NOT NULL REFERENCES public.sales_campaigns(id) ON DELETE CASCADE,
  ratio               numeric NOT NULL DEFAULT 1,
  allocated_amount    numeric NOT NULL,
  matched_by          text,
  matched_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (bank_transaction_id, campaign_id)
);
CREATE INDEX IF NOT EXISTS campaign_deposit_links_campaign_idx ON public.campaign_deposit_links (campaign_id);
ALTER TABLE public.campaign_deposit_links ENABLE ROW LEVEL SECURITY;  -- 서비스 키로만 접근
