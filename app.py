import os
import io
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="업무보고", layout="wide", initial_sidebar_state="collapsed")

# ── 앱 공통 비밀번호 게이트 (다른 페이지와 동일) ──
PW = os.environ.get("APP_PASSWORD")
if PW and not st.session_state.get("ok"):
    pw = st.text_input("비밀번호", type="password")
    if st.button("입장"):
        if pw == PW:
            st.session_state.ok = True; st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

st.title("📋 업무보고")
st.caption("업체별 컨텐츠 배치, 가이드라인 준수, 섭외 지시, 예정입출금 — 오늘 진행한 것만 짧게 남겨주세요.")

STAFF_NAMES = ["김선재", "곽재선", "구정회", "이단우", "Sanubari", "Meyna"]
CATEGORY_OPTS = ["뷰티", "라이프스타일", "기타"]
CONTENT_TYPE_OPTS = ["PPL", "시딩", "방문형", "캐러셀", "기타"]
STATUS_OPTS = ["섭외중", "섭외완료", "제작중", "업로드완료", "드롭앤고체크완료", "취소"]
STATUS_EMOJI = {
    "섭외중": "🟡", "섭외완료": "🔵", "제작중": "🟠",
    "업로드완료": "🟢", "드롭앤고체크완료": "✅", "취소": "⚪",
}
GUIDELINE_OPTS = ["미확인", "가이드라인 준수", "수정 필요"]
GUIDELINE_TO_BOOL = {"미확인": None, "가이드라인 준수": True, "수정 필요": False}
BOOL_TO_GUIDELINE = {None: "미확인", True: "가이드라인 준수", False: "수정 필요"}

# 구글시트 열 이름 ↔ DB 컬럼 매핑 (실제 직원들이 쓰던 작업시트 헤더 기준)
# 열 이름은 아래 별칭 중 아무거나 써도 인식됨 (대소문자 구분 없음)
SHEET_COL_MAP = {
    "influencer_name": ["Name", "이름", "인플루언서명", "인플루언서", "아이디 이름", "아이디이름", "SNS_ID"],
    "sns_id": ["SNS_ID", "SNS_아이디"],
    "sns_url": ["SNS_URL", "SNS_링크", "인스타링크", "틱톡링크", "프로필링크"],
    "followers": ["팔로워", "팔로워수", "팔로워 수"],
    "email": ["이메일", "이메일주소"],
    "address": ["주소"],
    "shipping_address": ["발송주소", "발송 주소"],
    "phone": ["전화번호", "연락처"],
    "visit_location": ["방문지점", "지점"],
    "visit_date": ["방문날짜", "방문일"],
    "product_name": ["상품", "제품명", "상품명"],
    "content_link": [
        "Upload_URL", "업로드URL", "업로드_URL", "콘텐츠링크", "콘텐츠 링크",
        "업로드 인스타 링크", "업로드 틱톡 링크", "업로드인스타링크", "업로드틱톡링크",
    ],
    "views": ["조회수"],
    "likes": ["좋아요수", "좋아요"],
    "saves": ["저장수"],
    "brand_name": ["브랜드사", "브랜드명", "브랜드", "업체명"],
    "category": ["카테고리", "분류"],
    "content_type": ["콘텐츠유형", "콘텐츠 유형", "유형"],
    "agency_name": ["대행사", "대행사명"],
    "scheduled_date": ["예정일", "예정 날짜"],
    "unit_price": ["단가", "인플루언서단가", "금액"],
    "casting_assigned_to": ["섭외지시대상", "섭외 지시 대상", "섭외담당"],
    "guideline_link": ["가이드라인링크", "가이드라인 링크"],
    "notes": ["메모", "비고"],
}
# 시트 열 이름이 대소문자/공백만 다르게 들어와도 인식되도록, 별칭을 정규화해서 매칭한다
SHEET_COL_MAP_NORM = {
    db_col: [a.strip().lower() for a in aliases] for db_col, aliases in SHEET_COL_MAP.items()
}


