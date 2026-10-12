-- 직원의 '올린 흔적' 기록 — 송금정보 업로드를 시도만 하고 끝내지 않은 경우도 대표님이 볼 수 있게
-- AGENTS.md 규칙 9번: SQL 파일 → 설명 → DB 적용 → 코드 배포
--
-- 변경 내용: 새 테이블 1개를 "추가"만 합니다. 기존 테이블·데이터는 건드리지 않습니다.
--
-- 배경 (2026-10-12 대표 요청):
--   곽재선님이 입력한 송금정보가 화면(마진 등)에 안 보이는 이유가 '미완성이라 등록이 안 된 것'인지,
--   '아예 시도도 안 한 것'인지 구분이 안 됐다. 등록 전 단계(불러오기·확인 중)는 저장되지 않기 때문.
--   그래서 직원이 파일을 불러오거나 등록을 누를 때마다 한 줄씩 남긴다. 대표님은 이 기록으로 '개선 지시'를 한다.
--
-- 칸 설명:
--   person         직원 이름
--   kind           기록 종류 (지금은 'payment' = 인플루언서 송금정보 등록)
--   stage          loaded(파일 불러옴) / parse_failed(파일을 못 읽음) / review(확인 중, 빠진 항목 있음)
--                  / register_blocked(등록 눌렀지만 확인 항목 때문에 막힘) / registered(저장 완료) / failed(저장 중 오류)
--   file_name      올린 파일 이름(있으면)
--   n_rows         그 시점의 전체 건수,  n_ok  등록 가능(또는 저장된) 건수,  n_blocked  빠진 항목 때문에 못 올린 건수
--   missing        빠진 항목별 건수  예: {"콘텐츠링크": 5, "신분증링크": 3}
--   detail         오류·안내 문구(원인을 숨기지 않기 위해 그대로 저장)
--   session_id     같은 작업 흐름을 묶는 값(한 번 불러와서 등록까지 가는 과정)
--
-- 저장하지 않는 것: 금액·이름·계좌·링크 같은 실제 송금 내용은 넣지 않는다(건수와 빠진 항목 이름만).
-- 보안: RLS 켬(정책 없음). 서비스 키로만 접근.
-- 되돌리기: DROP TABLE public.staff_upload_attempts;
-- 참고: 이 테이블이 없어도 직원 화면은 정상 동작합니다(기록만 안 남음).

CREATE TABLE IF NOT EXISTS public.staff_upload_attempts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  person      text NOT NULL,
  kind        text NOT NULL DEFAULT 'payment',
  stage       text NOT NULL CHECK (stage IN ('loaded','parse_failed','review','register_blocked','registered','failed')),
  file_name   text,
  n_rows      integer,
  n_ok        integer,
  n_blocked   integer,
  missing     jsonb,
  detail      text,
  session_id  text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS staff_upload_attempts_person_created_idx
  ON public.staff_upload_attempts (person, created_at DESC);

ALTER TABLE public.staff_upload_attempts ENABLE ROW LEVEL SECURITY;
