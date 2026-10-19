"""화면 번역(한국어 / English / 中文).

app.py 맨 위에서 `i18n.render_switch()`로 언어 버튼을 그리면, 이후 `st.markdown`·`st.button`·`st.selectbox` 같은
화면 함수가 글자를 내보내기 직전에 번역본으로 바꿔 보여준다(app.py의 한국어 원문은 그대로).

번역 순서: ① i18n_data.py(손으로 번역해 둔 기본 사전) → ② DB `i18n_cache`(한 번 번역한 것) → ③ 자동번역(구글 번역 API 또는 Claude)
- 사전/캐시에 없으면 이번 화면은 한국어로 그리고, 화면 맨 끝 `flush()`에서 모아서 한 번에 번역 → 저장 → 화면을 다시 그린다.
- 숫자와 직원 이름은 {0},{1}로 바꾼 '틀'로 찾는다. ("3개 클리어" → "{0}개 클리어")
- 돈·링크·이메일·급여/인건비 관련 문구는 외부 번역 서비스로 보내지 않는다(사전에 있을 때만 번역).
"""
import os
import re
import time

import requests
import streamlit as st

LANGS = {"ko": "한국어", "en": "English", "zh": "中文"}
_HANGUL = re.compile(r"[가-힣]")
_TOKEN = re.compile(r"(김선재|곽재선|구정회|이단우|유원리|가상인턴|장현우)|(\d[\d,]*(?:\.\d+)?)")
_MARK = re.compile(r"\{\d+\}")
_PROTECT = set(LANGS.values())
_NO_SEND = re.compile(r"₩|@|https?:|\d{6,}|급여|인건비|월급|연봉")
_TARGET = {"en": "English", "zh": "Simplified Chinese (简体中文)"}
_GOOGLE_CODE = {"en": "en", "zh": "zh-CN"}

_MEM = {}          # lang -> {틀: 번역}  (DB 캐시를 프로세스에 올려 둔 것)
_MEM_AT = {}       # lang -> 마지막으로 DB에서 읽은 시각
_NEG = {}          # (lang, 틀) -> 번역 실패한 시각 (잠깐 다시 시도하지 않음)
_MT_DOWN_UNTIL = 0.0
_MT_ERR = ""
_MISSED = set()    # 시험용: 사전·캐시에 없던 틀 모음
_DB = None
_INSTALLED = False


def cur():
    try:
        return st.session_state.get("ui_lang", "ko")
    except Exception:
        return "ko"


# ───────────── 사전 / 캐시 ─────────────
def _static(lang):
    try:
        import i18n_data
        return getattr(i18n_data, lang.upper(), {})
    except Exception:
        return {}


def _db():
    global _DB
    if _DB is None:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
        if not (url and key):
            return None
        from supabase import create_client
        _DB = create_client(url, key)
    return _DB


def _mem(lang):
    """DB 캐시(i18n_cache)를 프로세스에 올려 둔다. 테이블이 없거나 실패하면 빈 채로 10분 뒤 다시 시도."""
    now = time.time()
    if lang in _MEM and now - _MEM_AT.get(lang, 0) < 600:
        return _MEM[lang]
    out = {}
    try:
        db = _db()
        if db is not None:
            start = 0
            while True:
                rows = db.table("i18n_cache").select("src,tgt").eq("lang", lang).range(start, start + 999).execute().data
                for r in rows:
                    out[r["src"]] = r["tgt"]
                if len(rows) < 1000:
                    break
                start += 1000
    except Exception:
        out = _MEM.get(lang, {})
    _MEM[lang] = out
    _MEM_AT[lang] = now
    return out


def _normalize(s):
    vals = []

    def rep(m):
        vals.append(m.group(0))
        return "{%d}" % (len(vals) - 1)
    return _TOKEN.sub(rep, s), vals


def _fill(t, vals):
    return _MARK.sub(lambda m: vals[int(m.group(0)[1:-1])] if int(m.group(0)[1:-1]) < len(vals) else m.group(0), t)


def _lookup(lang, key):
    t = _static(lang).get(key)
    if t is None:
        t = _mem(lang).get(key)
    return t


# ───────────── 문자열 번역 ─────────────
def _tr_core(core, lang, queue):
    key, vals = _normalize(core)
    if not _HANGUL.search(key):
        return core  # 직원 이름만 있는 문구
    t = _lookup(lang, key)
    if t is not None:
        return _fill(t, vals)
    _MISSED.add(key)
    if queue and len(key) <= 300 and not _NO_SEND.search(core) and (lang, key) not in _NEG:
        try:
            st.session_state.setdefault("_i18n_q", {})[key] = lang
        except Exception:
            pass
    return core


