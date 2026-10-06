import os
import io
import re
import html
import calendar
import json
import uuid
import base64
import hashlib
from datetime import date, datetime, timedelta

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

STAFF_NAMES = ["김선재", "곽재선", "구정회", "이단우", "Sanubari", "Meyna", "가상인턴"]
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
    "bank_name": ["은행", "은행명", "지급은행"],
    "bank_account_no": ["계좌번호", "계좌", "수취계좌"],
    "account_holder_name": ["예금주", "수취인", "계좌주"],
    "contract_link": ["계약서", "계약서링크", "서명계약서", "계약링크"],
    "id_doc_link": ["신분증", "신분증링크", "신분증사본"],
    "influencer_email": ["이메일", "메일", "Email", "연락처이메일"],
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
    s = str(val).strip().replace(",", "").replace("₩", "").replace("원", "").strip()
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
    # "26-09-28"(YY-MM-DD) 같은 2자리 연도는 pd.to_datetime이 순서를 잘못 추측하는 경우가 있어
    # (예: 2028-09-26로 뒤바뀜) 명시적 포맷을 먼저 시도해서 그 문제를 막는다.
    for fmt in ("%Y-%m-%d", "%y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
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


def _extract_email(text):
    if not text:
        return None
    m = re.search(r"[\w\.\-+]+@[\w\-]+\.[\w\.\-]+", str(text))
    return m.group(0) if m else None


def _google_file_id(url):
    """구글시트/드라이브 링크에서 파일 ID를 뽑는다. (id, 종류) — 종류: 'sheet' | 'drive' | 'published' | None"""
    url = (url or "").strip()
    if "/spreadsheets/d/e/" in url:
        return None, "published"
    m = re.search(r"/spreadsheets/d/([\w-]+)", url)
    if m:
        return m.group(1), "sheet"
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
    if m:
        return m.group(1), "drive"
    return None, None


def _fetch_google_sheet(url):
    """구글시트 링크를 읽어 {탭이름: DataFrame}으로 돌려준다.
    실패하면 (None, 원인제목, 해결방법)을 돌려줘서 화면에 그대로 보여줄 수 있게 한다."""
    file_id, kind = _google_file_id(url)
    if kind == "published":
        return None, "'웹에 게시' 링크는 읽을 수 없어요", (
            "구글시트 **주소창의 링크**(…/spreadsheets/d/…/edit)를 복사해서 붙여넣어주세요. "
            "'파일 → 공유 → 웹에 게시'로 만든 링크는 지원하지 않아요.")
    if not file_id:
        return None, "구글시트 링크가 아닌 것 같아요", (
            "브라우저 주소창의 링크(https://docs.google.com/spreadsheets/d/…)를 그대로 복사해서 붙여넣어주세요.")

    perm_title = "권한 문제예요 — 저희 쪽에서 이 시트를 열 수 없어요"
    perm_fix = (
        "구글시트 우측 상단 **'공유' → '일반 액세스'를 '링크가 있는 모든 사용자' + '뷰어'**로 바꿔주세요. "
        "'회사 이름(조직) 내 사용자'로만 열어두면 외부 서버에서는 읽을 수 없습니다. "
        "공유가 어렵다면 시트를 **엑셀(.xlsx)로 다운로드해서 아래 '파일로 올리기'**를 쓰셔도 돼요.")

    def _get(u):
        return requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)

    try:
        urls = []
        if kind == "sheet":
            urls.append(f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx")
        urls.append(f"https://drive.google.com/uc?export=download&id={file_id}")  # 드라이브에 올린 엑셀 파일용
        content, last_status = None, None
        for u in urls:
            res = _get(u)
            last_status = res.status_code
            host_login = "accounts.google.com" in res.url
            if res.status_code == 200 and res.content[:2] == b"PK" and not host_login:
                content = res.content
                break
            if res.status_code in (401, 403) or host_login or (res.status_code == 200 and b"<html" in res.content[:500].lower()):
                last_status = 403  # 로그인 페이지로 튕기면 비공개라는 뜻 (코드는 200으로 와서 헷갈림)
                break
            if res.status_code == 404:
                break
            # 400 등: 다음 주소(드라이브 직접 다운로드)로 재시도
        if content is None:
            if last_status in (401, 403):
                return None, perm_title, perm_fix
            if last_status == 404:
                return None, "시트를 찾을 수 없어요", "링크가 잘렸거나 삭제된 시트일 수 있어요. 주소를 다시 복사해주세요."
            return None, f"구글 응답이 이상해요 (코드 {last_status})", (
                "시트가 '구글 스프레드시트' 형식이 아니거나 일시적인 오류일 수 있어요. "
                "잠시 후 다시 시도하시거나, 엑셀로 다운로드해서 '파일로 올리기'를 써주세요.")
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=str)
        if not sheets or all(df.empty for df in sheets.values()):
            return None, "시트가 비어 있어요", "내용이 있는 탭이 하나도 없어요. 맞는 파일인지 확인해주세요."
        return sheets, None, None
    except requests.exceptions.RequestException as e:
        return None, "구글에 연결하지 못했어요", f"네트워크 문제일 수 있어요. 잠시 후 다시 시도해주세요. (상세: {type(e).__name__}: {e})"
    except Exception as e:
        return None, "파일을 해석하지 못했어요", f"(상세: {type(e).__name__}: {e})"


def _read_uploaded_sheet_file(f):
    """직접 올린 .xlsx / .csv 파일을 {탭이름: DataFrame}으로 읽는다. (sheets, 에러문구)"""
    try:
        if f.name.lower().endswith(".csv"):
            raw = f.getvalue()
            for enc in ("utf-8-sig", "cp949"):
                try:
                    return {"CSV": pd.read_csv(io.StringIO(raw.decode(enc)), header=None, dtype=str)}, None
                except UnicodeDecodeError:
                    continue
            return None, "CSV 글자 인코딩을 알 수 없어요. 엑셀(.xlsx)로 저장해서 올려주세요."
        return pd.read_excel(io.BytesIO(f.getvalue()), sheet_name=None, header=None, dtype=str), None
    except Exception as e:
        return None, f"파일을 읽지 못했어요 ({type(e).__name__}: {e})"


def _cell_is_datalike(v):
    """셀이 '값'(금액·URL·이메일·날짜·계좌번호)처럼 보이면 True, 비었으면 None, 글자뿐이면 False."""
    sv = str(v).strip()
    if not sv or sv.lower() == "nan":
        return None
    if re.search(r"\d", sv) and re.fullmatch(r"[\d,.\s₩원$-]+", sv):
        return True
    if "@" in sv or sv.lower().startswith("http") or re.search(r"\d{2,}-\d{2,}", sv):
        return True
    return bool(re.fullmatch(r"\d{2,4}[-./]\d{1,2}[-./]\d{1,2}", sv))


def _detect_header_rows(raw_df):
    """한 탭 안에서 '제목줄(헤더)처럼 보이는 행'을 찾는다. 반환: 1부터 세는 행 번호 목록(못 찾으면 [1]).
    제목줄 = 내용 있는 칸 3개 이상이 전부 글자뿐이고, 바로 뒤 몇 줄 안에 값(금액·URL 등)이 있는 행."""
    kinds = [[_cell_is_datalike(v) for v in row] for row in raw_df.values.tolist()]
    found = []
    for i, ks in enumerate(kinds):
        filled = [k for k in ks if k is not None]
        if len(filled) < 3 or any(filled):
            continue
        if found and found[-1] == i:  # 바로 윗줄도 제목줄이면 두 줄짜리 제목으로 보고 첫 줄만 사용
            continue
        if any(True in [k for k in nxt if k is not None] for nxt in kinds[i + 1:i + 4]):
            found.append(i + 1)
    return found or [1]


def _parse_row_numbers(text, max_row):
    """'1, 22, 45' → [1, 22, 45]. 범위를 벗어나거나 숫자가 아닌 건 버린다."""
    nums = {int(t) for t in re.findall(r"\d+", str(text or "")) if 1 <= int(t) <= max_row}
    return sorted(nums)


def _col_letter(n):
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _collect_sections(all_sheets):
    """탭마다 사용자가 확인한 제목줄 행 번호대로 표 구간을 나눈다. {'탭 · 행 a~b': DataFrame(첫 행=제목줄)}"""
    sections = {}
    for i, (name, df) in enumerate(all_sheets.items()):
        if st.session_state.get(f"hdr_skip_{i}") or df.empty:
            continue
        heads = _parse_row_numbers(st.session_state.get(f"hdr_rows_{i}", ""), len(df)) or [1]
        for k, h in enumerate(heads):
            end = heads[k + 1] - 1 if k + 1 < len(heads) else len(df)
            sections[f"{name} · 행 {h}~{end}"] = df.iloc[h - 1:end].reset_index(drop=True)
    return sections


_DRIVE_API = "https://www.googleapis.com/drive/v3/files"
_CONTRACT_WORDS = ("계약", "contract", "agreement", "mou", "견적", "합의")


def _drive_token():
    """서비스계정(GOOGLE_SERVICE_ACCOUNT_JSON)으로 드라이브 읽기 전용 토큰을 받는다. (token, 서비스계정 이메일, 에러문구)"""
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None, None, "GOOGLE_SERVICE_ACCOUNT_JSON 환경변수가 이 서비스(brandslamteamspace)에 설정돼 있지 않아요. Railway Variables에 다른 서비스에서 쓰는 값을 복사해주세요."
    try:
        info = json.loads(raw)
    except Exception as e:
        return None, None, f"GOOGLE_SERVICE_ACCOUNT_JSON이 올바른 JSON이 아니에요 ({type(e).__name__}: {e}). 줄바꿈·따옴표가 깨졌는지 확인해주세요."
    email = info.get("client_email")
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
        creds.refresh(Request())
        return creds.token, email, None
    except ImportError:
        return None, email, "google-auth 패키지가 설치돼 있지 않아요(requirements.txt 반영 후 재배포가 필요해요)."
    except Exception as e:
        return None, email, f"구글 인증에 실패했어요 ({type(e).__name__}: {e})"


def _drive_norm(text):
    """비교용으로 공백·기호를 없애고 소문자로 맞춘다. 'Farm Skin_방문형' → 'farmskin방문형'"""
    return re.sub(r"[^0-9a-z가-힣]", "", str(text or "").lower())


def _drive_q(text):
    return str(text).replace("\\", "\\\\").replace("'", "\\'")


class _DriveError(Exception):
    """드라이브 호출 실패 — 메시지를 그대로 화면에 보여준다."""


def _sa_field(key):
    try:
        return json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or "{}").get(key)
    except Exception:
        return None


def _google_error_parts(res):
    """구글 오류 응답에서 (error.message, error.errors[0].reason, error.details[].reason 목록)을 꺼낸다."""
    try:
        err = res.json().get("error", {})
    except Exception:
        return (res.text or "")[:200], None, []
    if not isinstance(err, dict):
        return str(err)[:200], None, []
    errors = err.get("errors") or []
    reason = errors[0].get("reason") if errors and isinstance(errors[0], dict) else None
    details = [d.get("reason") for d in (err.get("details") or []) if isinstance(d, dict) and d.get("reason")]
    return (err.get("message") or (res.text or "")[:200]), reason, details