def _clean_number(val):
    if val is None:
        return None
    s = str(val).strip().replace(",", "")
    if not s or s in ("-", "–", "N/A", "n/a"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _clean_date(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", "none", "-", "n/a", "null"):
        return None
    s = s.replace(".", "-").rstrip("-")
    try:
        d = pd.to_datetime(s)
        if pd.isna(d):  # pd.to_datetime("nan") 등은 예외 없이 NaT를 반환하므로 반드시 별도 체크 필요
            return None
        return d.date().isoformat()
    except Exception:
        return None


_ALL_ALIASES_NORM = set()
for _aliases in SHEET_COL_MAP_NORM.values():
    _ALL_ALIASES_NORM.update(_aliases)


def _find_header_rows(raw_df, min_matches=2):
    """시트 안에 섹션이 여러 개 있어서 헤더가 1행이 아닐 수도 있으니,
    알려진 헤더 이름이 2개 이상 매치되는 행을 전부 헤더 후보로 찾는다."""
    header_rows = []
    for i in range(len(raw_df)):
        cells_norm = [str(c).strip().lower() for c in raw_df.iloc[i].tolist() if str(c).strip() and str(c) != "nan"]
        if sum(1 for c in cells_norm if c in _ALL_ALIASES_NORM) >= min_matches:
            header_rows.append(i)
    return header_rows


def _parse_multi_section_sheet(raw_df):
    """찾은 헤더 행들을 기준으로 시트를 여러 섹션으로 나눠서, 섹션마다 각자의 헤더로 파싱한다."""
    header_rows = _find_header_rows(raw_df)
    if not header_rows:
        # 헤더 후보를 하나도 못 찾으면, 그냥 1행을 헤더로 보고 기존 방식대로 시도
        raw_df.columns = [
            (str(c).strip() if pd.notna(c) and str(c).strip() else f"_blank_{i}")
            for i, c in enumerate(raw_df.iloc[0].tolist())
        ]
        return [_map_sheet_row(r) for _, r in raw_df.iloc[1:].iterrows()]

    all_rows = []
    for idx, hidx in enumerate(header_rows):
        end = header_rows[idx + 1] if idx + 1 < len(header_rows) else len(raw_df)
        header = [
            (str(x).strip() if pd.notna(x) and str(x).strip() else f"_blank_{i}")
            for i, x in enumerate(raw_df.iloc[hidx].tolist())
        ]
        section_df = raw_df.iloc[hidx + 1: end].copy()
        section_df.columns = header
        for _, r in section_df.iterrows():
            non_empty = sum(1 for v in r if pd.notna(v) and str(v).strip())
            if non_empty < 2:
                continue  # 구분줄/섹션 제목줄처럼 내용이 거의 없는 행은 건너뜀
            mapped = _map_sheet_row(r)
            if mapped.get("influencer_name"):
                all_rows.append(mapped)
    return all_rows


@st.cache_resource
def sb():
    url = os.environ.get("SUPABASE_URL"); key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        st.error("❌ SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 없습니다."); st.stop()
    return create_client(url, key)
SUPA = sb()


@st.cache_data(ttl=20)
def load_placements():
    return SUPA.table("influencer_placements").select("*").order("created_at", desc=True).execute().data


@st.cache_data(ttl=20)
def load_activity_log(limit=15):
    return SUPA.table("daily_activity_log").select("*").order("created_at", desc=True).limit(limit).execute().data


@st.cache_data(ttl=20)
def load_forecasts():
    return SUPA.table("fin_cash_forecasts").select("*").order("created_at", desc=True).limit(20).execute().data


def refresh():
    load_placements.clear()
    load_activity_log.clear()
    load_forecasts.clear()
    st.rerun()


my_name = st.selectbox("내 이름", STAFF_NAMES, key="my_name")

st.divider()

# ══════════════════════════════════════════════════════════
# 🧭 회사 비전 (항상 보임 — 모두가 바라보는 방향)
# ══════════════════════════════════════════════════════════
vision_data = SUPA.table("company_vision").select("*").order("updated_at", desc=True).limit(1).execute().data
if vision_data:
    v = vision_data[0]
    st.markdown(
        f"""<div style="background: linear-gradient(135deg, #10234f, #2e5597); padding: 20px 28px; border-radius: 16px 16px 0 0;">
<div style="color: #FFD700; font-size: 13px; font-weight: 800; letter-spacing: 3px;">VISION</div>
<div style="color: white; font-size: 28px; font-weight: 800; margin-top: 4px;">{v['title']}</div>
</div>""",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(v["content"])

st.divider()

# ══════════════════════════════════════════════════════════
# 🎯 팀 OKR 현황 (읽기 전용 — 기존 OKR 자료 그대로, 편집 기능 없음)
# ══════════════════════════════════════════════════════════
st.subheader("🎯 팀 OKR 현황")


@st.cache_data(ttl=60)
def load_okr():
    org = SUPA.table("okr_org").select("*").order("person").execute().data
    items = SUPA.table("okr_items").select("*").order("person").execute().data
    return org, items


with st.expander("열기 (평소엔 접어둠)", expanded=False):
    st.caption("전사 목표(OKR)를 참고용으로 보여드려요. 여기서는 수정이 안 되고 확인만 하는 용도예요 — 편집은 기존 OKR 페이지에서 계속 하시면 됩니다.")
    okr_org_data, okr_items_data = load_okr()

    if not okr_org_data:
        st.caption("등록된 OKR이 없습니다.")
    else:
        okr_view = st.radio("보기", ["🏢 회사 전체 OKR", "👤 개별 보기"], horizontal=True, key="okr_view_mode")

        if okr_view == "🏢 회사 전체 OKR":
            for o in okr_org_data:
                pending_tag = " · 🔲채용예정" if o.get("pending") else ""
                st.markdown(f"**{o['person']}**{pending_tag} — {o.get('objective') or '-'}")
        else:
            target_p = st.selectbox("사람 선택", [o["person"] for o in okr_org_data], key="okr_indiv_person")
            o = next(x for x in okr_org_data if x["person"] == target_p)
            with st.container(border=True):
                pending_tag = " · 🔲 채용예정" if o.get("pending") else ""
                st.markdown(f"#### 👤 {o['person']}{pending_tag}")
                if o.get("tag"):
                    st.caption(o["tag"])
                st.markdown(f"**🎯 Objective:** {o.get('objective') or '-'}")

                krs = o.get("krs") or []
                if krs:
                    st.markdown("**Key Results**")
                    for kr in krs:
                        st.markdown(f"- {kr}")

                person_items = [it for it in okr_items_data if it["person"] == o["person"]]

                def _render_item_card(it):
                    try:
                        target = float(it.get("target_qty") or 0)
                        progress = float(it.get("progress") or 0)
                    except (TypeError, ValueError):
                        target, progress = 0, 0
                    pct = min(progress / target, 1.0) if target > 0 else (1.0 if progress > 0 else 0.0)
                    conf = "✅" if it.get("confirmed") else "🔲"
                    unit = it.get("unit") or ""
                    progress_txt = f" — {progress:g}/{target:g}{unit}" if target > 0 else ""
                    with st.container(border=True):
                        st.markdown(f"{conf} **[{it.get('category') or '미분류'}]** {it['title']}{progress_txt}")
                        if target > 0:
                            st.progress(pct)

                okr_items_this = [it for it in person_items if not it.get("is_recurring")]
                kpi_items_this = [it for it in person_items if it.get("is_recurring")]

                if okr_items_this:
                    st.markdown(f"**🎯 이번 사이클 OKR 세부항목 ({len(okr_items_this)}개)** — 시한부 도전과제, 완료되면 끝")
                    for it in okr_items_this:
                        _render_item_card(it)
                if kpi_items_this:
                    st.markdown(f"**📊 상시 추적 KPI ({len(kpi_items_this)}개)** — 계속 반복해서 관리하는 건강지표")
                    for it in kpi_items_this:
                        _render_item_card(it)


# ══════════════════════════════════════════════════════════
# 🖊️ 오늘 빠른 기록
# ══════════════════════════════════════════════════════════
st.subheader("🖊️ 오늘 빠른 기록")
st.caption("오늘 한 일, 내일/오늘 할 일, 뭐든 편하게 적으세요. 링크나 PDF도 같이 남길 수 있어요 — 형식 신경 안 쓰셔도 됩니다.")
with st.form("quick_log_form", clear_on_submit=True):
    quick_note = st.text_area(
        "오늘/앞으로 할 일", placeholder="예: 오늘 사누바리한테 왕홍 5명 섭외 지시함 / 내일은 명동점 재고 확인 예정",
        label_visibility="collapsed", height=90,
    )
    qc1, qc2 = st.columns(2)
    quick_link = qc1.text_input("참고 링크(구글시트/문서 등, 선택)", placeholder="https://...")
    quick_file = qc2.file_uploader("파일 첨부(PDF 등, 선택)", type=["pdf", "docx", "png", "jpg", "jpeg", "xlsx"])
    quick_submitted = st.form_submit_button("📝 기록", type="primary", use_container_width=True)
def suggest_okr_match(note, person_items):
    """개떡같이 써도 찰떡같이 알아듣기: 자유 기록을 이 사람의 OKR/KPI 항목과 매칭해서
    진행치 업데이트를 제안한다. 확신 없으면 매칭 안 함."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not person_items:
        return None, None
    items_desc = "\n".join(
        f"- id:{it['id']} [{it.get('category') or ''}] {it['title']} "
        f"(현재 {it.get('progress') or 0}/{it.get('target_qty') or 0}{it.get('unit') or ''}, "
        f"{'KPI(반복)' if it.get('is_recurring') else 'OKR(이번사이클)'})"
        for it in person_items
    )
    system = (
        "너는 직원이 자유롭게 쓴 하루 업무 기록을 보고, 그 사람의 OKR/KPI 항목 중 관련된 것을 찾아 "
        "진행치 업데이트를 제안하는 보조원이다. 말투가 거칠거나 축약돼 있어도('개떡같이' 써도) 의미를 이해해서 매칭해라. "
        "기록에 구체적 숫자가 있으면 그 항목의 새 누적 진행치를 계산해 제안하고, 숫자가 없으면 progress는 null로 둬라. "
        "확신이 없으면 그 항목은 아예 배열에 넣지 마라. 최대 2개까지만 제안해라.\n\n"
        f"이 사람의 OKR/KPI 목록:\n{items_desc}\n\n"
        "출력은 오직 JSON 배열만: [{\"item_id\":\"...\", \"new_progress\": 숫자 또는 null, \"reason\":\"짧은 이유(20자 이내)\"}]. "
        "다른 텍스트는 절대 포함하지 마라."
    )
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-5", "max_tokens": 1000, "system": system,
                  "messages": [{"role": "user", "content": f"오늘 기록: {note}"}]},
            timeout=30,
        )
        if res.status_code >= 300:
            return None, f"{res.status_code}"
        data = res.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        import json as _json
        return _json.loads(text), None
    except Exception as e:
        return None, str(e)


if quick_submitted:
    if quick_note.strip():
        attachment_url = None
        if quick_file is not None:
            try:
                path = f"{my_name}/{int(pd.Timestamp.now().timestamp())}_{quick_file.name}"
                SUPA.storage.from_("daily-log-attachments").upload(
                    path, quick_file.getvalue(),
                    {"content-type": quick_file.type or "application/octet-stream"},
                )
                base = os.environ.get("SUPABASE_URL")
                attachment_url = f"{base}/storage/v1/object/public/daily-log-attachments/{path}"
            except Exception as e:
                st.warning(f"파일 첨부는 실패했지만 기록은 남길게요 ({e})")
        SUPA.table("daily_activity_log").insert({
            "staff_name": my_name, "note": quick_note.strip(),
            "link_url": quick_link.strip() or None, "attachment_url": attachment_url,
        }).execute()

        my_okr_items = [it for it in okr_items_data if it["person"] == my_name]
        suggestions, err = suggest_okr_match(quick_note.strip(), my_okr_items)
        if suggestions:
            st.session_state["pending_okr_suggestions"] = suggestions

        st.success("기록 완료!")
        refresh()
    else:
        st.error("한 줄이라도 적어주세요.")

# ── AI가 제안한 OKR/KPI 매칭 (개떡같이 써도 찰떡같이 알아듣기) ──
pending = st.session_state.get("pending_okr_suggestions") or []
if pending:
    st.markdown("🤖 **방금 기록을 보고 이 항목들이 떠올랐어요 — 진행치를 반영할까요?**")
    item_by_id = {it["id"]: it for it in okr_items_data}
    for sug in list(pending):
        it = item_by_id.get(sug.get("item_id"))
        if not it:
            st.session_state["pending_okr_suggestions"] = [s for s in st.session_state["pending_okr_suggestions"] if s is not sug]
            continue
        with st.container(border=True):
            st.markdown(f"**[{it.get('category') or ''}] {it['title']}** — {sug.get('reason') or ''}")
            new_val = sug.get("new_progress")
            pc1, pc2 = st.columns(2)
            if new_val is not None and pc1.button(f"✅ 진행치 {new_val:g}로 반영", key=f"apply_sug_{it['id']}"):
                SUPA.table("okr_items").update({
                    "progress": new_val, "last_checkin_at": date.today().isoformat(),
                }).eq("id", it["id"]).execute()
                st.session_state["pending_okr_suggestions"] = [s for s in st.session_state["pending_okr_suggestions"] if s is not sug]
                st.toast("반영 완료!")
                st.rerun()
            elif new_val is None:
                pc1.caption("숫자 언급이 없어서 자동 반영은 안 했어요.")
            if pc2.button("무시", key=f"dismiss_sug_{it['id']}"):
                st.session_state["pending_okr_suggestions"] = [s for s in st.session_state["pending_okr_suggestions"] if s is not sug]
                st.rerun()

recent_logs = load_activity_log()
if recent_logs:
    with st.expander(f"최근 기록 {len(recent_logs)}건 보기"):
        for lg in recent_logs:
            when = lg["created_at"][:16].replace("T", " ")
            extra = []
            if lg.get("link_url"):
                extra.append(f"[링크]({lg['link_url']})")
            if lg.get("attachment_url"):
                extra.append(f"[첨부파일]({lg['attachment_url']})")
            extra_txt = " · " + " · ".join(extra) if extra else ""
            is_mine = lg["staff_name"] == my_name
            lc1, lc2 = st.columns([5, 1])
            lc1.caption(f"{when} · **{lg['staff_name']}** · {lg['note']}{extra_txt}")
            if lg.get("manager_feedback"):
                st.success(f"💬 대표 피드백: {lg['manager_reaction'] or ''} {lg['manager_feedback']}")
            if is_mine:
                if lc2.button("✏️ 수정", key=f"editlog_{lg['id']}"):
                    st.session_state[f"editing_log_{lg['id']}"] = True
                if st.session_state.get(f"editing_log_{lg['id']}"):
                    with st.form(f"edit_log_form_{lg['id']}"):
                        new_note = st.text_area("내용 수정", value=lg["note"], key=f"editnote_{lg['id']}")
                        new_link = st.text_input("참고 링크", value=lg.get("link_url") or "", key=f"editlink_{lg['id']}")
                        ec1, ec2 = st.columns(2)
                        save_edit = ec1.form_submit_button("💾 저장", type="primary", use_container_width=True)
                        cancel_edit = ec2.form_submit_button("취소", use_container_width=True)
                    if save_edit:
                        SUPA.table("daily_activity_log").update({
                            "note": new_note.strip(), "link_url": new_link.strip() or None,
                        }).eq("id", lg["id"]).execute()
                        st.session_state[f"editing_log_{lg['id']}"] = False
                        refresh()
                    if cancel_edit:
                        st.session_state[f"editing_log_{lg['id']}"] = False
                        st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════
# 📥 구글시트로 일괄 등록
# ══════════════════════════════════════════════════════════
st.subheader("📥 구글시트로 일괄 등록")
st.caption("💡 인플루언서 풀/캐스팅 작업을 직접 다루시는 분(곽재선·이단우 등)은 이걸로 한 번에 올리시고, 그 외 업무는 위 '오늘 빠른 기록'에 자유롭게 쓰시면 AI가 알아서 해석해요.")
st.caption(
    "여러 건을 한 번에 올리고 싶으면, 구글시트 링크를 붙여넣으세요. "
    "시트는 '링크가 있는 모든 사용자 - 뷰어'로 공유 설정만 해두면 됩니다. "
    "지금 쓰시는 작업시트 헤더(Name, SNS_ID, SNS_URL, 방문지점, 방문날짜, 상품, Upload_URL, 조회수, 좋아요수, 저장수, 브랜드사) 그대로 인식돼요. "
    "브랜드사 칸에 여러 브랜드가 콤마로 같이 있으면 브랜드별로 자동으로 나눠서 등록됩니다. Upload_URL이 있으면 상태도 자동으로 '업로드완료'로 잡혀요."
)


def _sheet_xlsx_url(sheet_url):
    if "/spreadsheets/d/" not in sheet_url:
        return None
    sheet_id = sheet_url.split("/spreadsheets/d/")[1].split("/")[0]
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"


def _map_sheet_row(row):
    mapped = {}
    row_index_norm = {}
    for pos, c in enumerate(row.index):
        key = str(c).strip().lower()
        if key not in row_index_norm:  # 같은 이름의 열이 여러 개면 첫 번째 것만 사용
            row_index_norm[key] = pos
    for db_col, aliases_norm in SHEET_COL_MAP_NORM.items():
        for alias_norm in aliases_norm:
            if alias_norm in row_index_norm:
                val = row.iloc[row_index_norm[alias_norm]]  # 위치 기반 조회라 항상 스칼라값 하나만 나옴
                if pd.notna(val) and str(val).strip():
                    mapped[db_col] = str(val).strip()
                    break
    return mapped


gc1, gc2 = st.columns([4, 1])
sheet_url = gc1.text_input("구글시트 링크", placeholder="https://docs.google.com/spreadsheets/d/...", label_visibility="collapsed")
load_clicked = gc2.button("불러오기", use_container_width=True)
default_brand = st.text_input(
    "이 시트 전체에 적용할 기본 브랜드명 (행에 브랜드사 칸이 없으면 이걸로 채워요, 예: 기자단 섹션)",
    placeholder="예: OWM",
)
st.caption("스프레드시트 안에 탭이 여러 개 있어도, 링크 하나만 붙여넣으면 모든 탭을 자동으로 다 읽어옵니다.")

if load_clicked:
    if not sheet_url.strip():
        st.error("링크를 붙여넣어주세요.")
    else:
        xlsx_url = _sheet_xlsx_url(sheet_url.strip())
        if not xlsx_url:
            st.error("구글시트 링크 형식이 아닌 것 같아요. 시트를 열어서 주소창의 링크를 그대로 복사해주세요.")
        else:
            try:
                res = requests.get(xlsx_url, timeout=30)
                if res.status_code != 200:
                    raise ValueError(f"응답 코드 {res.status_code}")
                all_sheets = pd.read_excel(io.BytesIO(res.content), sheet_name=None, header=None, dtype=str)
                raw_rows = []
                sections_found = 0
                for sheet_name, raw_df in all_sheets.items():
                    if raw_df.empty:
                        continue
                    sections_found += len(_find_header_rows(raw_df))
                    for r in _parse_multi_section_sheet(raw_df):
                        r["_source_tab"] = sheet_name
                        raw_rows.append(r)
                if not raw_rows:
                    st.warning("인플루언서명(이름/Name/아이디 이름 등)을 인식하지 못했습니다. 시트 헤더 이름을 확인해주세요.")
                # 브랜드사가 없는 행(예: 기자단 섹션)은 기본 브랜드명으로 채움
                for r in raw_rows:
                    if not r.get("brand_name"):
                        r["brand_name"] = default_brand.strip() or "미지정"
                # 브랜드사 칸에 "닥터리엔장,텔로엑트,옵티팜" 처럼 여러 브랜드가 콤마로 같이 들어있으면
                # 브랜드별로 한 건씩 쪼개서 저장한다 (업체별 배치 현황을 정확히 보기 위함)
                rows = []
                for r in raw_rows:
                    brand_field = r["brand_name"]
                    brand_list = [b.strip("() ") for b in brand_field.replace("、", ",").split(",") if b.strip("() ")]
                    for b in (brand_list or [brand_field]):
                        row_copy = dict(r)
                        row_copy["brand_name"] = b
                        rows.append(row_copy)
                st.session_state["sheet_rows_preview"] = rows
                st.success(f"탭 {len(all_sheets)}개 · 섹션 {sections_found}개에서 {len(rows)}건 인식됨. 아래에서 확인 후 등록하세요.")
            except Exception as e:
                st.error(
                    f"시트를 못 읽었어요 ({e}). 구글시트가 '링크가 있는 모든 사용자 - 뷰어'로 공유되어 있는지 확인해주세요."
                )

preview_rows = st.session_state.get("sheet_rows_preview")
if preview_rows:
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)
    if st.button(f"✅ 이 {len(preview_rows)}건 일괄 등록", type="primary"):
        for r in preview_rows:
            content_link = r.get("content_link")
            payload = {
                "brand_name": r.get("brand_name"), "influencer_name": r.get("influencer_name"),
                "category": r.get("category") if r.get("category") in CATEGORY_OPTS else "기타",
                "content_type": r.get("content_type") if r.get("content_type") in CONTENT_TYPE_OPTS else "기타",
                "agency_name": r.get("agency_name"),
                "sns_id": r.get("sns_id"), "sns_url": r.get("sns_url"),
                "product_name": r.get("product_name"), "visit_location": r.get("visit_location"),
                "visit_date": _clean_date(r.get("visit_date")),
                "scheduled_date": _clean_date(r.get("scheduled_date")),
                "unit_price": _clean_number(r.get("unit_price")),
                "views": _clean_number(r.get("views")), "likes": _clean_number(r.get("likes")),
                "saves": _clean_number(r.get("saves")), "followers": _clean_number(r.get("followers")),
                "email": r.get("email"), "address": r.get("address"),
                "shipping_address": r.get("shipping_address"), "phone": r.get("phone"),
                "casting_assigned_to": r.get("casting_assigned_to"),
                "guideline_link": r.get("guideline_link"),
                "content_link": content_link,
                "status": "업로드완료" if content_link else "섭외중",
                "actual_upload_date": date.today().isoformat() if content_link else None,
                "notes": r.get("notes"),
                "assigned_to": my_name,
            }
            # 콘텐츠 링크는 진짜 고유값이라, 같은 링크+브랜드 조합이 이미 있으면 새로 만들지 않고 덮어씀
            # (담당자가 구글시트에서 계속 작업하다 몇 번을 다시 업로드해도 안전하게 최신 값으로 갱신됨)
            if payload.get("content_link"):
                SUPA.table("influencer_placements").upsert(
                    payload, on_conflict="content_link,brand_name"
                ).execute()
            else:
                SUPA.table("influencer_placements").insert(payload).execute()
        st.session_state.pop("sheet_rows_preview", None)
        st.success(f"{len(preview_rows)}건 등록 완료!")
        refresh()

st.divider()

# ══════════════════════════════════════════════════════════
# ➕ 새 배치 등록 (개별, 계약서 첨부 포함)
# ══════════════════════════════════════════════════════════
with st.expander("➕ 새 배치 등록 (업체·인플루언서가 정해졌을 때)"):
    with st.form("new_placement_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        brand_name = c1.text_input("브랜드명 *")
        influencer_name = c2.text_input("인플루언서명 *")

        c3, c4, c5 = st.columns(3)
        category = c3.selectbox("카테고리", CATEGORY_OPTS)
        content_type = c4.selectbox("콘텐츠 유형", CONTENT_TYPE_OPTS)
        agency_name = c5.text_input("대행사(있으면)")

        c6, c7, c8 = st.columns(3)
        scheduled_date = c6.date_input("예정일", value=None)
        unit_price = c7.number_input("단가(있으면)", min_value=0, step=10000, format="%d")
        casting_assigned_to = c8.text_input("섭외 지시 대상", placeholder="예: 사누바리, 현지 staff 이름")

        guideline_link = st.text_input("가이드라인 링크(있으면)", placeholder="브리핑/가이드라인 문서 URL")
        contract_file = st.file_uploader("업체 계약서 최종본 첨부(있으면)", type=["pdf", "docx", "png", "jpg"])
        notes = st.text_area("메모")
        submitted = st.form_submit_button("등록", type="primary", use_container_width=True)

    if submitted:
        if not brand_name.strip() or not influencer_name.strip():
            st.error("브랜드명과 인플루언서명은 꼭 입력해주세요.")
        else:
            contract_url = None
            if contract_file is not None:
                try:
                    path = f"{brand_name.strip()}/{int(date.today().strftime('%Y%m%d'))}_{contract_file.name}"
                    SUPA.storage.from_("contract-files").upload(
                        path, contract_file.getvalue(),
                        {"content-type": contract_file.type or "application/octet-stream"},
                    )
                    base = os.environ.get("SUPABASE_URL")
                    contract_url = f"{base}/storage/v1/object/public/contract-files/{path}"
                except Exception as e:
                    st.warning(f"계약서 업로드는 실패했지만 나머지 내용은 등록할게요 ({e})")

            SUPA.table("influencer_placements").insert({
                "brand_name": brand_name.strip(), "influencer_name": influencer_name.strip(),
                "category": category, "content_type": content_type,
                "agency_name": agency_name.strip() or None,
                "scheduled_date": scheduled_date.isoformat() if scheduled_date else None,
                "unit_price": unit_price or None,
                "casting_assigned_to": casting_assigned_to.strip() or None,
                "guideline_link": guideline_link.strip() or None,
                "contract_file_url": contract_url,
                "assigned_to": my_name, "notes": notes.strip() or None,
            }).execute()
            st.success("등록 완료!")
            refresh()

st.divider()

# ══════════════════════════════════════════════════════════
# 📋 업체별 진행 현황
# ══════════════════════════════════════════════════════════
st.subheader("📋 업체별 진행 현황")
fc1, fc2 = st.columns(2)
show_all = fc1.checkbox("전체 담당자 보기 (기본: 내 담당만)", value=False)
show_done = fc2.checkbox("완료/취소 건도 보기", value=False)

placements = load_placements()
items = placements if show_all else [p for p in placements if p["assigned_to"] == my_name]
if not show_done:
    items = [p for p in items if p["status"] not in ("드롭앤고체크완료", "취소")]

st.caption(f"{len(items)}건")

view_mode = st.radio("보기 방식", ["📊 표로 한눈에 보기", "🗂️ 카드로 자세히 보기"], horizontal=True, key="placements_view_mode")

if view_mode == "📊 표로 한눈에 보기":
    if not items:
        st.caption("표시할 항목이 없습니다.")
    else:
        table_df = pd.DataFrame([{
            "id": p["id"], "브랜드": p["brand_name"], "인플루언서": p["influencer_name"],
            "카테고리": p.get("category") or "", "유형": p.get("content_type") or "",
            "상태": p["status"], "콘텐츠 링크": p.get("content_link") or "",
            "담당": p.get("assigned_to") or "", "예정일": p.get("scheduled_date") or "",
        } for p in items])
        edited_table = st.data_editor(
            table_df,
            column_config={
                "id": None,
                "상태": st.column_config.SelectboxColumn(options=STATUS_OPTS, width="small"),
                "콘텐츠 링크": st.column_config.TextColumn(width="medium"),
                "브랜드": st.column_config.TextColumn(disabled=True),
                "인플루언서": st.column_config.TextColumn(disabled=True),
                "카테고리": st.column_config.TextColumn(disabled=True, width="small"),
                "유형": st.column_config.TextColumn(disabled=True, width="small"),
                "담당": st.column_config.TextColumn(disabled=True, width="small"),
                "예정일": st.column_config.TextColumn(disabled=True, width="small"),
            },
            hide_index=True, use_container_width=True, key="placements_table_editor",
        )
        if st.button("💾 표에서 바뀐 상태/링크 저장", type="primary"):
            by_id = {p["id"]: p for p in items}
            changed = 0
            for _, row in edited_table.iterrows():
                orig = by_id.get(row["id"])
                if not orig:
                    continue
                new_status = row["상태"]
                new_link = row["콘텐츠 링크"] or None
                if new_status != orig["status"] or new_link != (orig.get("content_link") or None):
                    update_payload = {"status": new_status, "content_link": new_link}
                    if new_status == "업로드완료" and not orig.get("actual_upload_date"):
                        update_payload["actual_upload_date"] = date.today().isoformat()
                    SUPA.table("influencer_placements").update(update_payload).eq("id", row["id"]).execute()
                    changed += 1
            st.success(f"{changed}건 저장 완료" if changed else "바뀐 내용이 없습니다.")
            if changed:
                refresh()
        st.caption("자세한 정보(가이드라인/성과지표/발송정보 등)를 보거나 고치려면 '카드로 자세히 보기'를 사용하세요.")

else:
    brands = sorted(set(p["brand_name"] for p in items))
    for brand in brands:
        brand_items = [p for p in items if p["brand_name"] == brand]
        with st.expander(f"🏢 **{brand}** ({len(brand_items)}건)", expanded=False):
            for p in brand_items:
                with st.container(border=True):
                    emoji = STATUS_EMOJI.get(p["status"], "⚪")
                    sns = f" (@{p['sns_id']})" if p.get("sns_id") else ""
                    st.markdown(f"**{p['influencer_name']}**{sns} · {p.get('category') or ''} · {p.get('content_type') or ''}  {emoji} {p['status']}")
                    meta = []
                    if p.get("product_name"):
                        meta.append(f"상품: {p['product_name']}")
                    if p.get("visit_location"):
                        meta.append(f"방문지점: {p['visit_location']}")
                    if p.get("visit_date"):
                        meta.append(f"방문일: {p['visit_date']}")
                    if p.get("agency_name"):
                        meta.append(f"대행사: {p['agency_name']}")
                    if p.get("assigned_to"):
                        meta.append(f"담당: {p['assigned_to']}")
                    if p.get("casting_assigned_to"):
                        meta.append(f"섭외지시: {p['casting_assigned_to']}")
                    if p.get("scheduled_date"):
                        meta.append(f"예정일: {p['scheduled_date']}")
                    if meta:
                        st.caption(" · ".join(meta))
                    if any(p.get(k) for k in ("views", "likes", "saves")):
                        st.caption(f"📈 조회수 {p.get('views') or 0:,} · 좋아요 {p.get('likes') or 0:,} · 저장 {p.get('saves') or 0:,}")
                    if p.get("followers"):
                        st.caption(f"👥 팔로워 {p['followers']:,}")
                    if p.get("shipping_address") or p.get("phone"):
                        st.caption(f"📦 발송: {p.get('shipping_address') or ''} {p.get('phone') or ''}")
                    if p.get("sns_url"):
                        st.caption(f"🔗 SNS: {p['sns_url']}")
                    if p.get("guideline_link"):
                        st.caption(f"📎 가이드라인: {p['guideline_link']}")
                    if p.get("contract_file_url"):
                        st.caption(f"📄 계약서: {p['contract_file_url']}")
                    if p.get("notes"):
                        st.caption(f"메모: {p['notes']}")

                    cc1, cc2, cc3 = st.columns([1.1, 1.1, 2.3])
                    new_status = cc1.selectbox(
                        "상태", STATUS_OPTS, index=STATUS_OPTS.index(p["status"]) if p["status"] in STATUS_OPTS else 0,
                        key=f"status_{p['id']}", label_visibility="collapsed",
                    )
                    cur_guideline_label = BOOL_TO_GUIDELINE.get(p.get("guideline_ok"), "미확인")
                    new_guideline_label = cc2.selectbox(
                        "가이드라인", GUIDELINE_OPTS, index=GUIDELINE_OPTS.index(cur_guideline_label),
                        key=f"guideline_{p['id']}", label_visibility="collapsed",
                    )
                    new_link = cc3.text_input(
                        "콘텐츠 링크", value=p.get("content_link") or "", placeholder="업로드된 콘텐츠 링크(=성과보고 링크)",
                        key=f"link_{p['id']}", label_visibility="collapsed",
                    )
                    if st.button("저장", key=f"save_{p['id']}", use_container_width=True):
                        update_payload = {
                            "status": new_status, "content_link": new_link or None,
                            "guideline_ok": GUIDELINE_TO_BOOL[new_guideline_label],
                        }
                        if new_status == "업로드완료" and not p.get("actual_upload_date"):
                            update_payload["actual_upload_date"] = date.today().isoformat()
                        SUPA.table("influencer_placements").update(update_payload).eq("id", p["id"]).execute()
                        st.success("저장 완료")
                        refresh()

st.divider()

# ══════════════════════════════════════════════════════════
# 📢 예정입출금 신고 (구 12_지출예정보고 통합)
# ══════════════════════════════════════════════════════════
st.subheader("📢 예정입출금 신고")
st.caption("\"이런 돈이 곧 나갈/들어올 것 같다\" 싶은 게 있으면 짧게 남겨주세요. 재무캘린더 대시보드에 바로 반영돼요.")

with st.form("cash_forecast_form", clear_on_submit=True):
    fcc1, fcc2, fcc3 = st.columns(3)
    direction_label = fcc1.radio("구분", ["지출 예정", "수입 예정"], horizontal=True)
    fc_amount = fcc2.number_input("예상 금액", min_value=0, step=10000, format="%d")
    fc_date = fcc3.date_input("예상 날짜", value=date.today())
    fc_reason = st.text_area("무슨 건인지 짧게 적어주세요", placeholder="예: OO브랜드 8월 캠페인 잔금")
    fc_submitted = st.form_submit_button("📝 등록하기", type="primary", use_container_width=True)

if fc_submitted:
    if fc_amount <= 0:
        st.error("금액을 입력해주세요.")
    elif not fc_reason.strip():
        st.error("무슨 건인지 간단히 적어주세요.")
    else:
        SUPA.table("fin_cash_forecasts").insert({
            "direction": "out" if direction_label == "지출 예정" else "in",
            "amount": fc_amount, "expected_date": fc_date.isoformat(),
            "reason": fc_reason.strip(), "submitted_by": my_name, "status": "open",
        }).execute()
        st.success("등록 완료!")
        refresh()

recent_fc = load_forecasts()
if recent_fc:
    with st.expander(f"최근 신고 {len(recent_fc)}건 보기"):
        for f in recent_fc:
            status_label = {"open": "🟡 대기중", "resolved": "✅ 처리완료", "dismissed": "🗑️ 취소됨"}.get(f["status"], f["status"])
            direction_kr = "지출" if f["direction"] == "out" else "수입"
            st.caption(f"{f['expected_date']} · {direction_kr} · ₩{float(f['amount']):,.0f} · {status_label} · {f.get('submitted_by') or ''} · {f.get('reason') or ''}")

st.divider()

# ══════════════════════════════════════════════════════════
# 📇 B2B 브랜드 관리 (세일즈) — 캘린더·계정·이슈·캠페인 주차루틴
# ══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
# 🧰 내 업무 도구 (역할별로 다른 화면이 뜹니다 — 다른 사람 도구는 안 보여요)
# ══════════════════════════════════════════════════════════
st.subheader("🧰 내 업무 도구")

ROLE_MAP = {"김선재": "sales", "곽재선": "influencer", "구정회": "dev", "이단우": "china_ops"}
my_role = ROLE_MAP.get(my_name)

if my_role == "sales":
    st.subheader("📇 B2B 브랜드 관리 (세일즈)")
    st.caption("업체별 일정·이슈·캠페인을 관리하는 세일즈 전용 공간입니다. 브랜드 B2B 관리가 핵심 업무인 분(김선재 등)이 주로 쓰시면 되고, 다른 분들은 안 쓰셔도 됩니다.")

    WEEK_TEMPLATE = [
        (1, "실행 및 가이드", "인플루언서 리스트 제안·전달, 매장 방문 진행, 콘텐츠 가이드라인 배포, 선물 제공 소통 후 가이드 전달"),
        (2, "중간 리포팅", "1주차 방문·업로드 활동 1차 보고, 차주 운영·실행 계획 공유"),
        (3, "성과 입증 및 세일즈", "업로드 활동 최종 보고, 초과 성과 어필, 재계약 당위성 전달, 익월 견적서 발송"),
        (4, "마감 및 차월 준비", "월별 마감 PT, 다음달 계약 확정·입금 진행, 에이전시 대상 스탠바이 요청"),
    ]


    @st.cache_data(ttl=20)
    def load_sales_accounts():
        return SUPA.table("sales_accounts").select("*").order("brand_name").execute().data


    @st.cache_data(ttl=20)
    def load_sales_issues():
        return SUPA.table("sales_issues").select("*").order("created_at", desc=True).execute().data


    @st.cache_data(ttl=20)
    def load_sales_campaigns():
        return SUPA.table("sales_campaigns").select("*").order("open_date", desc=True).execute().data


    @st.cache_data(ttl=20)
    def load_sales_campaign_tasks():
        return SUPA.table("sales_campaign_tasks").select("*").order("due_date").execute().data


    def refresh_sales():
        load_sales_accounts.clear(); load_sales_issues.clear()
        load_sales_campaigns.clear(); load_sales_campaign_tasks.clear()
        st.rerun()


    sales_show_all = st.checkbox("전체 담당자 보기 (기본: 내 담당만)", value=False, key="sales_show_all")
    all_sales_accounts = load_sales_accounts()
    my_accounts = all_sales_accounts if sales_show_all else [a for a in all_sales_accounts if a["assigned_to"] == my_name]
    account_by_id = {a["id"]: a for a in all_sales_accounts}
    STATUS_OPTS_ACC = ["협상중", "계약완료", "운영중", "종료", "이탈"]

    tab_cal, tab_acc, tab_issue, tab_camp = st.tabs(["📅 일정 한눈에보기", "🏢 계정 관리", "🐛 이슈", "🚀 캠페인·주차루틴"])

    # ── 📅 일정 한눈에보기 ──────────────────────────────────
    with tab_cal:
        st.markdown("**다가오는 일정**")
        all_tasks = load_sales_campaign_tasks()
        all_campaigns_map = {c["id"]: c for c in load_sales_campaigns()}
        my_account_ids = {a["id"] for a in my_accounts}

        cal_rows = []
        for a in my_accounts:
            if a.get("renewal_date"):
                cal_rows.append({"날짜": a["renewal_date"], "종류": "🔁 갱신/온보딩", "내용": f"{a['brand_name']} 갱신일", "브랜드": a["brand_name"]})
        for t in all_tasks:
            camp = all_campaigns_map.get(t["campaign_id"])
            if not camp or camp["account_id"] not in my_account_ids or t["status"] == "완료" or not t.get("due_date"):
                continue
            acc = account_by_id.get(camp["account_id"], {})
            cal_rows.append({"날짜": t["due_date"], "종류": f"📌 {t['week_number']}주차: {t['task_title']}", "내용": camp["campaign_name"], "브랜드": acc.get("brand_name", "?")})

        if not cal_rows:
            st.caption("예정된 일정이 없습니다.")
        else:
            cal_df = pd.DataFrame(sorted(cal_rows, key=lambda r: r["날짜"]))
            st.dataframe(cal_df[["날짜", "브랜드", "종류", "내용"]], hide_index=True, use_container_width=True)

    # ── 🏢 계정 관리 ────────────────────────────────────────
    with tab_acc:
        st.markdown("**담당 브랜드 계정**")
        with st.expander("➕ 새 브랜드 계정 등록"):
            with st.form("new_account_form", clear_on_submit=True):
                nac1, nac2 = st.columns(2)
                new_brand = nac1.text_input("브랜드명 *")
                new_status = nac2.selectbox("상태", STATUS_OPTS_ACC, index=2)
                nac3, nac4 = st.columns(2)
                new_contact_name = nac3.text_input("담당자 이름")
                new_contact_email = nac4.text_input("담당자 이메일")
                nac5, nac6, nac7 = st.columns(3)
                new_budget = nac5.number_input("월 예산", min_value=0, step=100000, format="%d")
                new_contract_start = nac6.date_input("계약 시작일", value=None)
                new_renewal = nac7.date_input("다음 갱신/온보딩일", value=None)
                new_notes = st.text_area("메모")
                acc_submitted = st.form_submit_button("등록", type="primary")
            if acc_submitted:
                if not new_brand.strip():
                    st.error("브랜드명을 입력해주세요.")
                else:
                    SUPA.table("sales_accounts").insert({
                        "brand_name": new_brand.strip(), "assigned_to": my_name, "status": new_status,
                        "contact_name": new_contact_name.strip() or None, "contact_email": new_contact_email.strip() or None,
                        "monthly_budget": new_budget or None,
                        "contract_start": new_contract_start.isoformat() if new_contract_start else None,
                        "renewal_date": new_renewal.isoformat() if new_renewal else None,
                        "notes": new_notes.strip() or None,
                    }).execute()
                    st.success("등록 완료!")
                    refresh_sales()

        if not my_accounts:
            st.caption("등록된 계정이 없습니다.")
        for a in my_accounts:
            with st.container(border=True):
                sat = "⭐" * (a.get("satisfaction_score") or 0)
                st.markdown(f"**🏢 {a['brand_name']}** · {a['status']} · 담당 {a['assigned_to']} {sat}")
                meta = []
                if a.get("contact_name"):
                    meta.append(f"담당자: {a['contact_name']}")
                if a.get("monthly_budget"):
                    meta.append(f"월예산: ₩{float(a['monthly_budget']):,.0f}")
                if a.get("renewal_date"):
                    meta.append(f"다음 갱신: {a['renewal_date']}")
                if meta:
                    st.caption(" · ".join(meta))
                if a.get("notes"):
                    st.caption(f"메모: {a['notes']}")
                with st.expander("✏️ 수정"):
                    ec1, ec2 = st.columns(2)
                    e_status = ec1.selectbox("상태", STATUS_OPTS_ACC, index=STATUS_OPTS_ACC.index(a["status"]), key=f"accstatus_{a['id']}")
                    e_sat = ec2.slider("만족도(1~5)", 1, 5, value=a.get("satisfaction_score") or 3, key=f"accsat_{a['id']}")
                    e_renewal = st.date_input(
                        "다음 갱신/온보딩일",
                        value=pd.to_datetime(a["renewal_date"]).date() if a.get("renewal_date") else None,
                        key=f"accrenew_{a['id']}",
                    )
                    e_notes = st.text_area("메모", value=a.get("notes") or "", key=f"accnotes_{a['id']}")
                    if st.button("저장", key=f"accsave_{a['id']}"):
                        SUPA.table("sales_accounts").update({
                            "status": e_status, "satisfaction_score": e_sat,
                            "renewal_date": e_renewal.isoformat() if e_renewal else None,
                            "notes": e_notes.strip() or None,
                            "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
                        }).eq("id", a["id"]).execute()
                        st.success("저장 완료"); refresh_sales()

    # ── 🐛 이슈 ────────────────────────────────────────────
    with tab_issue:
        st.markdown("**이슈 등록/관리**")
        if not my_accounts:
            st.caption("먼저 브랜드 계정을 등록해주세요.")
        else:
            with st.expander("➕ 새 이슈 등록"):
                with st.form("new_issue_form", clear_on_submit=True):
                    acc_names = {a["brand_name"]: a["id"] for a in my_accounts}
                    sel_brand = st.selectbox("브랜드", list(acc_names.keys()), key="issue_brand_pick")
                    ic1, ic2 = st.columns(2)
                    issue_title = ic1.text_input("이슈 제목 *")
                    issue_priority = ic2.selectbox("우선순위", ["긴급", "높음", "보통", "낮음"], index=2)
                    issue_desc = st.text_area("상세 내용")
                    issue_submitted = st.form_submit_button("등록", type="primary")
                if issue_submitted:
                    if not issue_title.strip():
                        st.error("제목을 입력해주세요.")
                    else:
                        SUPA.table("sales_issues").insert({
                            "account_id": acc_names[sel_brand], "title": issue_title.strip(),
                            "description": issue_desc.strip() or None, "priority": issue_priority,
                            "created_by": my_name,
                        }).execute()
                        st.success("등록 완료!"); refresh_sales()

            my_account_ids_issue = {a["id"] for a in my_accounts}
            sales_issues_all = [i for i in load_sales_issues() if i["account_id"] in my_account_ids_issue]
            show_resolved_issues = st.checkbox("해결된 이슈도 보기", value=False, key="show_resolved_issues")
            if not show_resolved_issues:
                sales_issues_all = [i for i in sales_issues_all if i["status"] != "해결됨"]
            PRIORITY_EMOJI = {"긴급": "🔴", "높음": "🟠", "보통": "🟡", "낮음": "🟢"}
            if not sales_issues_all:
                st.caption("등록된 이슈가 없습니다.")
            for i in sales_issues_all:
                acc = account_by_id.get(i["account_id"], {})
                with st.container(border=True):
                    st.markdown(f"{PRIORITY_EMOJI.get(i['priority'], '⚪')} **[{acc.get('brand_name', '?')}] {i['title']}** · {i['status']}")
                    if i.get("description"):
                        st.caption(i["description"])
                    new_issue_status = st.selectbox(
                        "상태", ["열림", "진행중", "해결됨"], index=["열림", "진행중", "해결됨"].index(i["status"]),
                        key=f"issuestatus_{i['id']}", label_visibility="collapsed",
                    )
                    if st.button("저장", key=f"issuesave_{i['id']}"):
                        update_payload = {"status": new_issue_status}
                        if new_issue_status == "해결됨":
                            update_payload["resolved_at"] = pd.Timestamp.now(tz="UTC").isoformat()
                        SUPA.table("sales_issues").update(update_payload).eq("id", i["id"]).execute()
                        st.success("저장 완료"); refresh_sales()

    # ── 🚀 캠페인·주차루틴 ──────────────────────────────────
    with tab_camp:
        st.markdown("**캠페인 등록 → 4주 루틴 자동 생성**")
        if not my_accounts:
            st.caption("먼저 브랜드 계정을 등록해주세요.")
        else:
            with st.expander("🚀 새 캠페인 등록", expanded=True):
                with st.form("new_campaign_form", clear_on_submit=True):
                    acc_names2 = {a["brand_name"]: a["id"] for a in my_accounts}
                    camp_brand = st.selectbox("브랜드", list(acc_names2.keys()), key="camp_brand_pick")
                    camp_name = st.text_input("캠페인명 *", placeholder="예: 9월 명동 오픈 캠페인")
                    camp_open_date = st.date_input("캠페인 오픈일", value=date.today(), key="camp_open_date")
                    camp_submitted = st.form_submit_button("등록 (4주 루틴 자동 생성)", type="primary")
                if camp_submitted:
                    if not camp_name.strip():
                        st.error("캠페인명을 입력해주세요.")
                    else:
                        camp_res = SUPA.table("sales_campaigns").insert({
                            "account_id": acc_names2[camp_brand], "campaign_name": camp_name.strip(),
                            "open_date": camp_open_date.isoformat(), "created_by": my_name,
                        }).execute()
                        new_camp_id = camp_res.data[0]["id"]
                        week_tasks = [{
                            "campaign_id": new_camp_id, "week_number": wn, "task_title": wt,
                            "task_description": wd, "due_date": (camp_open_date + timedelta(days=(wn - 1) * 7)).isoformat(),
                        } for wn, wt, wd in WEEK_TEMPLATE]
                        SUPA.table("sales_campaign_tasks").insert(week_tasks).execute()
                        st.success(f"캠페인 등록 완료! 1~4주차 루틴 {len(week_tasks)}개가 자동으로 만들어졌어요.")
                        refresh_sales()

            my_account_ids_camp = {a["id"] for a in my_accounts}
            my_campaigns = [c for c in load_sales_campaigns() if c["account_id"] in my_account_ids_camp]
            if not my_campaigns:
                st.caption("등록된 캠페인이 없습니다.")
            for c in my_campaigns:
                acc = account_by_id.get(c["account_id"], {})
                with st.expander(f"🚀 [{acc.get('brand_name', '?')}] {c['campaign_name']} · 오픈 {c['open_date']} · {c['status']}"):
                    tasks = [t for t in load_sales_campaign_tasks() if t["campaign_id"] == c["id"]]
                    for t in sorted(tasks, key=lambda x: x["week_number"]):
                        with st.container(border=True):
                            st.markdown(f"**{t['week_number']}주차 — {t['task_title']}** · 마감 {t.get('due_date') or '-'}")
                            if t.get("task_description"):
                                st.caption(t["task_description"])
                            new_tstatus = st.selectbox(
                                "상태", ["예정", "진행중", "완료"], index=["예정", "진행중", "완료"].index(t["status"]),
                                key=f"wtstatus_{t['id']}", label_visibility="collapsed",
                            )
                            if st.button("저장", key=f"wtsave_{t['id']}"):
                                SUPA.table("sales_campaign_tasks").update({"status": new_tstatus}).eq("id", t["id"]).execute()
                                st.success("저장 완료"); refresh_sales()
elif my_role == "dev":
    st.markdown("**💻 개발 업무 관리** — 백로그 → 진행중 → 리뷰 → 완료 (칸반 방식)")
    st.caption("전세계 개발팀이 가장 많이 쓰는 방식이에요. 카드를 만들고 상태만 옮기면 됩니다.")
    with st.expander("📚 참고: 왜 칸반 방식인가?"):
        st.caption(
            "전세계 개발팀(구글·MS 등)이 가장 많이 쓰는 방식이에요. 핵심은 '진행중' 칸에 너무 많은 카드를 "
            "동시에 두지 않는 것(WIP 제한) — 한 번에 몇 개만 집중해서 끝내는 게 여러 개를 동시에 벌리는 것보다 빠릅니다."
        )

    @st.cache_data(ttl=20)
    def load_dev_tasks():
        return SUPA.table("dev_tasks").select("*").eq("person", my_name).order("created_at", desc=True).execute().data

    def refresh_dev():
        load_dev_tasks.clear(); st.rerun()

    with st.expander("➕ 새 작업 카드 추가"):
        with st.form("new_dev_task_form", clear_on_submit=True):
            dc1, dc2 = st.columns(2)
            dev_title = dc1.text_input("작업 제목 *")
            dev_priority = dc2.selectbox("우선순위", ["긴급", "높음", "보통", "낮음"], index=2)
            dev_desc = st.text_area("설명(선택)")
            dev_submitted = st.form_submit_button("추가", type="primary")
        if dev_submitted:
            if not dev_title.strip():
                st.error("제목을 입력해주세요.")
            else:
                SUPA.table("dev_tasks").insert({
                    "person": my_name, "title": dev_title.strip(),
                    "description": dev_desc.strip() or None, "priority": dev_priority,
                }).execute()
                st.success("추가 완료!"); refresh_dev()

    dev_tasks_all = load_dev_tasks()
    DEV_STATUS_COLS = ["백로그", "진행중", "리뷰", "완료"]
    kb_cols = st.columns(4)
    for kcol, kstatus in zip(kb_cols, DEV_STATUS_COLS):
        with kcol:
            st.markdown(f"**{kstatus}** ({sum(1 for t in dev_tasks_all if t['status'] == kstatus)})")
            for t in [t for t in dev_tasks_all if t["status"] == kstatus]:
                with st.container(border=True):
                    pr_emoji = {"긴급": "🔴", "높음": "🟠", "보통": "🟡", "낮음": "🟢"}.get(t["priority"], "⚪")
                    signed = " ✅" if t.get("admin_signed") else ""
                    st.markdown(f"{pr_emoji} **{t['title']}**{signed}")
                    if t.get("description"):
                        st.caption(t["description"])
                    new_dev_status = st.selectbox(
                        "상태", DEV_STATUS_COLS, index=DEV_STATUS_COLS.index(t["status"]),
                        key=f"devstatus_{t['id']}", label_visibility="collapsed",
                    )
                    if new_dev_status != t["status"]:
                        SUPA.table("dev_tasks").update({
                            "status": new_dev_status, "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
                        }).eq("id", t["id"]).execute()
                        refresh_dev()

elif my_role == "influencer":
    st.markdown("**🌟 인플루언서 파트너십 관리**")
    st.caption("인플루언서 마케터들이 흔히 쓰는 방식 — 티어(나노/마이크로/미드/메가)별로 관계 상태를 관리합니다.")
    with st.expander("📚 참고: 왜 '관계 상태'로 관리하나?"):
        st.caption(
            "인플루언서 마케팅은 1회성 거래가 아니라 '관계'가 핵심이에요. 신규 발굴만큼 중요한 게 "
            "이미 협업한 사람과의 재협업률(관계 유지)입니다 — 그래서 단순 리스트가 아니라 신규/협상중/활성/휴면 "
            "단계로 관리하는 게 표준 CRM 방식입니다."
        )

    @st.cache_data(ttl=20)
    def load_influencer_pool():
        return SUPA.table("influencer_pool").select("*").eq("assigned_to", my_name).order("name").execute().data

    def refresh_pool():
        load_influencer_pool.clear(); st.rerun()

    with st.expander("➕ 새 인플루언서 추가"):
        with st.form("new_pool_form", clear_on_submit=True):
            pc1, pc2 = st.columns(2)
            pool_name = pc1.text_input("이름/계정 *")
            pool_tier = pc2.selectbox("티어", ["나노", "마이크로", "미드", "메가"])
            pc3, pc4, pc5 = st.columns(3)
            pool_platform = pc3.text_input("플랫폼", placeholder="인스타/틱톡/샤오홍슈 등")
            pool_followers = pc4.number_input("팔로워수", min_value=0, step=1000, format="%d")
            pool_rate = pc5.number_input("단가(있으면)", min_value=0, step=10000, format="%d")
            pool_notes = st.text_area("메모")
            pool_submitted = st.form_submit_button("추가", type="primary")
        if pool_submitted:
            if not pool_name.strip():
                st.error("이름을 입력해주세요.")
            else:
                SUPA.table("influencer_pool").insert({
                    "name": pool_name.strip(), "tier": pool_tier, "platform": pool_platform.strip() or None,
                    "followers": pool_followers or None, "rate": pool_rate or None,
                    "assigned_to": my_name, "notes": pool_notes.strip() or None,
                }).execute()
                st.success("추가 완료!"); refresh_pool()

    pool_all = load_influencer_pool()
    pool_filter_status = st.multiselect(
        "관계 상태 필터", ["신규", "협상중", "활성", "휴면"], default=["신규", "협상중", "활성"], key="pool_status_filter",
    )
    pool_view = [p for p in pool_all if p["relationship_status"] in pool_filter_status]
    st.caption(f"{len(pool_view)}명")
    for p in pool_view:
        with st.container(border=True):
            st.markdown(f"**{p['name']}** · {p.get('tier') or ''} · {p.get('platform') or ''} · 팔로워 {p.get('followers') or 0:,}")
            meta = []
            if p.get("rate"):
                meta.append(f"단가: ₩{float(p['rate']):,.0f}")
            if p.get("last_collab_date"):
                meta.append(f"최근 협업: {p['last_collab_date']}")
            if meta:
                st.caption(" · ".join(meta))
            cc1, cc2, cc3 = st.columns([1.3, 1.3, 1])
            new_rel = cc1.selectbox(
                "관계 상태", ["신규", "협상중", "활성", "휴면"],
                index=["신규", "협상중", "활성", "휴면"].index(p["relationship_status"]),
                key=f"poolrel_{p['id']}", label_visibility="collapsed",
            )
            new_last_collab = cc2.date_input(
                "최근 협업일", value=pd.to_datetime(p["last_collab_date"]).date() if p.get("last_collab_date") else None,
                key=f"poollast_{p['id']}", label_visibility="collapsed",
            )
            if cc3.button("저장", key=f"poolsave_{p['id']}", use_container_width=True):
                SUPA.table("influencer_pool").update({
                    "relationship_status": new_rel,
                    "last_collab_date": new_last_collab.isoformat() if new_last_collab else None,
                    "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
                }).eq("id", p["id"]).execute()
                st.success("저장 완료"); refresh_pool()

    if pool_all:
        tier_counts = {}
        for p in pool_all:
            tier_counts[p.get("tier") or "미분류"] = tier_counts.get(p.get("tier") or "미분류", 0) + 1
        st.markdown("**티어별 풀 현황**")
        st.bar_chart(pd.Series(tier_counts))

elif my_role == "china_ops":
    st.markdown("**🇨🇳 중국 마케팅 운영**")
    st.caption("알바 캐스팅 퍼널 — 지원 → 웨비나초대 → 테스트완료 → 채용 → 활성 단계로 관리합니다.")

    @st.cache_data(ttl=20)
    def load_casting_funnel():
        return SUPA.table("casting_funnel").select("*").eq("assigned_to", my_name).order("created_at", desc=True).execute().data

    def refresh_funnel():
        load_casting_funnel.clear(); st.rerun()

    with st.expander("➕ 새 지원자 추가"):
        with st.form("new_funnel_form", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            funnel_name = fc1.text_input("이름 *")
            funnel_stage = fc2.selectbox("단계", ["지원", "웨비나초대", "테스트완료", "채용", "활성", "탈락"])
            funnel_rate = st.number_input("테스트 결과(시간당 발굴 수 등, 선택)", min_value=0.0, step=1.0)
            funnel_notes = st.text_area("메모")
            funnel_submitted = st.form_submit_button("추가", type="primary")
        if funnel_submitted:
            if not funnel_name.strip():
                st.error("이름을 입력해주세요.")
            else:
                SUPA.table("casting_funnel").insert({
                    "name": funnel_name.strip(), "stage": funnel_stage, "test_rate": funnel_rate or None,
                    "assigned_to": my_name, "notes": funnel_notes.strip() or None,
                }).execute()
                st.success("추가 완료!"); refresh_funnel()

    funnel_all = load_casting_funnel()
    FUNNEL_STAGES = ["지원", "웨비나초대", "테스트완료", "채용", "활성", "탈락"]
    stage_counts = {s: sum(1 for f in funnel_all if f["stage"] == s) for s in FUNNEL_STAGES}
    st.markdown("**퍼널 현황**")
    st.bar_chart(pd.Series(stage_counts))

    for f in funnel_all:
        if f["stage"] == "탈락":
            continue
        with st.container(border=True):
            rate_txt = f" · 테스트 {f['test_rate']:g}" if f.get("test_rate") else ""
            st.markdown(f"**{f['name']}** · {f['stage']}{rate_txt}")
            if f.get("notes"):
                st.caption(f["notes"])
            new_stage = st.selectbox(
                "단계", FUNNEL_STAGES, index=FUNNEL_STAGES.index(f["stage"]),
                key=f"funnelstage_{f['id']}", label_visibility="collapsed",
            )
            if new_stage != f["stage"]:
                SUPA.table("casting_funnel").update({
                    "stage": new_stage, "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
                }).eq("id", f["id"]).execute()
                refresh_funnel()

    st.divider()
    st.caption("참고: 왕홍크루 성장률 등 나머지 KPI는 위 '팀 OKR 현황 > 개별 보기'에서 확인하실 수 있어요.")

else:
    st.caption("이 이름에는 아직 맞춤 도구가 없어요. 필요하시면 말씀해주세요 — 바로 만들어드릴게요.")

st.divider()

# ══════════════════════════════════════════════════════════
# 📊 내 요약 카드 (OKR 대체 — 읽기 전용, 자동 집계)
# ══════════════════════════════════════════════════════════
st.subheader("📊 내 요약 카드")
st.caption("직접 채우는 표가 아니라, 위에서 남긴 기록들이 자동으로 정리되는 카드예요. 관리자와 소통할 때 참고용으로 쓰세요.")

def _naive_ts(val):
    """created_at 등은 시간대 정보(tz-aware)가 있고 week_ago는 없어서(tz-naive) 그냥 비교하면
    'Cannot compare tz-naive and tz-aware timestamps' 에러가 남 — 항상 tz 정보를 떼고 비교한다."""
    if val is None:
        return None
    ts = pd.Timestamp(val)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts


week_ago = pd.Timestamp.now() - timedelta(days=7)
my_placements = [p for p in placements if p["assigned_to"] == my_name]
my_logs_all = SUPA.table("daily_activity_log").select("*").eq("staff_name", my_name).order("created_at", desc=True).limit(50).execute().data

status_counts = {s: 0 for s in STATUS_OPTS}
for p in my_placements:
    status_counts[p["status"]] = status_counts.get(p["status"], 0) + 1

new_this_week = sum(1 for p in my_placements if _naive_ts(p["created_at"]) >= week_ago)
done_this_week = sum(
    1 for p in my_placements
    if p.get("actual_upload_date") and _naive_ts(p["actual_upload_date"]) >= week_ago
)
logs_this_week = sum(1 for lg in my_logs_all if _naive_ts(lg["created_at"]) >= week_ago)

m1, m2, m3, m4 = st.columns(4)
m1.metric("이번주 신규 등록", f"{new_this_week}건")
m2.metric("이번주 업로드 완료", f"{done_this_week}건")
m3.metric("이번주 빠른기록", f"{logs_this_week}건")
m4.metric("전체 진행중", f"{sum(v for k, v in status_counts.items() if k not in ('드롭앤고체크완료', '취소'))}건")

st.markdown("**상태별 현황**")
st.bar_chart(pd.Series(status_counts))

st.divider()

# ══════════════════════════════════════════════════════════
# 🏢 조직도 (회의록 기준 역할/직급 반영 — 최소 20명 규모를 보여주기 위함)
# ══════════════════════════════════════════════════════════
st.subheader("🏢 조직도")
st.caption("사무실 직접 근무 4명 + 각자 산하 staff/어시스턴트를 포함한 전체 조직 구조입니다. (이름 미확인 staff는 '확인필요'로 표시 — 실제 이름 알려주시면 바로 바꿔드릴게요)")

org_chart_dot = """
digraph OrgChart {
    rankdir=TB;
    bgcolor="transparent";
    splines=curved;
    nodesep=0.45;
    ranksep=0.65;
    node [shape=box, style="rounded,filled", fontname="Malgun Gothic", fontsize=12, margin="0.18,0.12", penwidth=0];
    edge [color="#AAAAAA", arrowhead=none, penwidth=1.6];

    CEO [label="장현우\\n대표", fillcolor="#1F3864", fontcolor="white"];
    SOL [label="박솔\\n이사", fillcolor="#2E5597", fontcolor="white"];
    GU [label="구정회\\n개발팀장", fillcolor="#2E7D4F", fontcolor="white"];
    GWAK [label="곽재선\\nAM·인플루언서팀장", fillcolor="#2E7D4F", fontcolor="white"];
    KIM [label="김선재\\n영업·BD팀장", fillcolor="#2E7D4F", fontcolor="white"];
    LEE [label="이단우\\n중국팀장", fillcolor="#2E7D4F", fontcolor="white"];

    CEO -> SOL;
    CEO -> GU;
    CEO -> GWAK;
    CEO -> KIM;
    CEO -> LEE;

    GU1 [label="개발 어시스턴트\\n(충원예정)", fillcolor="#D9E1F2", style="rounded,dashed"];
    GU2 [label="개발 어시스턴트\\n(충원예정)", fillcolor="#D9E1F2", style="rounded,dashed"];
    GU -> GU1; GU -> GU2;

    GWAK1 [label="Meyna\\n인플루언서 협업", fillcolor="#D9E1F2"];
    GWAK2 [label="Sanubari\\n미국 담당", fillcolor="#D9E1F2"];
    GWAK3 [label="Staff\\n(확인필요)", fillcolor="#EDEDED"];
    GWAK4 [label="Staff\\n(확인필요)", fillcolor="#EDEDED"];
    GWAK -> GWAK1; GWAK -> GWAK2; GWAK -> GWAK3; GWAK -> GWAK4;

    KIM1 [label="충원 예정\\n(1명)", fillcolor="white", style="rounded,dashed"];
    KIM -> KIM1;

    LEE1 [label="Staff\\n(확인필요)", fillcolor="#EDEDED"];
    LEE2 [label="Staff\\n(확인필요)", fillcolor="#EDEDED"];
    LEE3 [label="Staff\\n(확인필요)", fillcolor="#EDEDED"];
    LEE4 [label="Staff\\n(확인필요)", fillcolor="#EDEDED"];
    LEE5 [label="Staff\\n(확인필요)", fillcolor="#EDEDED"];
    LEE6 [label="Staff\\n(확인필요)", fillcolor="#EDEDED"];
    LEE -> LEE1; LEE -> LEE2; LEE -> LEE3; LEE -> LEE4; LEE -> LEE5; LEE -> LEE6;
}
"""
st.graphviz_chart(org_chart_dot, use_container_width=True)

headcounts = {"장현우": 1, "박솔": 1, "구정회팀": 1 + 2, "곽재선팀": 1 + 4, "김선재팀": 1 + 1, "이단우팀": 1 + 6}
total_headcount = sum(headcounts.values())
st.caption(f"현재 기준 총 **{total_headcount}명** 규모 (충원 예정 1명 포함)")
