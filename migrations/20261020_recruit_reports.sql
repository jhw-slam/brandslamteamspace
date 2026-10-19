-- 모집 파트 보고 링크 (10/20): 유원리·이단우·Sanubari·Meyna가 구글드라이브 링크를 지속적으로 올리고, 대표님이 한 번에 모아 본다.
-- 영향: 새 테이블 1개 추가(기존 데이터 변화 없음). 되돌리기: DROP TABLE public.recruit_reports;
-- 대표용 화면(brandslamContract)에서도 같은 DB의 이 테이블을 읽어서 보여줄 수 있다(link·person·kind·title·report_date).
CREATE TABLE IF NOT EXISTS public.recruit_reports (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  person       text NOT NULL,
  link         text NOT NULL,                 -- 구글드라이브/문서/시트 링크
  title        text,                          -- 한 줄 제목(선택)
  kind         text,                          -- 인플루언서 후보 / 왕홍 / 전문가 / 자체채널 / 기타
  note         text,
  report_date  date NOT NULL DEFAULT current_date,
  week_start   date NOT NULL,                 -- 그 주 월요일(같은 사람·같은 링크는 한 주에 한 번)
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (person, link, week_start)
);
CREATE INDEX IF NOT EXISTS recruit_reports_person_idx ON public.recruit_reports (person, report_date DESC);
ALTER TABLE public.recruit_reports ENABLE ROW LEVEL SECURITY;  -- 서비스 키로만 접근