def _drive_http_error(res, target="최상위 폴더"):
    """드라이브 오류 응답을 원인별 안내 + 구글이 보낸 원문(message/reason)으로 바꾼다."""
    message, reason, details = _google_error_parts(res)
    code = res.status_code
    email = _sa_field("client_email") or "(서비스계정 이메일)"
    if reason in ("accessNotConfigured", "SERVICE_DISABLED") or "SERVICE_DISABLED" in details:
        project = _sa_field("project_id") or "<서비스계정 JSON의 project_id>"
        head = (f"Drive API가 꺼져 있어요. 아래 링크에서 '사용'을 눌러 켜주세요 (켠 뒤 몇 분 걸릴 수 있어요):\n"
                f"https://console.cloud.google.com/apis/library/drive.googleapis.com?project={project}")
    elif code == 404:
        head = (f"{target}을(를) 못 찾았어요 (404). **서비스계정이 공유 드라이브 멤버가 아니에요.** "
                f"공유 드라이브라면 그 드라이브에 `{email}` 을(를) 멤버(뷰어 이상)로 추가해주세요. "
                "일반 폴더라면 폴더 공유에 같은 이메일을 뷰어로 추가하고, DRIVE_FOLDER_ID가 맞는지도 확인해주세요.")
    elif code == 403:
        head = (f"{target}을(를) 열 권한이 없어요 (403). 폴더 공유에 `{email}` 을(를) 뷰어로 추가해주세요.")
    elif code == 401:
        head = "구글 인증이 거부됐어요 (401). GOOGLE_SERVICE_ACCOUNT_JSON 값이 맞는지 확인해주세요."
    else:
        head = f"드라이브 응답 오류 (코드 {code})."
    raw = f"구글 응답: {message}" + (f" (reason: {reason})" if reason else "")
    if details and set(details) - {reason}:
        raw += f" [details: {', '.join(dict.fromkeys(details))}]"
    return f"{head}\n\n{raw}"


