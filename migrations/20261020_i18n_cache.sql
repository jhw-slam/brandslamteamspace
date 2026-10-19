-- 화면 번역 캐시(10/20): 영어/중국어로 한 번 번역한 문구를 저장해 두고 다음부터 바로 보여준다.
-- 새 테이블만 추가 — 기존 데이터는 건드리지 않음. 이 테이블이 없어도 앱은 죽지 않고(기본 번역만 쓰고) 동작한다.
create table if not exists public.i18n_cache (
  lang text not null,          -- 'en' | 'zh'
  src text not null,           -- 한국어 원문(숫자·직원 이름은 {0},{1}로 바꾼 틀)
  tgt text not null,           -- 번역문
  source text default 'ai',    -- 'google' | 'ai' | 'manual'
  created_at timestamptz default now(),
  primary key (lang, src)
);
alter table public.i18n_cache enable row level security;  -- 서비스 키로만 접근
