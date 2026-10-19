-- 핵심 지표(KPI) 주간 추적 (10/19): 사람(역할)마다 정한 지표를 매주 '계획 → 실제'로 보고 우상향 그래프로 확인한다.
-- 영향: 새 테이블 3개만 추가(기존 데이터 변화 없음). 여러 번 실행해도 안전합니다.
-- ※ 먼저 올렸던 20261019_okr_weekly.sql은 이 파일로 대체되어 삭제했어요. 이미 실행했다면 그대로 둬도 됩니다(쓰지 않음).

-- ① 기록 한 줄: 자동으로 안 잡히는 지표(가이드 선정·모집·왕홍·자체채널·설득·기획전)를 직원이 남긴다
CREATE TABLE IF NOT EXISTS public.kpi_events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  person      text NOT NULL,
  metric_key  text NOT NULL,
  event_date  date NOT NULL,
  qty         numeric NOT NULL DEFAULT 1,
  brand_name  text,
  note        text,
  created_by  text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kpi_events_person_idx ON public.kpi_events (person, metric_key, event_date);

-- ② 주간 계획: 그 주에 하겠다고 한 숫자(사람×지표×주, 주=월요일 시작)
CREATE TABLE IF NOT EXISTS public.kpi_weekly_plan (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  person      text NOT NULL,
  metric_key  text NOT NULL,
  week_start  date NOT NULL,
  plan        numeric,
  note        text,
  updated_by  text,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (person, metric_key, week_start)
);

-- ③ 월 목표 숫자(대표가 정함)
CREATE TABLE IF NOT EXISTS public.kpi_targets (
  person        text NOT NULL,
  metric_key    text NOT NULL,
  month_target  numeric,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (person, metric_key)
);

ALTER TABLE public.kpi_events      ENABLE ROW LEVEL SECURITY;  -- 서비스 키로만 접근
ALTER TABLE public.kpi_weekly_plan ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kpi_targets     ENABLE ROW LEVEL SECURITY;