def _drive_list(token, q, fields="id,name,mimeType,webViewLink,modifiedTime,parents", page_cap=5):
    """드라이브 files.list를 페이지 끝까지(최대 page_cap쪽) 읽는다. 공유 드라이브 포함."""
    out, page_token = [], None
    for _ in range(page_cap):
        params = {
            "q": q, "fields": f"nextPageToken,files({fields})", "pageSize": 1000,
            "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "corpora": "allDrives",
        }
        if page_token:
            params["pageToken"] = page_token
        res = requests.get(_DRIVE_API, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if res.status_code != 200:
            raise _DriveError(_drive_http_error(res, "폴더 목록"))
        data = res.json()
        out.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return out


def _drive_find_contracts(brand_name, campaign_name="", max_folders=400, max_show=60):
    """DRIVE_FOLDER_ID(최상위 폴더) 아래 모든 하위 폴더를 훑어서, 이름에 '계약'이 들어간 폴더와 업체명이 들어간 폴더·파일을 찾는다.
    반환: (후보 목록, 안내문구, 에러문구). 후보: {'id','name','path','link','modified','score'}"""
    root = os.environ.get("DRIVE_FOLDER_ID")
    if not root:
        return [], None, "DRIVE_FOLDER_ID 환경변수가 이 서비스에 설정돼 있지 않아요(최상위 폴더 ID)."
    token, sa_email, err = _drive_token()
    if err:
        return [], None, err
    try:
        meta = requests.get(
            f"{_DRIVE_API}/{root}", params={"fields": "id,name", "supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {token}"}, timeout=30,
        )
        if meta.status_code != 200:
            return [], None, _drive_http_error(meta, f"최상위 폴더({root})")

        # 1) 하위 폴더 전체를 층별로 훑어서 {폴더ID: (이름, 부모ID)} 로 만든다
        folders = {root: (meta.json().get("name", ""), None)}
        level = [root]
        while level and len(folders) < max_folders:
            nxt = []
            for i in range(0, len(level), 25):
                parents = " or ".join(f"'{pid}' in parents" for pid in level[i:i + 25])
                for f in _drive_list(token, f"({parents}) and trashed=false and mimeType='application/vnd.google-apps.folder'",
                                     fields="id,name,parents"):
                    if f["id"] not in folders:
                        folders[f["id"]] = (f["name"], (f.get("parents") or [None])[0])
                        nxt.append(f["id"])
            level = nxt

        def path_of(fid):
            names, cur = [], fid
            while cur in folders and len(names) < 12:
                names.append(folders[cur][0]); cur = folders[cur][1]
            return " / ".join(reversed(names))

        brand = (brand_name or "").strip()
        brand_n = _drive_norm(brand)
        camp_n = _drive_norm(campaign_name)
        ids = list(folders)

        def chain_names(fid):  # 최상위 폴더를 뺀 폴더 이름들(바깥 → 안쪽)
            names, cur = [], fid
            while cur in folders and cur != root and len(names) < 12:
                names.append(folders[cur][0]); cur = folders[cur][1]
            return list(reversed(names))

        def in_contract(fid):  # 이름에 '계약'이 들어간 폴더이거나 그 아래에 있는 폴더
            return any("계약" in n for n in chain_names(fid))

        def brand_in_chain(fid):
            return bool(brand_n) and any(brand_n in _drive_norm(n) for n in chain_names(fid))

        # 2) 파일: '계약' 폴더 아래 + 업체명이 들어간 폴더 아래의 모든 파일을 가져와서, 파일명/폴더경로에 업체명이 있으면 전부 후보로 삼는다
        #    (드라이브의 name contains 검색은 단어 앞부분만 맞춰서, 'farmskin_계약서'처럼 붙은 이름은 파이썬에서 직접 걸러낸다)
        found, api_hits = {}, set()
        if brand_n:
            scan_ids = [fid for fid in ids if fid != root and (in_contract(fid) or brand_in_chain(fid))]
            for i in range(0, len(scan_ids), 25):
                parents = " or ".join(f"'{pid}' in parents" for pid in scan_ids[i:i + 25])
                for f in _drive_list(token, f"({parents}) and trashed=false and mimeType!='application/vnd.google-apps.folder'", page_cap=10):
                    found[f["id"]] = f
            for i in range(0, len(ids), 25):  # 보조: 계약 폴더 밖에 있는 파일 중 이름에 업체명이 있는 것
                parents = " or ".join(f"'{pid}' in parents" for pid in ids[i:i + 25])
                for f in _drive_list(token, f"({parents}) and trashed=false and mimeType!='application/vnd.google-apps.folder' and name contains '{_drive_q(brand)}'"):
                    found[f["id"]] = f
                    api_hits.add(f["id"])

        cands = []
        for f in found.values():
            parent = (f.get("parents") or [None])[0]
            fpath = path_of(parent) if parent in folders else ""
            name_hit = bool(brand_n) and brand_n in _drive_norm(f["name"])
            path_hit = parent in folders and brand_in_chain(parent)
            if not (name_hit or path_hit or f["id"] in api_hits):
                continue  # '계약' 폴더 안에 있어도 업체명과 무관한 파일은 제외
            score = 0
            if parent in folders and in_contract(parent):
                score += 3
            if name_hit:
                score += 4
            if path_hit:
                score += 2
            if any(w in f["name"].lower() for w in _CONTRACT_WORDS):
                score += 1
            if camp_n and camp_n in _drive_norm(f["name"]):
                score += 2
            cands.append({
                "id": f["id"], "name": f["name"], "path": fpath, "link": f.get("webViewLink"),
                "modified": (f.get("modifiedTime") or "")[:10], "score": score, "kind": "file",
            })
        n_files = len(cands)

        # 3) 폴더: 이름에 '계약'이 들어간 폴더 + 이름에 업체명이 들어간 폴더(예: '계약서/farmskin 방문형')를 폴더째로 제안
        n_contract_folders = n_brand_folders = 0
        for fid in ids:
            fname = folders[fid][0]
            if fid == root:
                continue
            is_contract = "계약" in fname
            is_brand = bool(brand_n) and brand_n in _drive_norm(fname)
            if not (is_contract or is_brand):
                continue
            score = (6 + (2 if in_contract(fid) else 0)) if is_brand else 4
            if is_contract and brand_in_chain(fid):
                score += 3
            if camp_n and camp_n in _drive_norm(path_of(fid)):
                score += 1
            parent_id = folders[fid][1]
            n_brand_folders += is_brand
            n_contract_folders += (is_contract and not is_brand)
            cands.append({
                "id": fid, "name": fname, "path": path_of(parent_id) if parent_id in folders else "",
                "link": f"https://drive.google.com/drive/folders/{fid}", "modified": "", "score": score, "kind": "folder",
            })
        cands.sort(key=lambda c: (c["score"], c["modified"]), reverse=True)
        note = f"폴더 {len(folders)}개를 훑어서 '계약' 폴더 {n_contract_folders}개"
        if brand:
            note += f", '{brand}' 폴더 {n_brand_folders}개, '{brand}' 관련 파일 {n_files}개를 찾았어요."
        else:
            note += "를 찾았어요. (브랜드명을 입력하면 그 브랜드 폴더·파일도 같이 찾아요)"
        if len(cands) > max_show:
            note += f" 점수가 높은 {max_show}개만 보여드려요."
        if len(folders) >= max_folders:
            note += f" (폴더가 많아서 앞 {max_folders}개까지만 훑었어요)"
        return cands[:max_show], note, None
    except _DriveError as e:
        return [], None, str(e)
    except Exception as e:
        return [], None, f"드라이브에서 찾는 중 문제가 생겼어요 ({type(e).__name__}: {e})"


@st.cache_data(ttl=120, show_spinner=False)
def _drive_children(folder_id):
    """폴더 안의 항목(하위 폴더 + 파일)을 읽는다. 반환: (항목 목록, 에러문구). 하위 폴더가 먼저, 파일은 최근 수정순."""
    token, _email, err = _drive_token()
    if err:
        return [], err
    try:
        items = _drive_list(
            token, f"'{_drive_q(folder_id)}' in parents and trashed=false",
            fields="id,name,mimeType,webViewLink,modifiedTime", page_cap=5,
        )
    except _DriveError as e:
        return [], str(e)
    except Exception as e:
        return [], f"폴더 내용을 읽는 중 문제가 생겼어요 ({type(e).__name__}: {e})"
    is_folder = lambda it: it.get("mimeType") == "application/vnd.google-apps.folder"
    folders_ = sorted([i for i in items if is_folder(i)], key=lambda i: i["name"].lower())
    files_ = sorted([i for i in items if not is_folder(i)], key=lambda i: i.get("modifiedTime") or "", reverse=True)
    return folders_ + files_, None


_CAL_COLORS = ["#4C78A8", "#F58518", "#54A24B", "#B279A2", "#E45756", "#72B7B2", "#EECA3B", "#9D755D"]


def _render_month_calendar(events, year, month, today, max_chips=4):
    """월 달력(HTML)을 만든다. events: [{'date','label','full','key','done'}]. 같은 날 일정은 캠페인 색으로 쌓여서 겹쳐 보인다."""
    keys = sorted({e["key"] for e in events}, key=str)
    color_of = {k: _CAL_COLORS[i % len(_CAL_COLORS)] for i, k in enumerate(keys)}
    by_day = {}
    for e in events:
        by_day.setdefault(e["date"], []).append(e)
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)  # 일요일 시작
    head = "".join(f"<th style='padding:6px;text-align:center;font-weight:600'>{d}</th>" for d in "일월화수목금토")
    rows = []
    for wk in weeks:
        tds = []
        for d in wk:
            in_month = d.month == month
            chips = []
            for e in sorted(by_day.get(d, []), key=lambda x: (x["done"], str(x["key"])))[:max_chips]:
                c = color_of[e["key"]]
                deco = "text-decoration:line-through;opacity:.55;" if e["done"] else ""
                chips.append(
                    f"<div title='{html.escape(e['full'], quote=True)}' style='margin:2px 0;padding:1px 5px;border-radius:4px;"
                    f"border-left:3px solid {c};background:{c}33;font-size:11px;line-height:1.35;white-space:nowrap;"
                    f"overflow:hidden;text-overflow:ellipsis;{deco}'>{html.escape(e['label'])}</div>"
                )
            more = len(by_day.get(d, [])) - max_chips
            if more > 0:
                chips.append(f"<div style='font-size:11px;opacity:.7'>+{more}개 더</div>")
            is_today = d == today
            num_style = "font-weight:700;color:#fff;background:#E45756;border-radius:10px;padding:0 6px;" if is_today else ""
            tds.append(
                f"<td style='vertical-align:top;height:104px;padding:4px;border:1px solid rgba(128,128,128,.25);"
                f"{'' if in_month else 'opacity:.35;'}'><div style='font-size:12px;margin-bottom:2px'>"
                f"<span style='{num_style}'>{d.day}</span></div>{''.join(chips)}</td>"
            )
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return (
        "<table style='width:100%;table-layout:fixed;border-collapse:collapse'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    ), color_of


def _month_add(y, m, n):
    t = y * 12 + (m - 1) + n
    return t // 12, t % 12 + 1


def _forecast_next_month(accounts, campaigns, tasks, today):
    """등록된 데이터만으로 '다음달 캠페인'을 규칙 기반으로 예측한다(추측 숫자를 만들지 않고, 근거를 함께 돌려준다).
    반환: 계정별 행 목록. 상태: 확정(다음달 캠페인이 이미 등록됨) / 높음 / 중간 / 낮음."""
    cy, cm = today.year, today.month
    ny, nm = _month_add(cy, cm, 1)
    camps_by_acc = {}
    for c in campaigns:
        if c.get("account_id") and c.get("open_date"):
            camps_by_acc.setdefault(c["account_id"], []).append(c)
    tasks_by_camp = {}
    for t in tasks:
        tasks_by_camp.setdefault(t["campaign_id"], []).append(t)

    rows = []
    for a in accounts:
        if a.get("status") in ("종료", "이탈"):
            continue
        cs = sorted(camps_by_acc.get(a["id"], []), key=lambda c: str(c["open_date"]))
        months = {(int(str(c["open_date"])[:4]), int(str(c["open_date"])[5:7])) for c in cs}
        budget = float(a["monthly_budget"]) if a.get("monthly_budget") else None
        renewal = date.fromisoformat(str(a["renewal_date"])[:10]) if a.get("renewal_date") else None
        renewal_next = bool(renewal and (renewal.year, renewal.month) == (ny, nm))

        # 이번 달(없으면 지난달)부터 거꾸로 연속으로 캠페인이 있던 달 수
        start = (cy, cm) if (cy, cm) in months else _month_add(cy, cm, -1)
        streak, cur = 0, start
        while cur in months and streak < 12:
            streak += 1
            cur = _month_add(cur[0], cur[1], -1)
        streak = streak if start in months else 0

        last = cs[-1] if cs else None
        pred_open = None
        if last:
            ld = date.fromisoformat(str(last["open_date"])[:10])
            pred_open = date(ny, nm, min(ld.day, calendar.monthrange(ny, nm)[1]))
        elif renewal_next:
            pred_open = renewal

        # 가장 최근 캠페인의 '다음달 견적서 발송(3주차)' · '다음달 계약 확정·입금(4주차)' 진행 상황
        wk = {t["week_number"]: t["status"] for t in tasks_by_camp.get(last["id"], [])} if last else {}

        registered = [c for c in cs if (int(str(c["open_date"])[:4]), int(str(c["open_date"])[5:7])) == (ny, nm)]
        reasons = []
        if registered:
            level = "확정"
            reasons.append(f"다음달 캠페인 {len(registered)}건 등록됨: " + ", ".join(c["campaign_name"] for c in registered))
        else:
            active = a.get("status") in ("운영중", "계약완료")
            if active and streak >= 2:
                level = "높음"; reasons.append(f"{streak}개월 연속 캠페인 진행")
            elif active and (streak == 1 or renewal_next):
                level = "중간"
                if streak == 1:
                    reasons.append("지난/이번 달 캠페인 진행 (연속 1개월)")
            else:
                level = "낮음"
                reasons.append("협상 중" if a.get("status") == "협상중" else "최근 캠페인 기록이 없음")
            if renewal_next:
                reasons.append(f"다음달 갱신/온보딩일 {renewal.isoformat()}")
            if wk.get(3) == "완료":
                reasons.append("3주차 '익월 견적서 발송' 완료")
            elif last and wk.get(3):
                reasons.append(f"견적서 발송(3주차) {wk[3]}")
        rows.append({
            "brand": a["brand_name"], "level": level, "reason": " · ".join(reasons) or "-",
            # 근거가 약하면(낮음) 예상 오픈일을 지어내지 않는다
            "pred_open": None if level == "낮음" else pred_open,
            "budget": budget, "budget_missing": budget is None,
            "owner": a.get("assigned_to"),
        })
    order = {"확정": 0, "높음": 1, "중간": 2, "낮음": 3}
    rows.sort(key=lambda r: (order[r["level"]], r["brand"]))
    return rows


def _api_error_text(status, body):
    """Claude API 오류를 직원이 이해할 수 있는 말로 바꾼다(원문도 같이 보여줘서 원인을 숨기지 않는다)."""
    body = str(body or "")
    if "credit balance is too low" in body:
        return ("Anthropic API 크레딧이 부족해요. 코드 문제가 아니라 결제 문제예요 — "
                "console.anthropic.com → Plans & Billing에서 이 API 키가 속한 조직의 크레딧을 충전해주세요. "
                f"(원문: 코드 {status})")
    if status == 401:
        return f"ANTHROPIC_API_KEY가 올바르지 않아요 (코드 401): {body[:150]}"
    if status == 429:
        return f"요청이 너무 많아요. 잠시 후 다시 시도해주세요 (코드 429): {body[:150]}"
    return f"Claude API 응답 오류 (코드 {status}): {body[:200]}"


def _ai_infer_column_mapping(all_sheets):
    """본격적으로 전부 추출하기 전에, 열 구성을 어떻게 이해했는지 사람이 먼저 확인하게 한다
    (예: 'A열이 이름이 맞나요?'에 해당하는 사전 점검 단계)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY 환경변수가 이 앱(brandslamteamspace)에 설정되어 있지 않아요."
    sheet_samples = {}
    for name, raw_df in all_sheets.items():
        if raw_df.empty:
            continue
        header = [str(h) if pd.notna(h) else "" for h in raw_df.iloc[0].tolist()]
        sample_rows = raw_df.iloc[1:3].fillna("").astype(str).values.tolist()
        sheet_samples[name] = {"header": header, "sample_rows": sample_rows}
    if not sheet_samples:
        return None, "시트에서 읽을 데이터를 못 찾았어요(빈 시트)."

    system = (
        "너는 스프레드시트의 열 구성을 사람에게 짧게 설명해주는 보조원이다. 헤더 텍스트와 샘플 행 1~2개를 보고, "
        "각 열(A, B, C...)이 실제로 어떤 내용을 담고 있는지 추측해서, 한국어로 아주 짧게 정리해라. "
        "예: 'A열: 인플루언서 이름 / B열: 비어있음(사용 안 함) / ... / J열: 송금액'. "
        "헤더 텍스트가 질문 문장이라도 속지 말고 샘플 값을 보고 실제 의미를 판단해라. "
        "여러 시트(탭)가 있으면 시트 이름별로 구분해서 적어라. 다른 설명 없이 이 요약만 출력해라."
    )
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-5", "max_tokens": 1000, "system": system,
                  "messages": [{"role": "user", "content": json.dumps(sheet_samples, ensure_ascii=False)}]},
            timeout=30,
        )
        if res.status_code >= 300:
            return None, _api_error_text(res.status_code, res.text)
        text = "".join(b.get("text", "") for b in res.json().get("content", []) if b.get("type") == "text").strip()
        return text, None
    except Exception as e:
        return None, f"예외 발생: {e}"


def _ai_extract_payment_rows(raw_df, existing_keys, batch_size=20, extra_hint=None, report=None):
    """시트 양식이 제각각이라도(방문형/업로드형/기업형 등) Claude가 각 행의 '의미'를 보고
    알아서 이름/금액/결제수단/링크 등을 뽑아낸다 — 열 위치를 고정하지 않는다.
    헤더 텍스트가 구글폼 질문이라 믿을 수 없는 경우에도 셀 내용 자체로 판단한다."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    rows, skipped = [], 0
    if report is None:
        report = {}
    report.setdefault("errors", [])
    report.setdefault("reasons", {})

    def _why(reason, n=1):
        report["reasons"][reason] = report["reasons"].get(reason, 0) + n

    if not api_key:
        report["errors"].append("ANTHROPIC_API_KEY 환경변수가 이 서비스에 설정돼 있지 않아요.")
    if not api_key or raw_df.empty or len(raw_df) < 2:
        return rows, max(0, len(raw_df) - 1)

    header = [str(h) if pd.notna(h) else "" for h in raw_df.iloc[0].tolist()]
    data_rows = raw_df.iloc[1:].fillna("").astype(str).values.tolist()

    system = (
        "너는 인플루언서 송금 정보가 담긴 스프레드시트의 각 행을 읽고, 열 순서가 어떻든 상관없이 "
        "의미로 판단해서 다음 필드를 추출하는 보조원이다: influencer_name(이름), amount(송금액, 숫자만), "
        "payment_method_raw(은행명+계좌번호 또는 PayPal 이메일 등 결제수단 — 원문 그대로), "
        "content_link(인스타/틱톡 등 업로드된 콘텐츠 링크), visit_date(방문일, YYYY-MM-DD), "
        "upload_date(업로드일, YYYY-MM-DD), scheduled_date(송금예정일, YYYY-MM-DD), "
        "id_doc_link(신분증/계좌 사본 드라이브 링크).\n\n"
        "헤더가 실제 필드명이 아니라 설명문/질문일 수 있다(구글폼으로 만든 시트 등) — 헤더 텍스트를 믿지 말고 "
        "각 셀의 실제 '내용'을 보고 판단해라. 이름도 금액도 없는 행(안내문, 기업용 결제 블록, 빈 줄, 관련시트 링크만 있는 행 등)은 "
        "skip:true로 건너뛰어라. 확신 없는 필드는 null로 둬라.\n\n"
        "출력은 오직 JSON 배열만, 입력 행과 같은 순서·같은 개수로: "
        "[{\"skip\":false,\"influencer_name\":\"...\",\"amount\":숫자 또는 null,\"payment_method_raw\":\"...\" 또는 null,"
        "\"content_link\":\"...\" 또는 null,\"visit_date\":\"...\" 또는 null,\"upload_date\":\"...\" 또는 null,"
        "\"scheduled_date\":\"...\" 또는 null,\"id_doc_link\":\"...\" 또는 null}, ...]. 다른 텍스트는 절대 포함하지 마라."
    )
    if extra_hint:
        system += f"\n\n사용자가 직접 알려준 열 구성 보정 사항(반드시 반영해라): {extra_hint}"

    for start in range(0, len(data_rows), batch_size):
        chunk = data_rows[start:start + batch_size]
        user_content = json.dumps({"headers": header, "rows": chunk}, ensure_ascii=False)
        try:
            res = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-5", "max_tokens": 4000, "system": system,
                      "messages": [{"role": "user", "content": user_content}]},
                timeout=60,
            )
            if res.status_code >= 300:
                report["errors"].append(_api_error_text(res.status_code, res.text))
                skipped += len(chunk)
                continue
            text = "".join(b.get("text", "") for b in res.json().get("content", []) if b.get("type") == "text").strip()
            # 앞뒤에 설명이나 ```json 이 붙어 와도 JSON 배열 부분만 꺼낸다
            lb, rb = text.find("["), text.rfind("]")
            if lb == -1 or rb <= lb:
                raise ValueError(f"JSON 배열을 못 찾음. 응답 앞부분: {text[:120]}")
            extracted = json.loads(text[lb:rb + 1])
        except Exception as e:
            report["errors"].append(f"{start + 1}~{start + len(chunk)}행 처리 실패 ({type(e).__name__}: {e})")
            skipped += len(chunk)
            continue

        for item in extracted:
            if not isinstance(item, dict) or item.get("skip"):
                skipped += 1
                _why("AI가 송금 정보가 아닌 행(안내문·빈 줄 등)으로 판단")
                continue
            name = str(item.get("influencer_name") or "").strip()
            amount = _clean_number(item.get("amount"))
            if not name or amount is None:
                skipped += 1
                _why("이름 또는 금액을 못 찾음")
                continue

            payment_method_raw = item.get("payment_method_raw")
            content_link = item.get("content_link")
            visit_date = _clean_date(item.get("visit_date")) if item.get("visit_date") else None
            upload_date = _clean_date(item.get("upload_date")) if item.get("upload_date") else None
            scheduled_date = _clean_date(item.get("scheduled_date")) if item.get("scheduled_date") else None
            id_doc_link = item.get("id_doc_link")
            # ⚠️ 이건 "돈이 실제로 가는 페이팔 계정"이지, 안내메일 받을 주소가 아니다 — 절대 섞으면 안 됨
            paypal_email = _extract_email(payment_method_raw)
            # 결제수단 자체가 비어있으면("-", 공백 등) 어디로 보낼지 알 수 없는 상태 — 등록 차단 대상
            destination_verified = bool(payment_method_raw and str(payment_method_raw).strip() not in ("-", ""))

            dedup_src = f"{content_link or ''}|{visit_date or ''}|{amount}"
            dedup_key = hashlib.md5(dedup_src.encode("utf-8")).hexdigest()
            if dedup_key in existing_keys:
                skipped += 1
                _why("이미 등록된 건(중복)")
                continue

            rows.append({
                "influencer_name": name, "tiktok_url": None, "instagram_url": None,
                "visit_date": visit_date, "upload_date": upload_date, "content_link": content_link,
                "payment_method_raw": payment_method_raw, "id_doc_link": id_doc_link,
                "amount": amount, "scheduled_date": scheduled_date,
                "paypal_email": paypal_email, "notification_email": None,
                "payment_destination_verified": destination_verified,
                "dedup_key": dedup_key,
            })
    return rows, skipped



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
ROLE_MAP = {"김선재": "sales", "곽재선": "influencer", "구정회": "dev", "이단우": "china_ops", "가상인턴": "sales"}  # 가상인턴=테스트 계정(세일즈 화면 시험용)
my_role = ROLE_MAP.get(my_name)


