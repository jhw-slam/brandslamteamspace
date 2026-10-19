-- 채팅처럼 쓰는 계획 (10/20): 직원이 "OO 거래처와 이번 캠페인에서 행사 하기로 했다 / 통화하겠다"를 두서없이 쓰면
-- AI(또는 기본 분석)가 거래처·캠페인·종류·날짜로 정리하고, 핵심 지표에 연결한다. 같은 계획을 말만 바꿔 또 쓰면 1개로 묶는다(중복 표시).
-- 영향: 새 테이블 1개 추가(기존 데이터 변화 없음). 되돌리기: DROP TABLE public.plan_items;
CREATE TABLE IF NOT EXISTS public.plan_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  person        text NOT NULL,
  title         text NOT NULL,                 -- 한 줄로 정리한 계획
  counterparty  text,                          -- 거래처/상대(브랜드 등)
  campaign      text,                          -- 어떤 캠페인에서
  action_type   text,                          -- 통화·미팅·행사·제안·계약·가이드·모집·기타
  metric_key    text,                          -- 연결된 핵심 지표(KPI_DEFS 키). 없으면 custom_label로 '내가 쓴 지표'
  custom_label  text,                          -- 써내려가는 지표의 이름(예: 거래처 통화)
  qty           numeric NOT NULL DEFAULT 1,
  due_date      date,
  status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','dropped')),
  repeat_count  integer NOT NULL DEFAULT 1,    -- 같은 계획을 몇 번 적었는지(미뤄진 횟수)
  raw_texts     jsonb NOT NULL DEFAULT '[]'::jsonb,  -- 직원이 실제로 쓴 문장들(말만 바꾼 것도 모두)
  source        text NOT NULL DEFAULT 'chat',
  created_at    timestamptz NOT NULL DEFAULT now(),
  done_at       timestamptz
);
CREATE INDEX IF NOT EXISTS plan_items_person_idx ON public.plan_items (person, status, due_date);
ALTER TABLE public.plan_items ENABLE ROW LEVEL SECURITY;  -- 서비스 키로만 접근
