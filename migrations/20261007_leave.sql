-- 개인별 휴가(연차·반차·반반차) 신청 + 잔여 휴가 계산용 테이블
-- AGENTS.md 규칙 9번: SQL 파일 → 설명 → DB 적용 → 코드 배포
--
-- 변경 내용: 새 테이블 2개를 "추가"만 합니다. 기존 테이블·데이터는 건드리지 않습니다.
--
-- 1) leave_profiles — 사람별 입사일과 연간 부여 일수(기본 15일).
--      입사 1년 미만은 '매달 1일씩 발생한 만큼', 1년 이상은 '연 15일을 자유롭게' 쓰기 때문에 입사일이 필요함.
--      이 앱에서는 본인이 처음 한 번만 입력할 수 있고, 이후 수정은 DB(대표님)에서만 함.
-- 2) leave_requests — 휴가 사용 기록(하루/반차/반반차). 취소하면 삭제하지 않고 canceled_at 만 채움.
--      1일 = 8시간, 반차 = 4시간, 반반차 = 2시간 (hours 에 2·4·8 만 허용, kind 와 일치해야 함).
--      slot : 반차(오전/오후), 반반차(오전 앞/오전 뒤/오후 앞/오후 뒤). 같은 날 같은 시간대가 겹치지 않게 앱에서 확인.
--
-- 보안: 두 테이블 모두 RLS 켬(정책 없음). 이 앱은 서비스 키로만 접근하므로 동작에는 영향 없음.
-- 되돌리기: DROP TABLE public.leave_requests; DROP TABLE public.leave_profiles;

CREATE TABLE IF NOT EXISTS public.leave_profiles (
  person      text PRIMARY KEY,
  hire_date   date NOT NULL,
  annual_days numeric NOT NULL DEFAULT 15 CHECK (annual_days >= 0),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.leave_requests (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at  timestamptz NOT NULL DEFAULT now(),
  person      text NOT NULL,
  leave_date  date NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('연차', '반차', '반반차')),
  slot        text,
  hours       numeric NOT NULL CHECK (hours IN (2, 4, 8)),
  memo        text,
  canceled_at timestamptz,
  CHECK ((kind = '연차' AND hours = 8) OR (kind = '반차' AND hours = 4) OR (kind = '반반차' AND hours = 2))
);
CREATE INDEX IF NOT EXISTS leave_requests_person_date_idx ON public.leave_requests (person, leave_date);
CREATE INDEX IF NOT EXISTS leave_requests_date_idx        ON public.leave_requests (leave_date);

ALTER TABLE public.leave_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leave_requests ENABLE ROW LEVEL SECURITY;