def _tr_line(s, lang, queue):
    m = re.match(r"^(\s*)(.*?)(\s*)$", s, re.S)
    lead, core, trail = m.group(1), m.group(2), m.group(3)
    if not core or not _HANGUL.search(core):
        return s
    return lead + _tr_core(core, lang, queue) + trail


def tr(s, queue=True):
    """한국어 문구 하나를 현재 언어로. 마크다운·HTML이 섞여 있으면 글자 부분만 따로 번역."""
    try:
        lang = cur()
        if lang == "ko" or not isinstance(s, str) or not _HANGUL.search(s) or s in _PROTECT:
            return s
        if "<" in s and ">" in s:
            parts = re.split(r"(<style.*?</style>|<script.*?</script>|<[^>]*>)", s, flags=re.S | re.I)
            return "".join(p if (i % 2 == 1) else _tr_multi(p, lang, queue) for i, p in enumerate(parts))
        return _tr_multi(s, lang, queue)
    except Exception:
        return s


def _tr_multi(s, lang, queue):
    if "\n" in s:
        return "\n".join(_tr_line(x, lang, queue) for x in s.split("\n"))
    return _tr_line(s, lang, queue)


def tr_static(s):
    """표 안의 값처럼 '이미 번역돼 있을 때만' 바꾸고, 없으면 그대로 둔다(자동번역 요청 안 함)."""
    return tr(s, queue=False)


# ───────────── 자동번역 ─────────────
def _mt_available():
    return bool(os.environ.get("GOOGLE_TRANSLATE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def _google(keys, lang):
    res = requests.post(
        "https://translation.googleapis.com/language/translate/v2",
        params={"key": os.environ["GOOGLE_TRANSLATE_API_KEY"]},
        json={"q": keys, "source": "ko", "target": _GOOGLE_CODE[lang], "format": "text"},
        timeout=20,
    )
    if res.status_code >= 300:
        raise RuntimeError(f"구글 번역 오류 {res.status_code}: {res.text[:150]}")
    import html as _html
    return [_html.unescape(x["translatedText"]) for x in res.json()["data"]["translations"]]


def _claude(keys, lang):
    import json
    system = (
        f"You translate UI text of a Korean company's internal work tool from Korean into {_TARGET[lang]}. "
        "Input is a JSON array of strings. Reply with ONLY a JSON array of the same length, in the same order. "
        "Keep placeholders like {0} {1}, markdown (** _ #), emoji and line breaks exactly as they are. "
        "Keep brand names, product names and people's names unchanged. Be short and natural, like a button or label. "
        "Do not add explanations."
    )
    res = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": os.environ.get("I18N_MODEL", "claude-sonnet-5"), "max_tokens": 4000, "system": system,
              "messages": [{"role": "user", "content": json.dumps(keys, ensure_ascii=False)}]},
        timeout=40,
    )
    if res.status_code >= 300:
        raise RuntimeError(f"Claude API 오류 {res.status_code}: {res.text[:150]}")
    txt = "".join(b.get("text", "") for b in res.json().get("content", []) if b.get("type") == "text").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt[4:] if txt.startswith("json") else txt
    arr = json.loads(txt)
    if not isinstance(arr, list) or len(arr) != len(keys):
        raise RuntimeError("번역 결과 개수가 맞지 않아요")
    return [str(x) for x in arr]


def _valid(src, out, lang):
    if not out or not out.strip():
        return False
    if sorted(_MARK.findall(src)) != sorted(_MARK.findall(out)):
        return False
    letters = [c for c in out if c.isalpha()]
    if letters and sum(1 for c in letters if _HANGUL.match(c)) / len(letters) > 0.3:
        return False
    return True


def _machine(keys, lang):
    """(번역 dict, 쓴 곳) — 구글 번역 키가 있으면 구글, 없거나 실패하면 Claude."""
    global _MT_ERR
    errs = []
    for name, fn, ok in (("google", _google, bool(os.environ.get("GOOGLE_TRANSLATE_API_KEY"))),
                         ("ai", _claude, bool(os.environ.get("ANTHROPIC_API_KEY")))):
        if not ok:
            continue
        try:
            outs = fn(keys, lang)
            res = {k: o for k, o in zip(keys, outs) if _valid(k, o, lang)}
            if res:
                _MT_ERR = ""
                return res, name
            errs.append(f"{name}: 결과가 올바르지 않음")
        except Exception as e:
            errs.append(f"{name}: {type(e).__name__}: {e}")
    _MT_ERR = " / ".join(errs) or "자동번역 키 없음"
    return {}, None