st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] {
    gap: 6px;
    border-bottom: 1px solid #e3e6ec;
    margin-bottom: 8px;
}
.stTabs [data-baseweb="tab"] {
    height: 42px;
    white-space: pre-wrap;
    background-color: transparent;
    border-radius: 0px;
    padding: 6px 14px;
    color: #6b7280;
    transition: color 0.18s ease, border-color 0.18s ease;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #2e5597;
    border-bottom: 2px solid #b9c8e8;
}
.stTabs [aria-selected="true"] {
    color: #10234f !important;
    border-bottom: 2px solid #10234f !important;
    font-weight: 700 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid #ededf2 !important;
    border-radius: 12px !important;
}
</style>
""", unsafe_allow_html=True)

tab_home, tab_okr, tab_log, tab_campaign, tab_finance, tab_mywork, tab_summary, tab_org = st.tabs([
    "🏠 홈", "🎯 목표", "📝 오늘 기록", "📋 캠페인", "💰 재무", "🧰 내 업무", "📊 요약", "🏢 조직도",
])

with tab_home:
    # ── 📋 채워주세요! (30분마다 도는 완성도 체크가 찾아낸 빈 정보) ──
    open_prompts = (
        SUPA.table("data_completeness_prompts")
        .select("*").eq("person", my_name).eq("status", "open")
        .order("created_at", desc=True).execute().data
    )
    if open_prompts:
        st.warning(f"📋 **현황판을 완성하려면 아래 {len(open_prompts)}건이 필요해요** (자동으로 채워지지 않아서 직접 확인 부탁드려요)")
        for p in open_prompts:
            pc1, pc2 = st.columns([5, 1])
            pc1.caption(f"• {p['message']}")
            if pc2.button("✅ 처리함", key=f"resolve_prompt_{p['id']}"):
                SUPA.table("data_completeness_prompts").update({
                    "status": "dismissed",
                }).eq("id", p["id"]).execute()
                st.rerun()

    # ── 🤖 AI가 미리 준비해둔 내용 (구글드라이브 등에서 발견, 본인 확인만 하면 됨) ──
    ai_drafts = (
        SUPA.table("ai_drafted_updates").select("*")
        .eq("person", my_name).eq("status", "pending")
        .order("created_at", desc=True).execute().data
    )
    if ai_drafts:
        st.info(f"🤖 **구글드라이브 등에서 업무 관련 내용을 확인했어요** — 아래 {len(ai_drafts)}건, 맞는지만 봐주세요")
        for d in ai_drafts:
            with st.container(border=True):
                st.write(d["draft_content"])
                dc1, dc2 = st.columns([1, 2])
                if dc1.button("✅ 맞아요, 문제없어요", key=f"confirm_draft_{d['id']}", use_container_width=True):
                    SUPA.table("ai_drafted_updates").update({
                        "status": "applied", "resolved_at": pd.Timestamp.now(tz="UTC").isoformat(),
                    }).eq("id", d["id"]).execute()
                    st.rerun()
                correction = dc2.text_input(
                    "틀린 부분 있으면 여기에 자유롭게 적어주세요", key=f"correction_{d['id']}",
                    placeholder="예: 계약 시작일은 9/1이 아니라 9/15이에요",
                )
                if correction.strip() and st.button("📝 수정사항 제출", key=f"submit_correction_{d['id']}"):
                    SUPA.table("ai_drafted_updates").update({
                        "status": "correction_requested", "correction_note": correction.strip(),
                    }).eq("id", d["id"]).execute()
                    st.success("제출 완료! 30분 안에 알아서 정리해둘게요.")
                    st.rerun()

    # ── 📼 세일즈 전용: 등록된 업체명이 언급된 회의만 알림 (기밀 보호) ──
    if my_role == "sales":
        sales_alerts = (
            SUPA.table("sales_meeting_alerts").select("*")
            .eq("person", my_name).eq("status", "open")
            .order("meeting_date", desc=True).execute().data
        )
        if sales_alerts:
            st.info(f"📼 **담당하시는 업체 관련 회의가 있었어요** — {len(sales_alerts)}건 (등록된 업체명이 언급된 회의만 보여드려요)")
            for al in sales_alerts:
                with st.container(border=True):
                    when = al["meeting_date"][:10] if al.get("meeting_date") else ""
                    st.markdown(f"**[{al['brand_matched']}]** {al.get('meeting_title') or ''} · {when}")
                    if al.get("summary_snippet"):
                        st.caption(al["summary_snippet"])
                    ac1, ac2 = st.columns(2)
                    if ac1.button("✅ 업무보고에 반영해주세요", key=f"reflect_meeting_{al['id']}", use_container_width=True):
                        SUPA.table("ai_drafted_updates").insert({
                            "person": my_name, "source": "meeting", "source_ref": str(al["meeting_id"]),
                            "target_table": "sales_accounts",
                            "draft_content": f"[{al['brand_matched']}] 관련 회의 내용: {al.get('summary_snippet') or ''}",
                        }).execute()
                        SUPA.table("sales_meeting_alerts").update({"status": "reflected"}).eq("id", al["id"]).execute()
                        st.success("반영 요청 접수! 위 'AI가 준비해둔 내용'에서 곧 확인하실 수 있어요.")
                        st.rerun()
                    if ac2.button("그냥 참고만 할게요", key=f"dismiss_meeting_{al['id']}", use_container_width=True):
                        SUPA.table("sales_meeting_alerts").update({"status": "dismissed"}).eq("id", al["id"]).execute()
                        st.rerun()

    # ── 🧭 내 KPI 데이터 정렬 제안 (kpi_gap만 — 본인 데이터라 바로 처리) ──
    my_kpi_gaps = (
        SUPA.table("kpi_alignment_suggestions").select("*")
        .eq("person", my_name).eq("status", "open").eq("suggestion_type", "kpi_gap")
        .order("created_at", desc=True).execute().data
    )
    if my_kpi_gaps:
        st.info(f"🧭 **내 KPI 추적 관련 제안이 있어요** — {len(my_kpi_gaps)}건 (Claude가 목표랑 실제 데이터를 비교해서 찾은 것)")
        for g in my_kpi_gaps:
            with st.container(border=True):
                st.write(g["suggestion_text"])
                gl1, gl2 = st.columns([3, 1])
                sheet_link = gl1.text_input(
                    "이 KPI를 추적할 구글시트 링크(있으면)", key=f"kpigap_link_{g['id']}",
                    placeholder="https://docs.google.com/spreadsheets/...", label_visibility="collapsed",
                )
                if gl2.button("등록", key=f"kpigap_register_{g['id']}", use_container_width=True):
                    if sheet_link.strip():
                        SUPA.table("kpi_data_sources").insert({
                            "person": my_name, "related_suggestion_text": g["suggestion_text"],
                            "source_url": sheet_link.strip(),
                        }).execute()
                    SUPA.table("kpi_alignment_suggestions").update({"status": "applied"}).eq("id", g["id"]).execute()
                    st.success("등록 완료! 다음부터 이 소스를 참고해서 분석할게요.")
                    st.rerun()
                if st.button("아직 없어요 / 나중에", key=f"kpigap_skip_{g['id']}"):
                    SUPA.table("kpi_alignment_suggestions").update({"status": "dismissed"}).eq("id", g["id"]).execute()
                    st.rerun()

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


with tab_okr:
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

                    # ── 요약 통계바 (옛 OKR목표관리 페이지의 "관리중업무/지연/주의/확정된목표/달성" 이식) ──
                    today_d = date.today()
                    total_cnt = len(person_items)
                    confirmed_cnt = sum(1 for it in person_items if it.get("confirmed"))
                    overdue_cnt = sum(
                        1 for it in person_items
                        if it.get("due_date") and pd.to_datetime(it["due_date"]).date() < today_d and not it.get("confirmed")
                    )
                    soon_cnt = sum(
                        1 for it in person_items
                        if it.get("due_date") and not it.get("confirmed")
                        and today_d <= pd.to_datetime(it["due_date"]).date() <= today_d + timedelta(days=3)
                    )
                    achieved_cnt = sum(
                        1 for it in person_items
                        if it.get("confirmed") or (float(it.get("target_qty") or 0) > 0 and float(it.get("progress") or 0) >= float(it.get("target_qty") or 0))
                    )
                    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
                    sc1.metric("관리 중 업무", f"{total_cnt}건")
                    sc2.metric("지연", f"{overdue_cnt}건", delta="확인 필요" if overdue_cnt else None, delta_color="inverse")
                    sc3.metric("주의(3일내 마감)", f"{soon_cnt}건")
                    sc4.metric("확정된 목표", f"{confirmed_cnt}/{total_cnt}")
                    sc5.metric("🏆 달성", f"{achieved_cnt}건")

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
                        due_txt = ""
                        if it.get("due_date"):
                            d_date = pd.to_datetime(it["due_date"]).date()
                            if not it.get("confirmed") and d_date < date.today():
                                due_txt = f" · ⚠️ 마감 {d_date} (지연)"
                            else:
                                due_txt = f" · 마감 {d_date}"
                        with st.container(border=True):
                            st.markdown(f"{conf} **[{it.get('category') or '미분류'}]** {it['title']}{progress_txt}{due_txt}")
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



with tab_log:
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


with tab_campaign:
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


with tab_finance:
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
    # 📥 인플루언서 송금정보 — 구글시트에서 바로 읽어오기
    # ══════════════════════════════════════════════════════════
    st.subheader("📥 인플루언서 송금정보 (구글시트에서 바로 읽어오기)")
    st.caption(
        "열 순서가 시트마다 달라도 괜찮아요 — Claude가 각 행의 내용을 보고 이름·금액·결제수단·링크를 알아서 찾아냅니다. "
        "같은 콘텐츠를 다시 올려도 중복 등록되지 않아요."
    )
    PAYMENT_TEMPLATE_CSV = (
        "이름,금액,결제수단,콘텐츠링크,방문일,업로드일,송금예정일,신분증링크\n"
        "홍길동,150000,하나은행 123-456789-01,https://instagram.com/p/xxxx,2026-10-01,2026-10-05,2026-10-10,https://drive.google.com/...\n"
    )
    dl1, dl2 = st.columns([1, 3])
    dl1.download_button(
        "📋 표준 양식 다운로드", data=PAYMENT_TEMPLATE_CSV.encode("utf-8-sig"), file_name="송금정보_양식.csv",
        mime="text/csv", key="download_payment_template",
    )
    dl2.caption("이 양식대로 채우시면 가장 정확하게 인식돼요. 다른 형식(기존에 쓰시던 시트)도 AI가 알아서 읽어보려 시도합니다.")

    pay_sheet_url = st.text_input("구글시트 링크", key="payment_sheet_url", placeholder="https://docs.google.com/spreadsheets/d/...")
    pay_sheet_file = st.file_uploader(
        "또는 엑셀(.xlsx)/CSV 파일로 올리기 (링크 공유가 어려울 때)", type=["xlsx", "csv"], key="payment_sheet_file",
    )
    if st.button("1단계: 시트 구조 확인", key="payment_sheet_load"):
        all_sheets, err_title, err_fix = None, None, None
        if pay_sheet_file is not None:
            all_sheets, err_title = _read_uploaded_sheet_file(pay_sheet_file)
        elif pay_sheet_url.strip():
            all_sheets, err_title, err_fix = _fetch_google_sheet(pay_sheet_url)
        else:
            err_title = "링크를 붙여넣거나 파일을 올려주세요."
        if all_sheets is None:
            st.error(f"❌ {err_title}" + (f"\n\n{err_fix}" if err_fix else ""))
        else:
            for i, (_nm, _df) in enumerate(all_sheets.items()):  # 탭마다 제목줄 후보를 미리 채워둔다(사용자가 고칠 수 있음)
                st.session_state[f"hdr_rows_{i}"] = ", ".join(str(n) for n in _detect_header_rows(_df))
                st.session_state[f"hdr_skip_{i}"] = bool(_df.empty)
            with st.spinner("Claude가 열 구성을 파악하는 중..."):
                mapping_desc, mapping_err = _ai_infer_column_mapping(_collect_sections(all_sheets))
            st.session_state["payment_all_sheets"] = all_sheets
            if mapping_desc:
                st.session_state["payment_mapping_desc"] = mapping_desc
            else:
                st.session_state["payment_mapping_desc"] = f"(자동 파악 실패: {mapping_err} — 그냥 2단계에서 바로 추출을 시도해볼게요)"
                st.warning(f"⚠️ 열 구조 파악 실패 — {mapping_err}")
            st.session_state.pop("payment_rows_preview", None)

    mapping_desc = st.session_state.get("payment_mapping_desc")
    if mapping_desc and st.session_state.get("payment_all_sheets") is not None:
        st.info(f"🧐 **제가 파악한 열 구성이에요 — 맞는지 봐주세요:**\n\n{mapping_desc}")
        st.markdown("**🗂️ 탭별 표 구간 확인** — 한 탭 안에서 제목줄(헤더)이 중간에 또 나오면, 제목줄 행 번호를 모두 적어주세요.")
        for i, (sheet_name, sheet_df) in enumerate(st.session_state["payment_all_sheets"].items()):
            heads = _parse_row_numbers(st.session_state.get(f"hdr_rows_{i}", ""), len(sheet_df)) or [1]
            with st.expander(f"탭 '{sheet_name}' ({len(sheet_df)}행) — 제목줄 {len(heads)}개로 인식", expanded=len(heads) > 1):
                hc1, hc2 = st.columns([3, 1])
                hc1.text_input("제목줄(헤더) 행 번호 — 여러 개면 쉼표로 (예: 1, 22)", key=f"hdr_rows_{i}")
                hc2.checkbox("이 탭은 제외", key=f"hdr_skip_{i}")
                preview = sheet_df.head(80).fillna("").astype(str).copy()
                preview.columns = [_col_letter(j) for j in range(preview.shape[1])]
                preview.insert(0, "행", range(1, len(preview) + 1))
                preview.insert(1, " ", ["◀ 제목줄" if n in heads else "" for n in preview["행"]])
                st.dataframe(preview, hide_index=True, use_container_width=True)
                if len(sheet_df) > 80:
                    st.caption(f"(앞 80행만 보여드려요. 80행 뒤에 제목줄이 또 있으면 행 번호를 직접 적어주세요.)")
        if st.button("🔄 제목줄을 바꿨어요 — 열 구성 다시 파악", key="remap_sections"):
            with st.spinner("Claude가 열 구성을 다시 파악하는 중..."):
                _desc, _err = _ai_infer_column_mapping(_collect_sections(st.session_state["payment_all_sheets"]))
            st.session_state["payment_mapping_desc"] = _desc or f"(자동 파악 실패: {_err} — 그냥 2단계에서 바로 추출을 시도해볼게요)"
            st.rerun()
        mapping_correction = st.text_input(
            "다르면 바로잡아주세요(선택)", key="mapping_correction",
            placeholder="예: A열은 이름이 아니라 방문 장소예요, 이름은 C열이에요",
        )
        mc1, mc2 = st.columns(2)
        if mc1.button("✅ 맞아요, 전체 추출 진행", key="confirm_mapping_proceed", type="primary", use_container_width=True):
            all_sheets = st.session_state["payment_all_sheets"]
            pay_rows, skipped_rows = [], 0
            extract_report = {"errors": [], "reasons": {}}
            existing_keys = {
                r["dedup_key"] for r in SUPA.table("payment_requests").select("dedup_key").execute().data
                if r.get("dedup_key")
            }
            with st.spinner("Claude가 전체 내용을 읽는 중..."):
                for _label, raw_df in _collect_sections(all_sheets).items():
                    if raw_df.empty:
                        continue
                    rows, n_skip = _ai_extract_payment_rows(
                        raw_df, existing_keys, extra_hint=mapping_correction.strip() or None,
                        report=extract_report,
                    )
                    pay_rows.extend(rows)
                    skipped_rows += n_skip
            reason_lines = "".join(f"\n- {k}: {v}행" for k, v in extract_report["reasons"].items())
            if not pay_rows:
                # 0건이면 화면을 초기화하지 않고(=다시 시도할 수 있게) 이유를 그대로 보여준다
                err_lines = "".join(f"\n- {e}" for e in dict.fromkeys(extract_report["errors"]))
                st.error(
                    "❌ 새로 인식된 송금 건이 0건이에요. 아래 이유를 확인해주세요." + (f"\n\n**오류**{err_lines}" if err_lines else "")
                    + (f"\n\n**건너뛴 이유**{reason_lines}" if reason_lines else "")
                    + "\n\n제목줄 행 번호나 위의 '열 구성 보정'을 고친 뒤 다시 눌러보세요."
                )
            else:
                msg = f"✅ {len(pay_rows)}명 새로 인식됨."
                if skipped_rows:
                    msg += f" (건너뜀 {skipped_rows}행){reason_lines}"
                if extract_report["errors"]:
                    msg += "\n\n⚠️ 일부 구간은 처리하지 못했어요:" + "".join(f"\n- {e}" for e in dict.fromkeys(extract_report["errors"]))
                st.session_state["payment_rows_preview"] = pay_rows
                st.session_state["payment_extract_msg"] = msg
                st.session_state.pop("payment_mapping_desc", None)
                st.session_state.pop("payment_all_sheets", None)
                st.rerun()
        if mc2.button("❌ 다시 확인 (취소)", key="cancel_mapping", use_container_width=True):
            st.session_state.pop("payment_mapping_desc", None)
            st.session_state.pop("payment_all_sheets", None)
            st.rerun()

    st.markdown("**또는, 더 간단하게:**")
    with st.expander("📷 스크린샷으로 대신 올리기 (시트 링크가 번거로우면 이쪽이 더 쉬워요)"):
        st.caption("송금 정보가 보이는 화면을 캡처해서 올리면, Claude가 읽어서 자동으로 채워드려요. 여러 장 올려도 됩니다.")
        shot_files = st.file_uploader(
            "스크린샷 업로드", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="payment_screenshot_up",
        )
        if shot_files and st.button("스크린샷 읽기", key="payment_screenshot_read"):
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                st.error("ANTHROPIC_API_KEY가 설정되어 있지 않아 이 기능은 못 써요.")
            else:
                existing_keys = {
                    r["dedup_key"] for r in SUPA.table("payment_requests").select("dedup_key").execute().data
                    if r.get("dedup_key")
                }
                shot_rows = []
                with st.spinner("Claude가 스크린샷을 읽는 중..."):
                    for f in shot_files:
                        img_bytes = f.getvalue()
                        media_type = f.type or "image/png"
                        # 전체화면 캡처는 해상도가 너무 커서 API가 거부(400)하는 경우가 많아, 가로/세로 1568px로 축소
                        try:
                            from PIL import Image
                            img = Image.open(io.BytesIO(img_bytes))
                            img = img.convert("RGB")
                            max_dim = 1568
                            if max(img.size) > max_dim:
                                ratio = max_dim / max(img.size)
                                img = img.resize((int(img.width * ratio), int(img.height * ratio)))
                            buf = io.BytesIO()
                            img.save(buf, format="JPEG", quality=85)
                            img_bytes = buf.getvalue()
                            media_type = "image/jpeg"
                        except Exception as resize_err:
                            st.caption(f"{f.name}: 리사이즈 건너뜀({resize_err}), 원본으로 시도")
                        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                        sys_prompt = (
                            "이 이미지는 인플루언서 송금 정보 화면(또는 메시지)이다. 다음 정보를 찾아서 JSON으로만 출력해라: "
                            "{\"influencer_name\": \"...\", \"amount\": 숫자(원화 기준, 콤마/₩ 제외), "
                            "\"payment_method_raw\": \"은행명+계좌번호 또는 PayPal 이메일 등 보이는 그대로\", "
                            "\"content_link\": \"콘텐츠 링크 있으면, 없으면 null\"}. "
                            "확실하지 않은 값은 null로 둬라. 다른 텍스트는 절대 포함하지 마라."
                        )
                        try:
                            r = requests.post(
                                "https://api.anthropic.com/v1/messages",
                                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                                json={
                                    "model": "claude-sonnet-5", "max_tokens": 500, "system": sys_prompt,
                                    "messages": [{"role": "user", "content": [
                                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                                        {"type": "text", "text": "이 이미지에서 송금정보를 추출해줘."},
                                    ]}],
                                },
                                timeout=30,
                            )
                            if r.status_code >= 300:
                                st.warning(f"{f.name}: 읽기 실패 ({r.status_code}) — {r.text[:300]}")
                                continue
                            text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
                            if text.startswith("```"):
                                text = text.strip("`")
                                if text.startswith("json"):
                                    text = text[4:]
                            d = json.loads(text)
                            amount = _clean_number(d.get("amount"))
                            if not d.get("influencer_name") or amount is None:
                                st.warning(f"{f.name}: 이름/금액을 못 읽었어요. 직접 입력 폼을 이용해주세요.")
                                continue
                            payment_method_raw = d.get("payment_method_raw")
                            paypal_email = _extract_email(payment_method_raw)
                            content_link = d.get("content_link")
                            dedup_src = f"{content_link or ''}||{amount}"
                            dedup_key = hashlib.md5(dedup_src.encode("utf-8")).hexdigest()
                            if dedup_key in existing_keys:
                                st.caption(f"{f.name}: 이미 등록된 것 같아 건너뜀")
                                continue
                            shot_rows.append({
                                "influencer_name": d.get("influencer_name"), "tiktok_url": None, "instagram_url": None,
                                "visit_date": None, "upload_date": None, "content_link": content_link,
                                "payment_method_raw": payment_method_raw, "id_doc_link": None,
                                "amount": amount, "scheduled_date": None,
                                "paypal_email": paypal_email, "notification_email": None,
                                "payment_destination_verified": bool(payment_method_raw),
                                "dedup_key": dedup_key,
                            })
                        except Exception as e:
                            st.warning(f"{f.name}: 오류 ({e})")
                if shot_rows:
                    st.session_state["payment_rows_preview"] = (
                        st.session_state.get("payment_rows_preview") or []
                    ) + shot_rows
                    st.success(f"{len(shot_rows)}건 인식됨. 아래에서 확인해주세요.")
                    st.rerun()

    pay_preview = st.session_state.get("payment_rows_preview")
    if st.session_state.get("payment_extract_msg") and pay_preview:
        st.success(st.session_state["payment_extract_msg"])
    if pay_preview:
        REQUIRED_FIELDS = ["influencer_name", "amount", "payment_method_raw", "content_link", "id_doc_link", "scheduled_date", "brand_names"]
        FIELD_LABEL = {
            "influencer_name": "이름", "amount": "금액", "payment_method_raw": "결제수단",
            "content_link": "콘텐츠링크", "id_doc_link": "신분증링크", "scheduled_date": "송금예정일",
            "brand_names": "참여 브랜드",
        }

        def _missing_fields(r):
            return [f for f in REQUIRED_FIELDS if not r.get(f)]

        st.warning(
            "📋 **완벽한 보고만 등록할 수 있어요** — 이름·금액·결제수단·콘텐츠링크·신분증링크·송금예정일·통화·참여브랜드가 "
            "전부 채워져야 등록됩니다. 해외송금에서 정보 하나라도 안 맞으면 신청 자체가 막히는 것과 같은 원리예요."
        )
        st.markdown(f"**{len(pay_preview)}건 확인 중** — 빠진 항목은 아래에서 바로 채워주세요.")

        complete_rows = []
        for idx, r in enumerate(pay_preview):
            missing = _missing_fields(r)
            with st.container(border=True):
                c1, c2 = st.columns([2, 1])
                c1.markdown(f"**{r.get('influencer_name') or '(이름없음)'}** · {r.get('amount') or '-'}")
                c1.caption(f"💳 결제수단: {r.get('payment_method_raw') or '-'}")
                if r.get("paypal_email"):
                    c1.caption(f"⚠️ 페이팔 결제 계정(실제 송금 대상): **{r['paypal_email']}** — 안내메일 주소와 다를 수 있어요!")
                elif r.get("payment_method_raw"):
                    c1.warning("⏳ 페이팔이 아니라서 송금까지 **최대 1개월** 걸릴 수 있어요 — 별도 송금일정으로 처리됩니다.")

                if missing:
                    st.error(f"🚫 빠진 항목: {', '.join(FIELD_LABEL[f] for f in missing)} — 채워야 등록 가능")

                # 빠진 필드를 그 자리에서 바로 채울 수 있게
                if "content_link" in missing:
                    r["content_link"] = st.text_input("콘텐츠 링크", key=f"fix_content_{idx}", placeholder="인스타/틱톡 업로드 링크") or None
                if "id_doc_link" in missing:
                    r["id_doc_link"] = st.text_input("신분증 사본 링크", key=f"fix_iddoc_{idx}", placeholder="구글드라이브 링크 등") or None
                if "scheduled_date" in missing:
                    fixed_date = st.date_input("송금예정일", value=None, key=f"fix_date_{idx}")
                    r["scheduled_date"] = fixed_date.isoformat() if fixed_date else None
                if "payment_method_raw" in missing:
                    r["payment_method_raw"] = st.text_input("결제수단(은행명+계좌번호 또는 PayPal 이메일)", key=f"fix_pm_{idx}") or None
                    r["paypal_email"] = _extract_email(r["payment_method_raw"])
                if "brand_names" in missing:
                    r["brand_names"] = st.text_input(
                        "참여 브랜드 (콤마로 여러개 가능)", key=f"fix_brands_{idx}",
                        placeholder="예: 브랜드A, 브랜드B",
                    ) or None

                r["currency"] = c2.selectbox(
                    "통화 *", ["KRW", "USD", "EUR", "GBP", "JPY"], key=f"currency_{idx}",
                    help="추측하지 않습니다 — 실제 지급 통화를 정확히 선택해주세요.",
                )
                notif_email = c2.text_input(
                    "안내메일 받을 주소(선택)", value=r.get("notification_email") or "",
                    key=f"notif_email_{idx}", placeholder="비워두면 자동메일 발송 안 함",
                )
                r["notification_email"] = notif_email.strip() or None
                proposal_url = c2.text_input(
                    "지출기안서 링크(선택, 추후 필수화 예정)", value=r.get("expense_proposal_url") or "",
                    key=f"proposal_{idx}",
                )
                r["expense_proposal_url"] = proposal_url.strip() or None
                contract_url = c2.text_input("계약서 링크(있으면)", value=r.get("contract_link") or "", key=f"contract_{idx}")
                r["contract_link"] = contract_url.strip() or None

                cc1, cc2 = c2.columns(2)
                r["id_doc_confirmed"] = cc1.checkbox("신분증 확인함", key=f"iddoc_confirm_{idx}")
                r["contract_confirmed"] = cc2.checkbox("계약서 확인함(또는 해당없음)", key=f"contract_confirm_{idx}")

                pay_preview[idx] = r
                fully_checked = not _missing_fields(r) and r["id_doc_confirmed"] and r["contract_confirmed"]
                if not fully_checked:
                    missing_checks = []
                    if not r["id_doc_confirmed"]:
                        missing_checks.append("신분증 확인")
                    if not r["contract_confirmed"]:
                        missing_checks.append("계약서 확인")
                    if missing_checks and not missing:
                        st.caption(f"☝️ 체크 필요: {', '.join(missing_checks)}")
                if fully_checked:
                    complete_rows.append(r)

        st.session_state["payment_rows_preview"] = pay_preview
        valid_rows = complete_rows

        if valid_rows:
            batch_total = sum(float(r.get("amount") or 0) for r in valid_rows)
            by_currency = {}
            for r in valid_rows:
                cur = r.get("currency", "KRW")
                by_currency[cur] = by_currency.get(cur, 0) + float(r.get("amount") or 0)
            total_line = " · ".join(f"{cur} {amt:,.0f}" for cur, amt in by_currency.items())
            st.success(f"✅ 완벽하게 채워진 {len(valid_rows)}건 — 등록 가능합니다.")
            st.markdown(f"### 💰 이번 신청 전체 송금규모: {total_line}")
            confirm_total = st.number_input(
                "위 합계가 맞는지, 금액을 다시 한번 직접 입력해서 확인해주세요 (통화 섞여있으면 대표 통화 기준 숫자만)",
                min_value=0.0, step=1.0, key="confirm_batch_total",
            )
            total_matches = abs(confirm_total - batch_total) < 1 if len(by_currency) == 1 else True
            if len(by_currency) > 1:
                st.caption("통화가 여러 개 섞여있어서 합계 재확인은 생략하고 통화별 금액만 참고해주세요.")
            elif not total_matches:
                st.error(f"입력하신 금액이 합계(₩{batch_total:,.0f})와 달라요 — 다시 확인해주세요.")

            if st.button("🔍 이미 송금한 내역과 겹치는지 확인하기", key="check_dup_paid"):
                paid_history = SUPA.table("payment_requests").select("*").eq("status", "paid").execute().data
                bank_hits_total = 0
                for r in valid_rows:
                    name = r.get("influencer_name") or ""
                    amt = r.get("amount") or 0
                    matches = [
                        p for p in paid_history
                        if p["influencer_name"] == name and abs(float(p.get("amount") or 0) - amt) < 1000
                    ]
                    bank_matches = (
                        SUPA.table("bank_transactions").select("txn_date,amount,description")
                        .ilike("description", f"%{name}%").eq("direction", "out").execute().data
                        if name else []
                    )
                    if matches or bank_matches:
                        bank_hits_total += 1
                        st.warning(f"⚠️ **{name}** (₩{amt:,.0f}) — 비슷한 기존 기록 발견:")
                        for m in matches:
                            st.caption(f"  · 이미 송금처리됨: {m.get('paid_at', '')[:10]} · ₩{float(m['amount']):,.0f}")
                        for b in bank_matches[:3]:
                            st.caption(f"  · 은행거래 유사건: {b.get('txn_date')} · ₩{float(b['amount']):,.0f} · {b.get('description')}")
                if bank_hits_total == 0:
                    st.success("겹치는 기존 내역을 못 찾았어요 (완전히 새로운 건으로 보여요).")

            double_check = st.checkbox("위 내용을 확인했고, 이미 송금한 내역과 안 겹치는 걸 확인했습니다", key="payment_double_check")
            register_disabled = not double_check or (len(by_currency) == 1 and not total_matches)
            if st.button(f"✅ 이 {len(valid_rows)}건 일괄 등록", type="primary", key="payment_sheet_register", disabled=register_disabled):
                batch_id = str(uuid.uuid4())
                all_brands = set()
                for r in valid_rows:
                    SUPA.table("payment_requests").insert({
                        "influencer_name": r.get("influencer_name"),
                        "paypal_email": r.get("paypal_email"), "notification_email": r.get("notification_email"),
                        "amount": r.get("amount"),
                        "scheduled_date": r.get("scheduled_date"),
                        "visit_date": r.get("visit_date"), "upload_date": r.get("upload_date"),
                        "tiktok_url": r.get("tiktok_url"), "instagram_url": r.get("instagram_url"),
                        "payment_method_raw": r.get("payment_method_raw"),
                        "content_link": r.get("content_link"), "id_doc_link": r.get("id_doc_link"),
                        "contract_link": r.get("contract_link"), "brand_names": r.get("brand_names"),
                        "id_doc_confirmed": r.get("id_doc_confirmed"), "contract_confirmed": r.get("contract_confirmed"),
                        "currency": r.get("currency", "KRW"), "expense_proposal_url": r.get("expense_proposal_url"),
                        "dedup_key": r.get("dedup_key"), "double_checked": True, "batch_id": batch_id,
                        "payment_destination_verified": True, "report_complete": True,
                        "submitted_by": my_name,
                    }).execute()
                    for b in (r.get("brand_names") or "").split(","):
                        if b.strip():
                            all_brands.add(b.strip())

                # 마진율 관리를 위해 구정회에게 지출포인트 공유 (DB 저장 + 할일로 알림)
                brands_txt = ", ".join(sorted(all_brands)) if all_brands else "미지정"
                SUPA.table("assigned_tasks").insert({
                    "person": "구정회", "category": "마진데이터",
                    "title": f"[지출발생] {brands_txt} · 총 {total_line} · {len(valid_rows)}건 — 마진율 반영 필요",
                }).execute()

                st.session_state.pop("payment_rows_preview", None)
                st.session_state["payment_double_check"] = False
                st.success(f"{len(valid_rows)}건 등록 완료! 대표님 재무캘린더에서 송금 처리해주실 거고, 구정회님께도 마진데이터 알림 보냈어요.")
                st.rerun()

    # 재확인용: 내가 등록한 것만 보여줌 (송금 처리/완료 버튼은 재무캘린더=대표 전용)
    my_pending_payments = (
        SUPA.table("payment_requests").select("*").eq("status", "pending")
        .eq("submitted_by", my_name).order("scheduled_date").execute().data
    )
    if my_pending_payments:
        st.markdown(f"**💸 내가 등록한 송금요청 — 재확인용 ({len(my_pending_payments)}건, 대표님 처리 대기중)**")
        confirm_df = pd.DataFrame([{
            "이름": p["influencer_name"], "금액": f"₩{float(p['amount']):,.0f}" if p.get("amount") else "-",
            "예정일": p.get("scheduled_date") or "-",
            "콘텐츠링크": "✅" if p.get("content_link") else "⚠️ 없음",
            "신분증": "✅" if p.get("id_doc_link") else "⚠️ 없음",
        } for p in my_pending_payments])
        st.dataframe(confirm_df, hide_index=True, use_container_width=True)
        st.caption("내용이 틀렸으면 구글시트 수정 후 다시 불러와서 등록해주세요. 송금 완료 처리는 대표님이 재무캘린더에서 하시면 자동으로 알림 메일이 나가요.")


with tab_mywork:
    # ══════════════════════════════════════════════════════════
    # 📇 B2B 브랜드 관리 (세일즈) — 캘린더·계정·이슈·캠페인 주차루틴
    # ══════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════
    # 🧰 내 업무 도구 (역할별로 다른 화면이 뜹니다 — 다른 사람 도구는 안 보여요)
    # ══════════════════════════════════════════════════════════
    st.subheader("🧰 내 업무 도구")

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

        tab_reg, tab_big, tab_fc, tab_cal, tab_acc, tab_issue, tab_camp = st.tabs(["📝 캠페인 등록", "🗓️ 큰 캘린더", "🔮 다음달 예측", "📅 일정 한눈에보기", "🏢 계정 관리", "🐛 이슈", "🚀 캠페인·주차루틴"])

        # ── 📅 일정 한눈에보기 ──────────────────────────────────
        with tab_big:
            st.markdown("**캠페인 일정 큰 캘린더** — 여러 캠페인이 같은 날 겹쳐도 색깔로 구분돼서 한눈에 보여요. (수정은 '🚀 캠페인·주차루틴' 탭에서)")
            _camps = {c["id"]: c for c in load_sales_campaigns()}
            _my_ids = {a["id"] for a in my_accounts}
            cal_events = []
            for t in load_sales_campaign_tasks():
                camp = _camps.get(t["campaign_id"])
                if not camp or camp["account_id"] not in _my_ids or not t.get("due_date"):
                    continue
                brand = account_by_id.get(camp["account_id"], {}).get("brand_name", "?")
                cal_events.append({
                    "date": date.fromisoformat(str(t["due_date"])[:10]), "label": f"{brand} {t['week_number']}주차",
                    "full": f"[{brand}] {camp['campaign_name']} · {t['week_number']}주차 {t['task_title']} ({t['status']})",
                    "key": camp["id"], "done": t["status"] == "완료", "brand": brand, "campaign": camp["campaign_name"],
                })
            for a in my_accounts:
                if a.get("renewal_date"):
                    cal_events.append({
                        "date": date.fromisoformat(str(a["renewal_date"])[:10]), "label": f"🔁 {a['brand_name']} 갱신",
                        "full": f"{a['brand_name']} 갱신/온보딩일", "key": f"renew-{a['id']}", "done": False,
                        "brand": a["brand_name"], "campaign": "갱신/온보딩",
                    })

            today_d = date.today()
            ym = st.session_state.setdefault("bigcal_ym", (today_d.year, today_d.month))
            nv1, nv2, nv3, nv4 = st.columns([1, 1, 1, 4])
            if nv1.button("◀ 이전 달", key="bigcal_prev", use_container_width=True):
                y, m = st.session_state["bigcal_ym"]
                st.session_state["bigcal_ym"] = (y - 1, 12) if m == 1 else (y, m - 1)
                st.rerun()
            if nv2.button("오늘", key="bigcal_today", use_container_width=True):
                st.session_state["bigcal_ym"] = (today_d.year, today_d.month)
                st.rerun()
            if nv3.button("다음 달 ▶", key="bigcal_next", use_container_width=True):
                y, m = st.session_state["bigcal_ym"]
                st.session_state["bigcal_ym"] = (y + 1, 1) if m == 12 else (y, m + 1)
                st.rerun()
            cy, cm = st.session_state["bigcal_ym"]
            nv4.markdown(f"### {cy}년 {cm}월")

            all_brands = sorted({e["brand"] for e in cal_events})
            f1, f2 = st.columns([3, 1])
            pick_brands = f1.multiselect("브랜드 필터 (비우면 전체)", all_brands, key="bigcal_brands")
            show_done = f2.checkbox("완료한 일정도 보기", value=True, key="bigcal_done")
            shown = [e for e in cal_events if (not pick_brands or e["brand"] in pick_brands) and (show_done or not e["done"])]

            cal_html, color_of = _render_month_calendar(shown, cy, cm, today_d)
            st.markdown(cal_html, unsafe_allow_html=True)
            if not shown:
                st.caption("표시할 일정이 없어요. 캠페인을 등록하면 주차별 일정이 여기에 나타나요.")
            else:
                legend = "".join(
                    f"<span style='display:inline-block;margin:2px 8px 2px 0;padding:1px 8px;border-radius:4px;border-left:3px solid {color_of[k]};"
                    f"background:{color_of[k]}33;font-size:12px'>{html.escape(name)}</span>"
                    for k, name in dict.fromkeys((e["key"], f"{e['brand']} · {e['campaign']}") for e in shown)
                )
                st.markdown(legend, unsafe_allow_html=True)
                month_rows = sorted([e for e in shown if e["date"].year == cy and e["date"].month == cm], key=lambda e: e["date"])
                with st.expander(f"이번 달 일정 목록 ({len(month_rows)}건)"):
                    if month_rows:
                        st.dataframe(pd.DataFrame([{
                            "날짜": e["date"].isoformat(), "브랜드": e["brand"], "캠페인": e["campaign"], "내용": e["full"],
                        } for e in month_rows]), hide_index=True, use_container_width=True)
                    else:
                        st.caption("이번 달에는 일정이 없어요.")

        with tab_fc:
            _t = date.today()
            _ny, _nm = _month_add(_t.year, _t.month, 1)
            st.markdown(f"**{_ny}년 {_nm}월 캠페인 예측** — 등록된 캠페인·계정 정보만으로 계산해요. 근거가 없으면 만들어내지 않고 '낮음'으로 둡니다.")
            fc_rows = _forecast_next_month(my_accounts, load_sales_campaigns(), load_sales_campaign_tasks(), _t)
            confirmed = [r for r in fc_rows if r["level"] == "확정"]
            high = [r for r in fc_rows if r["level"] == "높음"]
            mid = [r for r in fc_rows if r["level"] == "중간"]
            low = [r for r in fc_rows if r["level"] == "낮음"]
            _sum = lambda rs: sum(r["budget"] or 0 for r in rs)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("✅ 확정(등록됨)", f"{len(confirmed)}건", f"₩{_sum(confirmed):,.0f}", delta_color="off")
            m2.metric("🟢 가능성 높음", f"{len(high)}건", f"₩{_sum(high):,.0f}", delta_color="off")
            m3.metric("🟡 가능성 중간", f"{len(mid)}건", f"₩{_sum(mid):,.0f}", delta_color="off")
            m4.metric("🔴 낮음/불확실", f"{len(low)}건")
            st.caption("금액은 '🏢 계정 관리'에 적힌 월 예산 기준이에요. 월 예산이 비어 있는 브랜드는 0원으로 계산돼요.")

            if not fc_rows:
                st.info("예측할 브랜드 계정이 아직 없어요. '🏢 계정 관리'에서 담당 브랜드를 등록하고, 캠페인을 등록하면 여기에 나타나요.")
            elif not confirmed:
                todo = [r["brand"] for r in high + mid]
                st.error(
                    f"⚠️ {_ny}년 {_nm}월에 확정된 캠페인이 아직 없어요. "
                    + (f"지금 견적·계약을 챙겨야 할 브랜드: **{', '.join(todo)}**" if todo else "가능성이 높은 브랜드도 없어서, 신규 수주가 필요해요.")
                )
            elif not high and not mid:
                st.success(f"{_ny}년 {_nm}월 캠페인 {len(confirmed)}건이 확정돼 있어요.")

            if fc_rows:
                icon = {"확정": "✅ 확정", "높음": "🟢 높음", "중간": "🟡 중간", "낮음": "🔴 낮음"}
                st.dataframe(pd.DataFrame([{
                    "상태": icon[r["level"]], "브랜드": r["brand"], "예상 오픈일": r["pred_open"].isoformat() if r["pred_open"] else "-",
                    "월 예산": (f"₩{r['budget']:,.0f}" if r["budget"] else "미입력"), "근거": r["reason"], "담당": r["owner"],
                } for r in fc_rows]), hide_index=True, use_container_width=True)
                no_budget = [r["brand"] for r in fc_rows if r["budget_missing"] and r["level"] in ("확정", "높음", "중간")]
                if no_budget:
                    st.caption(f"💡 월 예산이 비어 있는 브랜드: {', '.join(no_budget)} — '🏢 계정 관리'에 적어두면 예상 매출이 정확해져요.")

            # 최근 6개월 + 다음달 캠페인 수: '한 달 달리고 한 달 쉬는' 패턴이 있는지 한눈에 보기
            _camps_all = [c for c in load_sales_campaigns() if c.get("account_id") in {a["id"] for a in my_accounts} and c.get("open_date")]
            _cnt = {}
            for c in _camps_all:
                k = str(c["open_date"])[:7]
                _cnt[k] = _cnt.get(k, 0) + 1
            _months = [_month_add(_t.year, _t.month, i) for i in range(-5, 2)]
            _labels = [f"{y}-{m:02d}" for y, m in _months]
            _series = [_cnt.get(l, 0) for l in _labels]
            _series[-1] = len(confirmed)  # 다음달은 '확정'만 센다
            if sum(_series) > 0:
                st.markdown("**월별 캠페인 시작 건수** (마지막 달 = 다음달 확정 건수)")
                st.bar_chart(pd.DataFrame({"캠페인 수": _series}, index=_labels))

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
                    if a.get("contract_drive_url"):
                        st.caption(f"📎 [계약서/관련파일]({a['contract_drive_url']})")
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
        with tab_reg:
            st.markdown("**캠페인 등록 → 4주 루틴 자동 생성**")
            with st.expander("🚀 새 캠페인 등록", expanded=True):
                cv = st.session_state.setdefault("camp_new_ver", 0)  # 등록 성공 후 입력칸을 비우려고 key에 붙이는 번호
                if st.session_state.get("camp_new_msg"):
                    st.success(st.session_state.pop("camp_new_msg"))
                acc_names2 = {a["brand_name"]: a["id"] for a in my_accounts}
                NEW_BRAND = "➕ 새 브랜드 직접 입력"
                camp_brand = st.selectbox("브랜드", list(acc_names2.keys()) + [NEW_BRAND], key="camp_brand_pick")
                new_brand_name = ""
                if camp_brand == NEW_BRAND:
                    new_brand_name = st.text_input(
                        "새 브랜드명 *", key=f"camp_new_brand_{cv}",
                        help="등록하면 '🏢 계정 관리'에도 내 담당 브랜드로 자동 추가돼요.",
                    )
                    if not acc_names2:
                        st.caption("아직 등록된 브랜드 계정이 없어서, 여기서 브랜드명을 쓰면 계정도 같이 만들어져요.")
                camp_name = st.text_input("캠페인명 *", placeholder="예: 9월 명동 오픈 캠페인", key=f"camp_new_name_{cv}")
                camp_open_date = st.date_input("캠페인 오픈일", value=date.today(), key=f"camp_new_open_{cv}")

                st.markdown("**📄 계약서** (선택) — 직접 올리거나, 구글드라이브에서 찾아올 수 있어요")
                cc1, cc2 = st.columns(2)
                camp_contract_file = cc1.file_uploader(
                    "계약서 파일 올리기", type=["pdf", "docx", "png", "jpg", "jpeg"], key=f"camp_new_contract_file_{cv}",
                )
                cc2.caption("브랜드명(과 캠페인명)이 들어간 파일·폴더를 드라이브에서 찾아와요.")
                if cc2.button("🔍 구글드라이브에서 찾아오기", key="camp_new_drive_find", use_container_width=True):
                    with st.spinner("구글드라이브를 훑는 중... (폴더가 많으면 시간이 좀 걸려요)"):
                        _cands, _note, _err = _drive_find_contracts(new_brand_name.strip() if camp_brand == NEW_BRAND else camp_brand, camp_name)
                    st.session_state["camp_drive_result"] = {"brand": camp_brand if camp_brand != NEW_BRAND else new_brand_name.strip(), "cands": _cands, "note": _note, "err": _err}
                    st.session_state.pop(f"camp_drive_pick_{cv}", None)
                    st.session_state.pop("camp_browse", None)

                drive_res = st.session_state.get("camp_drive_result")
                drive_pick = None
                if drive_res:
                    if drive_res["brand"] != (camp_brand if camp_brand != NEW_BRAND else new_brand_name.strip()):
                        st.caption("브랜드를 바꾸셨어요. 아래 결과는 이전 브랜드 기준이라, 다시 '찾아오기'를 눌러주세요.")
                    elif drive_res["err"]:
                        st.error(f"❌ {drive_res['err']}")
                    else:
                        st.caption(drive_res["note"])
                        if not drive_res["cands"]:
                            st.warning("'계약서'가 들어간 폴더도, 브랜드명이 들어간 파일도 못 찾았어요. 폴더·파일 이름을 확인하시거나, 위에서 직접 올려주세요.")
                        else:
                            by_id = {c["id"]: c for c in drive_res["cands"]}
                            pick_id = st.radio(
                                "찾은 폴더·파일 중 골라주세요 (폴더를 고르면 안의 파일이 아래에 나와요)", list(by_id.keys()), index=None,
                                format_func=lambda fid: (
                                        f"📁 {by_id[fid]['name']}  ·  {by_id[fid]['path'] or '(최상위)'}  ·  폴더" if by_id[fid].get("kind") == "folder"
                                        else f"📄 {by_id[fid]['name']}  ·  {by_id[fid]['path'] or '(최상위)'}  ·  수정 {by_id[fid]['modified'] or '-'}"
                                    ),
                                key=f"camp_drive_pick_{cv}",
                            )
                            drive_pick = by_id.get(pick_id)
                            if drive_pick and drive_pick.get("kind") == "folder":
                                # 폴더를 고르면 이 화면 안에서 그 안의 폴더·파일을 보여주고, 파일을 고르게 한다
                                bs = st.session_state.get("camp_browse")
                                if not bs or bs["root"] != pick_id:
                                    bs = {"root": pick_id, "stack": [{"id": pick_id, "name": drive_pick["name"]}]}
                                    st.session_state["camp_browse"] = bs
                                cur = bs["stack"][-1]
                                st.markdown("📂 **" + " › ".join(x["name"] for x in bs["stack"]) + "**")
                                kids, kids_err = _drive_children(cur["id"])
                                drive_pick = None  # 폴더 자체가 아니라, 폴더 안에서 고른 파일만 계약서로 연결한다
                                if len(bs["stack"]) > 1 and st.button("⬆ 상위 폴더로", key=f"camp_up_{cv}"):
                                    bs["stack"].pop()
                                    st.rerun()
                                if kids_err:
                                    st.error(f"❌ {kids_err}")
                                else:
                                    sub_folders = [k for k in kids if k.get("mimeType") == "application/vnd.google-apps.folder"]
                                    sub_files = [k for k in kids if k.get("mimeType") != "application/vnd.google-apps.folder"]
                                    for sf in sub_folders:
                                        if st.button(f"📁 {sf['name']}", key=f"camp_open_{cv}_{sf['id']}"):
                                            bs["stack"].append({"id": sf["id"], "name": sf["name"]})
                                            st.rerun()
                                    if not sub_files:
                                        st.caption("이 폴더에는 파일이 없어요." + (" 위의 폴더를 눌러 안으로 들어가 보세요." if sub_folders else ""))
                                    else:
                                        kid_by_id = {k["id"]: k for k in sub_files}
                                        file_icon = lambda mt: "📊" if "spreadsheet" in (mt or "") else ("📝" if "document" in (mt or "") else "📄")
                                        file_id = st.radio(
                                            f"이 폴더 안의 파일 중 계약서를 골라주세요 ({len(sub_files)}개)", list(kid_by_id.keys()), index=None,
                                            format_func=lambda kid: f"{file_icon(kid_by_id[kid].get('mimeType'))} {kid_by_id[kid]['name']}  ·  수정 {(kid_by_id[kid].get('modifiedTime') or '')[:10] or '-'}",
                                            key=f"camp_file_pick_{cv}_{cur['id']}",
                                        )
                                        if file_id:
                                            kf = kid_by_id[file_id]
                                            drive_pick = {"id": kf["id"], "name": kf["name"], "link": kf.get("webViewLink"), "kind": "file"}

                if st.button("등록 (4주 루틴 자동 생성)", type="primary", key=f"camp_new_submit_{cv}"):
                    if not camp_name.strip():
                        st.error("캠페인명을 입력해주세요.")
                    elif camp_brand == NEW_BRAND and not new_brand_name.strip():
                        st.error("새 브랜드명을 입력해주세요.")
                    else:
                        if camp_brand == NEW_BRAND:
                            nb = new_brand_name.strip()
                            if nb in acc_names2:  # 이미 있는 이름이면 중복 생성하지 않고 그 계정을 쓴다
                                target_account_id = acc_names2[nb]
                            else:
                                target_account_id = SUPA.table("sales_accounts").insert({
                                    "brand_name": nb, "assigned_to": my_name, "status": "운영중",
                                }).execute().data[0]["id"]
                            camp_brand_for_drive = nb
                        else:
                            target_account_id = acc_names2[camp_brand]
                            camp_brand_for_drive = camp_brand
                        camp_res = SUPA.table("sales_campaigns").insert({
                            "account_id": target_account_id, "campaign_name": camp_name.strip(),
                            "open_date": camp_open_date.isoformat(), "created_by": my_name,
                        }).execute()
                        new_camp_id = camp_res.data[0]["id"]
                        week_tasks = [{
                            "campaign_id": new_camp_id, "week_number": wn, "task_title": wt,
                            "task_description": wd, "due_date": (camp_open_date + timedelta(days=(wn - 1) * 7)).isoformat(),
                        } for wn, wt, wd in WEEK_TEMPLATE]
                        SUPA.table("sales_campaign_tasks").insert(week_tasks).execute()
                        msg = f"캠페인 등록 완료! 1~4주차 루틴 {len(week_tasks)}개가 자동으로 만들어졌어요."

                        contract_url, contract_name = None, None
                        if camp_contract_file is not None:  # 직접 올린 파일이 있으면 그걸 우선 사용
                            try:
                                ext = os.path.splitext(camp_contract_file.name)[1].lower()
                                cpath = f"campaign/{new_camp_id}/{uuid.uuid4().hex[:8]}{ext}"
                                SUPA.storage.from_("contract-files").upload(
                                    cpath, camp_contract_file.getvalue(),
                                    {"content-type": camp_contract_file.type or "application/octet-stream"},
                                )
                                contract_url = f"{os.environ.get('SUPABASE_URL')}/storage/v1/object/public/contract-files/{cpath}"
                                contract_name = camp_contract_file.name
                            except Exception as e:
                                st.warning(f"계약서 업로드는 실패했지만 캠페인은 등록됐어요 ({type(e).__name__}: {e})")
                        elif drive_pick and drive_res and drive_res["brand"] == camp_brand_for_drive:
                            contract_url = drive_pick.get("link")
                            contract_name = f"📁 {drive_pick['name']}" if drive_pick.get("kind") == "folder" else drive_pick["name"]
                        if contract_url:
                            try:
                                SUPA.table("sales_campaigns").update({
                                    "contract_url": contract_url, "contract_name": contract_name,
                                }).eq("id", new_camp_id).execute()
                                msg += f" 📄 계약서 연결: {contract_name}"
                            except Exception as e:
                                st.warning(
                                    "캠페인은 등록됐지만 계약서 링크를 저장하지 못했어요. DB에 계약서 칸(contract_url, contract_name)이 "
                                    f"아직 없는 것 같아요 — 관리자에게 알려주세요. ({type(e).__name__}: {e})"
                                )
                        st.session_state["camp_new_msg"] = msg
                        st.session_state["camp_new_ver"] = cv + 1
                        st.session_state.pop("camp_drive_result", None)
                        st.session_state.pop("camp_browse", None)
                        refresh_sales()
                        st.rerun()

        with tab_camp:
            st.markdown("**등록된 캠페인 · 주차 루틴**")
            my_account_ids_camp = {a["id"] for a in my_accounts}
            my_campaigns = [c for c in load_sales_campaigns() if c["account_id"] in my_account_ids_camp]
            if not my_campaigns:
                st.caption("등록된 캠페인이 없습니다.")
            for c in my_campaigns:
                acc = account_by_id.get(c["account_id"], {})
                with st.expander(f"🚀 [{acc.get('brand_name', '?')}] {c['campaign_name']} · 오픈 {c['open_date']} · {c['status']}"):
                    tasks = [t for t in load_sales_campaign_tasks() if t["campaign_id"] == c["id"]]
                    if c.get("contract_url"):
                        st.markdown(f"📄 계약서: [{c.get('contract_name') or '열기'}]({c['contract_url']})")
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


with tab_summary:
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


with tab_org:
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
