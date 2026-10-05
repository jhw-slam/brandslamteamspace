-- 세일즈 캠페인 등록: 계약서 연결용 컬럼 추가
-- 변경 내용: public.sales_campaigns 에 컬럼 2개를 "추가"만 합니다. 기존 데이터·컬럼은 건드리지 않습니다.
--   contract_url  : 계약서 링크 (구글드라이브 링크 또는 Supabase contract-files 업로드 주소)
--   contract_name : 계약서 파일 이름
-- 안전성: IF NOT EXISTS 라서 여러 번 실행해도 안전합니다. 값이 없는 캠페인은 NULL 입니다.
-- 되돌리기: ALTER TABLE public.sales_campaigns DROP COLUMN contract_url, DROP COLUMN contract_name;

ALTER TABLE public.sales_campaigns
  ADD COLUMN IF NOT EXISTS contract_url  text,
  ADD COLUMN IF NOT EXISTS contract_name text;