def flush():
    """화면 맨 끝에서 호출: 이번 화면에서 못 찾은 문구를 한 번에 번역·저장하고, 번역됐으면 화면을 다시 그린다."""
    global _MT_DOWN_UNTIL
    lang = cur()
    if lang == "ko":
        return
    q = st.session_state.get("_i18n_q") or {}
    keys = [k for k, lg in q.items() if lg == lang and (lang, k) not in _NEG and _lookup(lang, k) is None]
    st.session_state["_i18n_q"] = {}
    if not keys:
        return
    if not _mt_available() or time.time() < _MT_DOWN_UNTIL:
        _hint(lang)
        return
    done = {}
    for i in range(0, min(len(keys), 120), 40):
        res, used = _machine(keys[i:i + 40], lang)
        if not res:
            _MT_DOWN_UNTIL = time.time() + 300  # 5분 쉬었다가 다시 시도(크레딧 소진 등)
            break
        done.update(res)
        try:
            db = _db()
            if db is not None:
                db.table("i18n_cache").upsert(
                    [{"lang": lang, "src": k, "tgt": v, "source": used} for k, v in res.items()], on_conflict="lang,src").execute()
        except Exception:
            pass
    now = time.time()
    _mem(lang).update(done)
    for k in keys:
        if k not in done:
            _NEG[(lang, k)] = now
    if done:
        rr_t, rr_n = st.session_state.get("_i18n_rr", (0, 0))
        if now - rr_t > 20:
            rr_t, rr_n = now, 0
        if rr_n < 4:
            st.session_state["_i18n_rr"] = (rr_t, rr_n + 1)
            st.rerun()
    elif keys:
        _hint(lang)


def _hint(lang):
    msg = {"en": "🌐 Some text is still in Korean (auto-translation is not available right now).",
           "zh": "🌐 部分内容暂时仍显示韩文（自动翻译暂不可用）。"}[lang]
    st.caption(msg)


# ───────────── st.* 가로채기 ─────────────
def _tr_kw(k, names):
    for n in names:
        if isinstance(k.get(n), str):
            k[n] = tr(k[n])


def _fmt(ff):
    base = ff if callable(ff) else str
    return lambda o: tr(str(base(o)))


def _wrap_text(orig, self_arg=True):
    def w(*a, **k):
        if cur() != "ko":
            a = list(a)
            i = 1 if self_arg else 0
            if len(a) > i and isinstance(a[i], str):
                a[i] = tr(a[i])
            _tr_kw(k, ("body", "label", "help", "text"))
        return orig(*a, **k)
    return w


def _wrap_write(orig):
    def w(self, *a, **k):
        if cur() != "ko":
            a = [tr(x) if isinstance(x, str) else x for x in a]
        return orig(self, *a, **k)
    return w


def _wrap_widget(orig, fmt_pos=None, fmt_kw=False, extra=()):
    def w(self, *a, **k):
        if cur() != "ko":
            a = list(a)
            if a and isinstance(a[0], str):
                a[0] = tr(a[0])
            _tr_kw(k, ("label", "placeholder", "help") + tuple(extra))
            if fmt_pos is not None or fmt_kw:
                if fmt_pos is not None and len(a) > fmt_pos and a[fmt_pos] is not None:
                    a[fmt_pos] = _fmt(a[fmt_pos])
                else:
                    k["format_func"] = _fmt(k.get("format_func"))
        return orig(self, *a, **k)
    return w


def _wrap_metric(orig):
    def w(self, *a, **k):
        if cur() != "ko":
            a = [tr(x) if (isinstance(x, str) and i < 3) else x for i, x in enumerate(a)]
            _tr_kw(k, ("label", "value", "delta", "help"))
        return orig(self, *a, **k)
    return w


def _wrap_tabs(orig):
    def w(self, tabs, *a, **k):
        if cur() != "ko":
            tabs = [tr(t) if isinstance(t, str) else t for t in tabs]
        return orig(self, tabs, *a, **k)
    return w


