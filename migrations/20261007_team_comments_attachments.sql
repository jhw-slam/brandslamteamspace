-- 캠페인 캘린더 댓글에 파일 첨부 칸 추가
-- AGENTS.md 규칙 9번: SQL 파일 → 설명 → DB 적용 → 코드 배포
--
-- 변경 내용: public.team_comments 에 컬럼 2개를 "추가"만 합니다. 기존 댓글·컬럼은 건드리지 않습니다.
--   attachment_url  : 첨부 파일 주소 (Supabase contract-files 버킷의 comments/ 폴더)
--   attachment_name : 첨부 파일 이름
-- 안전성: IF NOT EXISTS 라서 여러 번 실행해도 안전합니다. 기존 댓글은 모두 NULL(첨부 없음)로 남습니다.
-- 되돌리기: ALTER TABLE public.team_comments DROP COLUMN attachment_url, DROP COLUMN attachment_name;

ALTER TABLE public.team_comments
  ADD COLUMN IF NOT EXISTS attachment_url  text,
  ADD COLUMN IF NOT EXISTS attachment_name text;
