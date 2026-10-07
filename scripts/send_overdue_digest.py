"""
처리요망 알림 메일 — 마감이 지난 요청을 담당자 '본인'에게 하루 1번 모아서 보냅니다.

하는 일
1. team_requests 중 마감일(due_date)이 오늘(한국 날짜)보다 이전이고 아직 끝나지 않은(완료·보류가 아닌) 요청을 찾는다.
2. 담당자(assignee)별로 모아서, 사람마다 메일 1통(여러 건이면 목록으로)을 보낸다.
3. 오늘 이미 보낸 사람(email_log의 purpose='overdue_requests')에게는 다시 보내지 않는다 → 몇 번 실행해도 하루 1통.
4. 보낸 요청에는 overdue_notified_at(마지막으로 알린 시각)을 남긴다. 처리하면 다음 날부터 자동으로 빠진다.

실행 방법 (Railway Cron 서비스 하나를 새로 만들어서)
  Start Command : python scripts/send_overdue_digest.py
  Cron Schedule : 0 0 * * 1-5        ← Railway 크론은 UTC. 한국 평일 오전 9시
  Variables     : SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY, RESEND_FROM,
                  (선택) ADMIN_BCC_EMAIL, DAILY_REPORT_APP_URL(바로가기 링크)
  미리보기      : python scripts/send_overdue_digest.py --dry-run   (메일을 보내지 않고 누구에게 뭘 보낼지만 출력)

⚠️ staging과 운영이 같은 Supabase를 쓰면 이 스크립트는 실제 직원 메일로 나갑니다. 처음에는 --dry-run으로 확인하세요.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from supabase import create_client

PURPOSE = "overdue_requests"
KST = timezone(timedelta(hours=9))
RESEND_FROM = os.environ.get("RESEND_FROM", "브랜드슬램 업무보고 <onboarding@resend.dev>")
ADMIN_BCC_EMAIL = os.environ.get("ADMIN_BCC_EMAIL")
APP_URL = os.environ.get("DAILY_REPORT_APP_URL", "")


def kst_today():
    return datetime.now(KST).date()


def kst_day_start_utc_iso():
    start = datetime.combine(kst_today(), datetime.min.time(), tzinfo=KST)
    return start.astimezone(timezone.utc).isoformat()


def build_digest(person, items, today):
    """담당자 한 명에게 보낼 제목·본문. 오래 지난 것부터 보여준다."""
    items = sorted(items, key=lambda r: str(r["due_date"]))
    lines = []
    for r in items:
        days = (today - datetime.fromisoformat(str(r["due_date"])[:10]).date()).days
        lines.append(f"- [{r.get('priority') or '보통'}] {r['title']} (요청: {r['requester']} · 마감 {r['due_date']} · {days}일 지남)")
    link = f"\n바로가기: {APP_URL}\n" if APP_URL else "\n"
    subject = f"[처리요망] 마감이 지난 요청 {len(items)}건"
    body = (
        f"{person}님, 마감이 지난 요청이 {len(items)}건 있어요.\n\n"
        + "\n".join(lines)
        + "\n\n'요청 게시판'에서 상태를 바꾸거나, 어려우면 댓글로 상황을 남겨주세요."
        + link
        + "\n- 브랜드슬램 업무보고 (자동발송)"
    )
    return subject, body


def send_email(supa, api_key, to_addr, subject, body):
    payload = {"from": RESEND_FROM, "to": [to_addr], "subject": subject, "text": body}
    if ADMIN_BCC_EMAIL:
        payload["bcc"] = [ADMIN_BCC_EMAIL]
    res = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload, timeout=15,
    )
    ok = res.status_code < 300
    supa.table("email_log").insert({
        "purpose": PURPOSE, "recipient": to_addr, "subject": subject, "body": body,
        "status": "sent" if ok else "failed",
        "error": None if ok else f"{res.status_code} {res.text}"[:500],
    }).execute()
    if not ok:
        print(f"  ⚠️ {to_addr} 발송 실패: {res.status_code} {res.text[:200]}")
    return ok


def main(dry_run=False):
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    api_key = os.environ.get("RESEND_API_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 없습니다.")
    if not api_key and not dry_run:
        raise SystemExit("RESEND_API_KEY 환경변수가 없습니다. (미리보기만 하려면 --dry-run)")
    supa = create_client(url, key)
    today = kst_today()

    rows = (
        supa.table("team_requests").select("*")
        .lt("due_date", today.isoformat()).neq("status", "완료").neq("status", "보류").execute().data
    )
    by_person = {}
    for r in rows:
        by_person.setdefault(r["assignee"], []).append(r)
    print(f"[{today}] 마감 지난 요청 {len(rows)}건 / 담당자 {len(by_person)}명")
    if not by_person:
        return

    org = {o["person"]: o for o in supa.table("okr_org").select("person,email,pending").execute().data}
    sent_today = {
        e["recipient"] for e in
        supa.table("email_log").select("recipient").eq("purpose", PURPOSE).eq("status", "sent")
        .gte("sent_at", kst_day_start_utc_iso()).execute().data
    }
    for person, items in by_person.items():
        o = org.get(person) or {}
        email = (o.get("email") or "").strip()
        if o.get("pending") or not email:
            print(f"  - {person}: 이메일 없음/공석이라 건너뜀 ({len(items)}건)")
            continue
        if email in sent_today:
            print(f"  - {person}: 오늘 이미 보냈어요")
            continue
        subject, body = build_digest(person, items, today)
        if dry_run:
            print(f"  [미리보기] {person} <{email}> — {subject}\n{body}\n")
            continue
        if send_email(supa, api_key, email, subject, body):
            now_iso = datetime.now(timezone.utc).isoformat()
            for r in items:
                supa.table("team_requests").update({"overdue_notified_at": now_iso}).eq("id", r["id"]).execute()
            print(f"  ✅ {person} <{email}> {len(items)}건 발송")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
