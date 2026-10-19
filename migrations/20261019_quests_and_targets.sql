-- 퀘스트(대·중·소 미션) + 월 목표 + 콘텐츠 반응 칸 (10/19)
-- 영향: ① influencer_placements에 칸 2개(댓글·공유 수) 추가  ② 새 테이블 quests 1개  ③ 시작 데이터(퀘스트·월 목표) 입력.
-- 모두 여러 번 실행해도 중복되지 않게 만들었어요(IF NOT EXISTS / ON CONFLICT DO NOTHING).
-- 근거: 2026-10-19 '직무 OKR 재설정 — OWM 기획전 운영 + 전문가 풀 구축' 문서와 대표님 답변(터진 콘텐츠=조회 1만+ & 반응 1천+, 월 목표 숫자들).

-- ① 터진 콘텐츠 판정용: 반응 = 좋아요 + 저장 + 댓글 + 공유 (채널과 상관없이 같은 기준)
ALTER TABLE public.influencer_placements
  ADD COLUMN IF NOT EXISTS comments integer,
  ADD COLUMN IF NOT EXISTS shares   integer;

-- ② 퀘스트: big=대(Objective) / mid=중(KR) / small=소(할 일). 완료하면 xp를 얻는다.
CREATE TABLE IF NOT EXISTS public.quests (
  id         uuid PRIMARY KEY,
  kind       text NOT NULL CHECK (kind IN ('big','mid','small')),
  parent_id  uuid REFERENCES public.quests(id) ON DELETE SET NULL,
  title      text NOT NULL,
  owner      text NOT NULL,
  due_date   date,
  kpi_key    text,
  xp         integer NOT NULL DEFAULT 0,
  status     text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','dropped')),
  done_at    timestamptz,
  done_by    text,
  note       text,
  source     text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS quests_owner_idx ON public.quests (owner, status, due_date);
ALTER TABLE public.quests ENABLE ROW LEVEL SECURITY;  -- 서비스 키로만 접근

INSERT INTO public.quests (id, kind, parent_id, title, owner, due_date, kpi_key, xp, source) VALUES
  ('50a8df36-ca25-4789-805f-24eef5e2ca24', 'big', NULL::uuid, '월 매출 1억 유지 + 매월 15% 이상 성장', '김선재', NULL::date, 'revenue', 0, '직무 OKR 재설정 2026-10-19'),
  ('75859bb3-a740-4aa3-926d-c32f76de69f0', 'big', NULL::uuid, '월간 기획전(OWM)으로 브랜드 참여·약사 세일즈 키우기 — 11월부터 매월 1건', '김선재', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('48175d2c-bdbc-48f6-b09f-38ef57ee0e98', 'big', NULL::uuid, '검증된 전문가(약사) 풀 상시 구축 — 연말 30명, 이후 월 +10명', '곽재선', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('c3e813ac-01f6-4d69-b559-973deb3b34a7', 'big', NULL::uuid, '인플루언서 pool을 키우고 ''터지는 콘텐츠'' 비율 높이기 (조회 1만+ & 반응 1천+)', '곽재선', NULL::date, 'popped_rate', 0, '직무 OKR 재설정 2026-10-19'),
  ('59a02155-eae5-4172-b967-a730749e5e71', 'big', NULL::uuid, '중국: 왕홍 관리 + 샤오홍슈 자체채널 영향력 키우기', '이단우', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('72a4a6bb-271e-4374-ad44-89fff1dac9e5', 'mid', '50a8df36-ca25-4789-805f-24eef5e2ca24'::uuid, '월 매출 1억 유지', '김선재', NULL::date, 'revenue', 0, '직무 OKR 재설정 2026-10-19'),
  ('751924fb-272b-4501-911b-0c1ceb4ae619', 'mid', '50a8df36-ca25-4789-805f-24eef5e2ca24'::uuid, '전월 대비 매출 성장률 15% 이상', '김선재', NULL::date, 'revenue_growth', 0, '직무 OKR 재설정 2026-10-19'),
  ('1ee34dc2-a713-4d30-a97a-6cc92dd424ca', 'mid', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '회차당 참여 브랜드 8~10개 (신청+입금 완료)', '김선재', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('8eb0d14e-7619-41b4-82ce-3717b92ea8ab', 'mid', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '브랜드사 재참여율 60% 이상', '김선재', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('f1784573-d7a0-432b-913e-735ba084f4ee', 'mid', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '기획전 SKU 매출 직전 4주 대비 1.5배 이상', '김선재', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('69b4f0c2-9091-4cea-9620-adc6de860ded', 'mid', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '기획전 안내 자동 발송(신청→입금 확정→대시보드+이메일) 100%', '구정회', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('8b8179be-ef6d-4f0c-96be-4c88282178aa', 'mid', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '온라인 가격 충돌 0건 (국내·중국 티몰글로벌/샤오홍슈몰/타오바오 환산가 포함)', '이단우', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('a427e496-85ad-4808-be5b-1c2157e9d1cc', 'mid', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '효능표현 규제 이슈 0건', '곽재선', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('2e0b927f-bf41-4399-a158-9498bb258e19', 'mid', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '''약사 추천'' 콘텐츠가 붙은 기획전 SKU 50% 이상', '곽재선', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('3a741f01-549a-46e4-8c0a-cb8567c4f93f', 'mid', '48175d2c-bdbc-48f6-b09f-38ef57ee0e98'::uuid, '전문가 DB 구조 확정 + 면허 불일치·가짜 0건', '구정회', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('a801ff11-a8db-450c-882c-6a4f25e37761', 'mid', '48175d2c-bdbc-48f6-b09f-38ef57ee0e98'::uuid, '기획전 참여 약사 → 풀 등록 50% 이상', '김선재', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('992cfbfe-3029-4574-a367-d0ad7a975b56', 'mid', '48175d2c-bdbc-48f6-b09f-38ef57ee0e98'::uuid, '독점계약 비율 30% 이상 / 이탈률 10% 이하', '김선재', NULL::date, NULL, 0, '직무 OKR 재설정 2026-10-19'),
  ('50c4f668-1a84-433e-9489-5e209bc20a83', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '브랜드가 선정한 콘텐츠 가이드 월 10개 이상', '곽재선', NULL::date, 'guide_selected', 0, '직무 OKR 재설정 2026-10-19'),
  ('8f7c2688-105d-4a64-be08-cf34c0b0d4da', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '터진 콘텐츠 비율 10% 이상', '곽재선', NULL::date, 'popped_rate', 0, '직무 OKR 재설정 2026-10-19'),
  ('9f5bbc15-9097-4936-99d7-28488e83445f', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '검증되고 ''사용된'' pool 월 30명 이상', '곽재선', NULL::date, 'pool_new', 0, '직무 OKR 재설정 2026-10-19'),
  ('6713688e-1e9a-4737-aa6f-8d34213955b1', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '브랜드가 선정한 콘텐츠 가이드 월 10개 이상', '이단우', NULL::date, 'guide_selected', 0, '직무 OKR 재설정 2026-10-19'),
  ('db31be06-e273-4262-aa83-3528cb010f14', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '터진 콘텐츠 비율 10% 이상', '이단우', NULL::date, 'popped_rate', 0, '직무 OKR 재설정 2026-10-19'),
  ('7997986a-b6be-4d4e-acc5-fd7638f89420', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '검증되고 ''사용된'' pool 월 30명 이상', '이단우', NULL::date, 'pool_new', 0, '직무 OKR 재설정 2026-10-19'),
  ('e3963006-2b2d-4e23-bbfd-cd24e0e2972c', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '브랜드가 선정한 콘텐츠 가이드 월 10개 이상', '유원리', NULL::date, 'guide_selected', 0, '직무 OKR 재설정 2026-10-19'),
  ('7d51f01b-6fed-4b78-a640-1dd148044016', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '터진 콘텐츠 비율 10% 이상', '유원리', NULL::date, 'popped_rate', 0, '직무 OKR 재설정 2026-10-19'),
  ('72ae6bee-93e3-438f-8a15-f7651cd3bf7c', 'mid', 'c3e813ac-01f6-4d69-b559-973deb3b34a7'::uuid, '검증되고 ''사용된'' pool 월 30명 이상', '유원리', NULL::date, 'pool_new', 0, '직무 OKR 재설정 2026-10-19'),
  ('34af6b97-0958-42bd-ad2e-a4b4700f5093', 'mid', '59a02155-eae5-4172-b967-a730749e5e71'::uuid, '자체채널(샤오홍슈) 팔로워 1만명', '이단우', NULL::date, 'own_followers', 0, '직무 OKR 재설정 2026-10-19'),
  ('4b227e00-e0e5-4bad-88a5-3396ef78c283', 'mid', '59a02155-eae5-4172-b967-a730749e5e71'::uuid, '직접 소통하는 위챗방 100명', '이단우', NULL::date, 'wechat_room', 0, '직무 OKR 재설정 2026-10-19'),
  ('672a8fc0-868a-488f-8d2f-16a38ff3c694', 'mid', '59a02155-eae5-4172-b967-a730749e5e71'::uuid, '왕홍 관리 — 관리 중인 왕홍 수 주간 기록', '이단우', NULL::date, 'wanghong', 0, '직무 OKR 재설정 2026-10-19'),
  ('88211813-403f-40f7-bf2c-902e2dbbc506', 'mid', '59a02155-eae5-4172-b967-a730749e5e71'::uuid, '자체채널(샤오홍슈) 팔로워 1만명', '유원리', NULL::date, 'own_followers', 0, '직무 OKR 재설정 2026-10-19'),
  ('496911ed-3460-4ee6-a62a-3eb910015058', 'mid', '59a02155-eae5-4172-b967-a730749e5e71'::uuid, '직접 소통하는 위챗방 100명', '유원리', NULL::date, 'wechat_room', 0, '직무 OKR 재설정 2026-10-19'),
  ('e276e407-b016-43bf-ae8f-5f38bbc04ace', 'mid', '59a02155-eae5-4172-b967-a730749e5e71'::uuid, '왕홍 관리 — 관리 중인 왕홍 수 주간 기록', '유원리', NULL::date, 'wanghong', 0, '직무 OKR 재설정 2026-10-19'),
  ('9477b536-f915-4005-a8c6-3307fe592a98', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '김진호 대표·이진만 이사에게 ''기존 업무 개선''으로 공유', '장현우', '2026-10-23'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('afe73dd2-57f8-401a-af73-27e69e7ddaf0', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '송우재 이사와 역할 분담 확인', '장현우', '2026-10-24'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('6fc4d82f-5899-4137-8bed-efa319f17ad2', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '기획전 신청서 양식 확정', '장현우', '2026-10-24'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('049cf397-f3d2-444a-b98a-6b9c6913397b', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '신청·입금 → 대시보드+이메일 자동 발송 점검', '구정회', '2026-10-30'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('e7dbbf34-3946-4751-84f1-ce431aca71bb', 'small', '48175d2c-bdbc-48f6-b09f-38ef57ee0e98'::uuid, '전문가 DB 구조 확정(면허 검증·전문분야·지점·계약)', '구정회', '2026-10-30'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('8492ad37-bc6e-4e44-bdbc-951c2ca28e64', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '글로벌 온라인 가격 체크 시트 만들기(중국 채널 환산가 포함)', '이단우', '2026-10-30'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('65d347c9-c0b6-453c-bd2d-dbdf36818215', 'small', '48175d2c-bdbc-48f6-b09f-38ef57ee0e98'::uuid, '약사 면허 검증 절차 작성', '장현우', '2026-10-30'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('0c140f5e-9e79-4dc1-b199-7ea894c16438', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '11월 ''OWM 픽 10'' 공지 배포', '장현우', '2026-11-03'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('5587df9e-b763-4668-a75b-57e6663f7385', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '화요일 약사 세미나에서 기획전 소개', '장현우', '2026-11-04'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('4b0c4b34-b1c3-4b97-bb65-f3b954239189', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '효능표현 체크리스트 1차본', '곽재선', '2026-11-07'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('e70f0f06-c3e0-4328-b34a-48cec6cf1a15', 'small', '48175d2c-bdbc-48f6-b09f-38ef57ee0e98'::uuid, '약국장 대상 풀 등록 동의·수익 배분안 공유', '장현우', '2026-11-11'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('d7053b2f-5fbb-4a96-8c5b-9479315a43f4', 'small', '48175d2c-bdbc-48f6-b09f-38ef57ee0e98'::uuid, '11월 기획전 참여 약사 중 1차 풀 등록', '장현우', '2026-11-30'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('32baaa5e-5049-4628-ad2e-67f54ed8e4b4', 'small', '75859bb3-a740-4aa3-926d-c32f76de69f0'::uuid, '11월 ''OWM 픽 10'' 참여 브랜드 모집 시작(공지 후 신청서 접수)', '김선재', '2026-11-03'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('c39a65dc-59bf-4891-815d-530332c246ab', 'small', '59a02155-eae5-4172-b967-a730749e5e71'::uuid, '샤오홍슈 자체채널 첫 현황 기록(팔로워·주간 조회·모집 인입) — 목표 지표의 출발점', '유원리', '2026-10-26'::date, NULL, 20, '직무 OKR 재설정 2026-10-19'),
  ('09d3a15e-60f7-43ad-8695-85cd52890ae1', 'small', '59a02155-eae5-4172-b967-a730749e5e71'::uuid, '위챗방 현재 인원 첫 기록 + 왕홍 관리 명단 정리', '이단우', '2026-10-26'::date, NULL, 20, '직무 OKR 재설정 2026-10-19')
ON CONFLICT (id) DO NOTHING;


-- ③ 월 목표(대표님 답변 10/19): 매출 1억(당분간 유지)·성장 15%·터진 비율 10%·가이드 선정 10개·검증/사용 pool 월 30명·자체채널 팔로워 1만·위챗방 100명
INSERT INTO public.kpi_targets (person, metric_key, month_target) VALUES
  ('김선재','revenue',100000000), ('김선재','revenue_growth',15),
  ('곽재선','guide_selected',10), ('곽재선','popped_rate',10), ('곽재선','pool_new',30),
  ('이단우','guide_selected',10), ('이단우','popped_rate',10), ('이단우','pool_new',30), ('이단우','own_followers',10000), ('이단우','wechat_room',100),
  ('유원리','guide_selected',10), ('유원리','popped_rate',10), ('유원리','pool_new',30), ('유원리','own_followers',10000), ('유원리','wechat_room',100)
ON CONFLICT (person, metric_key) DO NOTHING;