def _label_cfg(cfg, cols):
    """표 머리글(컬럼 이름)을 번역 라벨로. 컬럼 이름 자체는 안 바꿔서 코드가 읽는 값은 그대로."""
    out = dict(cfg or {})
    for c in cols:
        if not (isinstance(c, str) and _HANGUL.search(c)):
            continue
        e = out.get(c, "missing")
        if e is None:
            continue  # 숨김 칸
        if e == "missing":
            out[c] = st.column_config.Column(label=tr(c))
        elif isinstance(e, dict):
            e = dict(e)
            e["label"] = tr(e["label"]) if isinstance(e.get("label"), str) else tr(c)
            out[c] = e
    return out


def _wrap_df(orig, values):
    def w(self, data=None, *a, **k):
        if cur() != "ko":
            try:
                import pandas as pd
                if isinstance(data, pd.DataFrame):
                    k["column_config"] = _label_cfg(k.get("column_config"), list(data.columns))
                    if values:
                        data = data.copy()
                        for c in data.columns:
                            if data[c].dtype == object and data[c].nunique(dropna=True) <= 40:
                                data[c] = data[c].map(lambda v: tr_static(v) if isinstance(v, str) and len(v) <= 30 else v)
            except Exception:
                pass
        return orig(self, data, *a, **k)
    return w


def _wrap_table(orig):
    def w(self, data=None, *a, **k):
        if cur() != "ko":
            try:
                import pandas as pd
                if isinstance(data, pd.DataFrame):
                    data = data.copy()
                    data.columns = [tr(c) if isinstance(c, str) else c for c in data.columns]
                    for c in data.columns:
                        if data[c].dtype == object:
                            data[c] = data[c].map(lambda v: tr_static(v) if isinstance(v, str) and len(v) <= 30 else v)
            except Exception:
                pass
        return orig(self, data, *a, **k)
    return w


def install():
    """st.* 함수를 번역 버전으로 바꿔 끼운다(프로세스당 한 번)."""
    global _INSTALLED
    if _INSTALLED:
        return
    from streamlit.delta_generator import DeltaGenerator as DG
    plain = {}
    for n in ("markdown", "caption", "title", "header", "subheader", "success", "info", "warning", "error", "html", "status"):
        plain[n] = _wrap_text
    methods = {n: f for n, f in plain.items()}
    methods["write"] = _wrap_write
    methods["metric"] = _wrap_metric
    methods["tabs"] = _wrap_tabs
    for n in ("text_input", "text_area", "number_input", "date_input", "time_input", "checkbox", "toggle", "file_uploader",
              "slider", "camera_input", "color_picker", "button", "download_button", "link_button", "form_submit_button",
              "popover", "expander", "chat_input", "progress"):
        methods[n] = (lambda o: _wrap_widget(o, extra=("text",)))
    methods["radio"] = lambda o: _wrap_widget(o, fmt_pos=3, fmt_kw=True)
    methods["selectbox"] = lambda o: _wrap_widget(o, fmt_pos=3, fmt_kw=True)
    methods["multiselect"] = lambda o: _wrap_widget(o, fmt_pos=3, fmt_kw=True)
    methods["select_slider"] = lambda o: _wrap_widget(o, fmt_pos=3, fmt_kw=True)
    methods["segmented_control"] = lambda o: _wrap_widget(o, fmt_kw=True)
    methods["pills"] = lambda o: _wrap_widget(o, fmt_kw=True)
    methods["dataframe"] = lambda o: _wrap_df(o, True)
    methods["data_editor"] = lambda o: _wrap_df(o, False)
    methods["table"] = _wrap_table
    for name, maker in methods.items():
        orig = getattr(DG, name, None)
        if orig is None:
            continue
        # _wrap_text는 (self, 본문) 형태로 부르므로 self를 포함해서 감싼다
        setattr(DG, name, maker(orig))
        if hasattr(st, name):
            setattr(st, name, getattr(st._main, name))
    # 모듈 함수(메서드가 아닌 것)
    for name in ("toast", "spinner"):
        orig = getattr(st, name, None)
        if orig is not None and not hasattr(DG, name):
            setattr(st, name, _wrap_text(orig, self_arg=False))
    _INSTALLED = True


def render_switch():
    """맨 위 오른쪽의 언어 버튼. ?lang=en 주소로 열면 그 언어로 시작."""
    qp = st.query_params.get("lang")
    if "ui_lang" not in st.session_state:
        st.session_state["ui_lang"] = qp if qp in LANGS else "ko"
    install()
    _l, _r = st.columns([5, 3])
    with _r:
        st.radio("🌐", list(LANGS), format_func=LANGS.get, horizontal=True, key="ui_lang", label_visibility="collapsed")
    if st.query_params.get("lang") != st.session_state["ui_lang"]:
        st.query_params["lang"] = st.session_state["ui_lang"]
