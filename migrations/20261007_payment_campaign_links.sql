-- 인플루언서 송금(콘텐츠 비용) ↔ 캠페인 연결 (마진율 자동 계산의 기초)
-- AGENTS.md 규칙 9번: SQL 파일 → 설명 → DB 적용 → 코드 배포
--
-- 왜 필요한가:
--   매출  = 김선재가 캠페인별로 올리는 인보이스 금액 (sales_campaigns.invoice_amount)
--   비용  = 곽재선이 올리는 콘텐츠별 인플루언서 송금 (payment_requests.amount)
--   마진  = 매출 - 비용  → 비용이 '어느 캠페인 몫인지' 알아야 계산됩니다.
--   한 콘텐츠에 여러 캠페인(브랜드)이 노출될 수 있으므로 1:N(다대다) 연결 테이블을 둡니다.
--
-- 변경 내용: 새 테이블 1개(payment_request_campaigns)를 "추가"만 합니다. 기존 테이블·데이터는 건드리지 않습니다.
--   payment_request_id : 어떤 송금(콘텐츠)인지
--   campaign_id        : 어떤 캠페인에 노출됐는지 (캠페인이 연결돼 있으면 캠페인 삭제를 막음)
--   ratio              : 비용을 나누는 비율 (기본은 균등: 캠페인 2개면 각 0.5, 모든 비율의 합 = 1)
--   allocated_amount   : 이 캠페인에 배분된 비용 (송금 통화 기준, 반올림 차이는 마지막 캠페인에 합산)
--   currency           : 송금 통화 (인보이스 통화와 다르면 마진 계산 때 환산 필요 — 환율은 추측하지 않음)
--   matched_by         : 연결한 사람
-- 같은 송금에 같은 캠페인을 두 번 연결할 수 없습니다(UNIQUE).
--
-- 보안: RLS 켬(정책 없음). 이 앱은 서비스 키로만 접근하므로 동작에는 영향 없음.
-- 되돌리기: DROP TABLE public.payment_request_campaigns;

CREATE TABLE IF NOT EXISTS public.payment_request_campaigns (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at         timestamptz NOT NULL DEFAULT now(),
  payment_request_id uuid NOT NULL REFERENCES public.payment_requests(id) ON DELETE CASCADE,
  campaign_id        uuid NOT NULL REFERENCES public.sales_campaigns(id) ON DELETE RESTRICT,
  ratio              numeric NOT NULL DEFAULT 1 CHECK (ratio > 0 AND ratio <= 1),
  allocated_amount   numeric,
  currency           text,
  matched_by         text,
  UNIQUE (payment_request_id, campaign_id)
);
CREATE INDEX IF NOT EXISTS payment_request_campaigns_campaign_idx ON public.payment_request_campaigns (campaign_id);
CREATE INDEX IF NOT EXISTS payment_request_campaigns_payment_idx  ON public.payment_request_campaigns (payment_request_id);

ALTER TABLE public.payment_request_campaigns ENABLE ROW LEVEL SECURITY;
