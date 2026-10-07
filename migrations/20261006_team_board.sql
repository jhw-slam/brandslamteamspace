-- 팀 요청 게시판 + 댓글 (대표님 요청으로 적용)
-- AGENTS.md 규칙 9번: SQL 파일 → 설명 → DB 적용 → 코드 배포
--
-- 변경 내용: 새 테이블 2개를 "추가"만 합니다. 기존 테이블·데이터는 건드리지 않습니다.
--
-- 1) team_requests  — '요청 게시판'. 모두에게 보이는 글, 권한만 다름.
--      requester 가 assignee 에게 요청을 올림. 마감(due_date)이 지났는데 끝나지 않은 요청은
--      담당자 대시보드에 '⚠️ 처리요망'으로 보이고, 하루 1번 모아서 담당자 본인에게 메일이 감.
--      overdue_notified_at : 마지막으로 처리요망 메일에 포함된 시각(기록용).
--      related_* : 요청을 특정 캠페인/계정/날짜에 연결(예: "10/15 포스팅 일정 확인 부탁").
-- 2) team_comments  — 댓글. 요청(request)뿐 아니라 캠페인·계정·특정 일자 달력 칸에도 달 수 있음.
--
-- 보안: 두 테이블 모두 RLS를 켭니다(정책 없음). 이 앱은 서비스 키로만 접근하므로 동작에는 영향이 없고,
--       앱 밖(공개 키)에서의 직접 접근은 막힙니다. (support_chat_staff 처럼 RLS가 꺼진 채로 만들지 않기 위함)
-- 되돌리기: DROP TABLE public.team_comments; DROP TABLE public.team_requests;

CREATE TABLE IF NOT EXISTS public.team_requests (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  requester           text NOT NULL,
  assignee            text NOT NULL,
  title               text NOT NULL,
  body                text,
  due_date            date,
  priority            text NOT NULL DEFAULT '보통' CHECK (priority IN ('낮음', '보통', '높음', '긴급')),
  status              text NOT NULL DEFAULT '요청' CHECK (status IN ('요청', '확인', '진행중', '완료', '보류')),
  related_type        text CHECK (related_type IN ('campaign', 'account', 'date')),
  related_id          uuid,
  related_date        date,
  completed_at        timestamptz,
  overdue_notified_at timestamptz
);
CREATE INDEX IF NOT EXISTS team_requests_status_due_idx ON public.team_requests (status, due_date);
CREATE INDEX IF NOT EXISTS team_requests_assignee_idx   ON public.team_requests (assignee, status);

CREATE TABLE IF NOT EXISTS public.team_comments (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at  timestamptz NOT NULL DEFAULT now(),
  target_type text NOT NULL CHECK (target_type IN ('request', 'campaign', 'account', 'date')),
  target_id   uuid,
  target_date date,
  author      text NOT NULL,
  body        text NOT NULL
);
CREATE INDEX IF NOT EXISTS team_comments_target_idx ON public.team_comments (target_type, target_id);
CREATE INDEX IF NOT EXISTS team_comments_date_idx   ON public.team_comments (target_date);

ALTER TABLE public.team_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.team_comments ENABLE ROW LEVEL SECURITY;
