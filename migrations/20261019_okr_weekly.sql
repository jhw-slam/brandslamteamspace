-- OKR 주간 추적 (10/19): 사람마다 핵심 KPI 1개를 정하고, 매주 '계획/실제'를 남겨 우상향 그래프로 본다.
-- 영향: ① okr_items에 칸 1개 추가(기존 데이터 변화 없음)  ② 새 테이블 okr_weekly_log 1개 추가.
-- 모두 IF NOT EXISTS라 여러 번 실행해도 안전합니다.

-- ① 핵심 KPI 표시(사람당 1개만): 매일 바뀌는 지표가 아니라 중장기 목표 중 대표님이 매주 확인할 1개
ALTER TABLE public.okr_items ADD COLUMN IF NOT EXISTS is_headline boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS okr_items_one_headline_per_person ON public.okr_items (person) WHERE is_headline;

-- ② 주간 기록: 한 항목 × 한 주(월요일 시작)에 한 줄. plan=그 주에 하겠다고 한 개수, actual=실제 한 개수(그 주 분량, 누적 아님)
CREATE TABLE IF NOT EXISTS public.okr_weekly_log (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id     uuid NOT NULL REFERENCES public.okr_items(id) ON DELETE CASCADE,
  person      text NOT NULL,
  week_start  date NOT NULL,
  plan        numeric,
  actual      numeric,
  note        text,
  updated_by  text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (item_id, week_start)
);
CREATE INDEX IF NOT EXISTS okr_weekly_log_person_idx ON public.okr_weekly_log (person, week_start);
ALTER TABLE public.okr_weekly_log ENABLE ROW LEVEL SECURITY;  -- 서비스 키로만 접근
