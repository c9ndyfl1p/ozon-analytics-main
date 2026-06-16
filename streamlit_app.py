"""
Аналитика маркетплейсов — OZON + Яндекс Маркет (Streamlit)
"""
from __future__ import annotations
import hashlib
import io
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Пути к файлам ─────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
COSTS_FILE      = BASE_DIR / "costs_db.json"       # legacy
COST_NAMES_FILE = BASE_DIR / "cost_names.json"     # legacy
COSTS_OZON_FILE      = BASE_DIR / "costs_db_ozon.json"
COSTS_YM_FILE        = BASE_DIR / "costs_db_ym.json"
COST_NAMES_OZON_FILE = BASE_DIR / "cost_names_ozon.json"
COST_NAMES_YM_FILE   = BASE_DIR / "cost_names_ym.json"
RETURNS_FILE    = BASE_DIR / "returns_settings.json"
STATE_FILE      = BASE_DIR / "ozon_state.json"
HISTORY_FILE    = BASE_DIR / "history.json"
HISTORY_DIR     = BASE_DIR / "history"
USERS_FILE      = BASE_DIR / "users.json"

ADMIN_LOGIN    = "admin"
ADMIN_PASSWORD = "Allroad016"

TELEGRAM_TOKEN   = "8683988833:AAEoq2pVkEZinD3QcsjRj1dRx9IT8x06nug"
TELEGRAM_CHAT_ID = "730245954"

# ── Константы ─────────────────────────────────────────────────────────────
TARIFF_PER_L  = 1.9
ACQUIRING_PCT = 1.5

RETURN_TYPE_KEYS   = {"Бой товара": "бой", "Восстановление": "восстановление", "Возврат к продаже": "возврат"}
RETURN_KEYS_LABELS = {"бой": "Бой товара", "восстановление": "Восстановление", "возврат": "Возврат к продаже"}

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта",    4: "апреля",
    5: "мая",    6: "июня",    7: "июля",      8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

# ── Тема (только тёмная) ──────────────────────────────────────────────────
DARK_THEME = dict(
    name="dark",
    bg="#0F172A",    card="#1E293B",   text="#E2E8F0",  muted="#94A3B8",
    primary="#3B82F6", success="#22C55E", danger="#EF4444", warning="#F59E0B",
    border="#334155", input_bg="#0F172A",
)

def get_theme() -> dict:
    return DARK_THEME

def apply_theme(t: dict):
    st.markdown(f"""<style>
    /* ── Base ── */
    .stApp, [data-testid="stMain"], [data-testid="stMainBlockContainer"],
    [data-testid="stHeader"], [data-testid="stBottom"] {{
        background-color: {t['bg']} !important;
    }}
    /* ── Sidebar ── */
    [data-testid="stSidebar"], [data-testid="stSidebarContent"] {{
        background-color: {t['card']} !important;
    }}
    /* ── Global text (cascades everywhere) ── */
    .stApp, .stApp p, .stApp span:not([data-testid]),
    .stApp label, .stMarkdown, .stText,
    [data-testid="stText"], [data-testid="stMarkdownContainer"],
    [data-testid="stCaptionContainer"] {{
        color: {t['text']};
    }}
    h1, h2, h3, h4, h5, h6 {{ color: {t['text']} !important; }}
    .stCaption {{ color: {t['muted']} !important; }}
    /* ── Metrics ── */
    [data-testid="stMetricValue"] {{ color: {t['text']} !important; }}
    [data-testid="stMetricLabel"] {{ color: {t['muted']} !important; }}
    /* ── Inputs ── */
    input, textarea, [data-baseweb="input"] input {{
        background-color: {t['input_bg']} !important;
        color: {t['text']} !important;
        border-color: {t['border']} !important;
    }}
    /* ── Containers ── */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background-color: {t['card']} !important;
        border-color: {t['border']} !important;
    }}
    [data-testid="stExpander"] details {{
        background-color: {t['card']} !important;
        border-color: {t['border']} !important;
    }}
    /* ── Tabs ── */
    /* ── Chrome-style tabs ── */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 3px !important;
        background-color: transparent !important;
        border-bottom: 2px solid {t['border']} !important;
        padding: 0 4px !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
        align-items: flex-end !important;
    }}
    .stTabs [data-baseweb="tab"] {{
        background-color: rgba(255,255,255,0.04) !important;
        color: {t['muted']} !important;
        border-radius: 9px 9px 0 0 !important;
        border: 1px solid transparent !important;
        border-bottom: none !important;
        padding: 7px 18px 8px !important;
        margin-bottom: -2px !important;
        font-size: 13px !important;
        font-weight: 500 !important;
        white-space: nowrap !important;
        transition: background-color 0.12s ease, color 0.12s ease !important;
        min-height: 36px !important;
    }}
    .stTabs [data-baseweb="tab"]:hover {{
        background-color: rgba(255,255,255,0.09) !important;
        color: {t['text']} !important;
        border-color: {t['border']} !important;
    }}
    .stTabs [aria-selected="true"] {{
        background-color: {t['card']} !important;
        color: {t['text']} !important;
        border: 1px solid {t['border']} !important;
        border-bottom: 2px solid {t['card']} !important;
        font-weight: 600 !important;
    }}
    .stTabs [data-baseweb="tab-highlight"] {{ display: none !important; }}
    /* ── Divider ── */
    hr {{ border-color: {t['border']} !important; }}
    /* ── File uploader ── */
    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploadDropzone"] {{
        background-color: {t['card']} !important;
        border-color: {t['border']} !important;
    }}
    [data-testid="stFileUploader"] span,
    [data-testid="stFileUploader"] p {{
        color: {t['text']} !important;
    }}
    /* ── Select / dropdown ── */
    [data-baseweb="select"] > div {{
        background-color: {t['input_bg']} !important;
        border-color: {t['border']} !important;
        color: {t['text']} !important;
    }}
    [data-baseweb="popover"] ul {{
        background-color: {t['card']} !important;
        color: {t['text']} !important;
    }}
    /* ── Info / warning / success boxes ── */
    [data-testid="stAlert"] {{ background-color: {t['card']} !important; }}
    /* ── ALL buttons: universal fallback then specific overrides ── */
    button {{
        background-color: {t['card']} !important;
        color: {t['text']} !important;
        border: 1px solid {t['border']} !important;
    }}
    button:hover {{
        border-color: {t['primary']} !important;
        color: {t['primary']} !important;
    }}
    /* Streamlit wrapper-based selectors */
    .stButton > button, .stDownloadButton > button {{
        background-color: {t['card']} !important;
        color: {t['text']} !important;
        border-color: {t['border']} !important;
    }}
    .stButton > button:hover, .stDownloadButton > button:hover {{
        background-color: {t['input_bg']} !important;
        border-color: {t['primary']} !important;
        color: {t['primary']} !important;
    }}
    /* data-testid on the button element itself (no "st" prefix) */
    button[data-testid="baseButton-secondary"] {{
        background-color: {t['card']} !important;
        color: {t['text']} !important;
        border-color: {t['border']} !important;
    }}
    button[data-testid="baseButton-secondary"]:hover {{
        border-color: {t['primary']} !important;
        color: {t['primary']} !important;
    }}
    button[data-testid="baseButton-primary"],
    .stButton > button[kind="primary"] {{
        background-color: {t['primary']} !important;
        color: #ffffff !important;
        border-color: {t['primary']} !important;
    }}
    button[data-testid="baseButton-primary"]:hover,
    .stButton > button[kind="primary"]:hover {{
        filter: brightness(1.1);
        color: #ffffff !important;
    }}
    /* ── Radio ── */
    [data-testid="stRadio"] label {{ color: {t['text']} !important; }}
    [data-testid="stRadio"] div[role="radiogroup"] label span {{
        color: {t['text']} !important;
    }}
    /* ── Number input arrows ── */
    [data-testid="stNumberInput"] button {{
        background-color: {t['input_bg']} !important;
        color: {t['text']} !important;
        border-color: {t['border']} !important;
    }}
    /* ── Mobile ── */
    @media (max-width: 768px) {{
        [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; }}
        [data-testid="column"] {{ min-width: min(100%, 280px) !important; }}
        [data-testid="stMetricValue"] {{ font-size: 1.1rem !important; }}
        h1 {{ font-size: 1.4rem !important; }}
        h2 {{ font-size: 1.2rem !important; }}
        [data-testid="stPlotlyChart"] {{ overflow-x: auto; }}
        [data-testid="stSidebar"] {{ min-width: 0 !important; }}
    }}
    </style>""", unsafe_allow_html=True)

# Сокращения цветов (используются в коде ниже)
C_PRIMARY = DARK_THEME["primary"]
C_SUCCESS = DARK_THEME["success"]
C_DANGER  = DARK_THEME["danger"]
C_WARNING = DARK_THEME["warning"]
C_MUTED   = DARK_THEME["muted"]
C_BG      = DARK_THEME["bg"]
C_CARD    = DARK_THEME["card"]

# ══════════════════════════════════════════════════════════════════════════
# ОБЩЕЕ СОСТОЯНИЕ (shared across all user sessions via cache_resource)
# ══════════════════════════════════════════════════════════════════════════

def _read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def _write_json(path: Path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

@st.cache_resource
def _shared() -> dict:
    """
    Единый объект в памяти сервера, общий для всех сессий.
    Инициализируется из файлов при старте приложения.
    """
    HISTORY_DIR.mkdir(exist_ok=True)
    # Миграция из единой базы в раздельные (один раз)
    legacy = _read_json(COSTS_FILE, {})
    legacy_names = _read_json(COST_NAMES_FILE, {})
    def _init_costs(path):
        if not path.exists() and legacy:
            _write_json(path, legacy)
        return _read_json(path, {})
    def _init_names(path):
        if not path.exists() and legacy_names:
            _write_json(path, legacy_names)
        return _read_json(path, {})
    return {
        "costs_ozon":      _init_costs(COSTS_OZON_FILE),
        "costs_ym":        _init_costs(COSTS_YM_FILE),
        "cost_names_ozon": _init_names(COST_NAMES_OZON_FILE),
        "cost_names_ym":   _init_names(COST_NAMES_YM_FILE),
        "return_settings": _read_json(RETURNS_FILE, {}),
        "history":         _read_json(HISTORY_FILE, {"ozon": [], "ym": []}),
        "users":           _read_json(USERS_FILE, {}),
    }

# Обёртки для чтения/записи через shared state
def get_costs(kind: str = "ozon") -> dict:
    return _shared()[f"costs_{kind}"]

def set_costs(costs: dict, kind: str = "ozon"):
    _shared()[f"costs_{kind}"] = costs
    _write_json(COSTS_OZON_FILE if kind == "ozon" else COSTS_YM_FILE, costs)

def get_cost_names(kind: str = "ozon") -> dict:
    return _shared()[f"cost_names_{kind}"]

def set_cost_names(names: dict, kind: str = "ozon"):
    _shared()[f"cost_names_{kind}"] = names
    _write_json(COST_NAMES_OZON_FILE if kind == "ozon" else COST_NAMES_YM_FILE, names)

def get_return_settings() -> dict:
    return _shared()["return_settings"]

def set_return_settings(data: dict):
    _shared()["return_settings"] = data
    _write_json(RETURNS_FILE, data)

def get_history() -> dict:
    return _shared()["history"]

def _save_history():
    _write_json(HISTORY_FILE, _shared()["history"])

# ── Auth helpers ───────────────────────────────────────────────────────────

def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def get_users() -> dict:
    return _shared()["users"]

def set_users(users: dict):
    _shared()["users"] = users
    _write_json(USERS_FILE, users)

def _ensure_admin():
    """Добавляет аккаунт admin если его нет."""
    users = get_users()
    if ADMIN_LOGIN not in users:
        users[ADMIN_LOGIN] = {
            "password": _hash_pw(ADMIN_PASSWORD),
            "status": "approved",
            "role": "admin",
        }
        set_users(users)

# ── GitHub autosave ───────────────────────────────────────────────────────

GITHUB_REPO      = "c9ndyfl1p/ozon-analytics-main"
_DATA_FILES      = ["costs_db_ozon.json", "costs_db_ym.json",
                    "cost_names_ozon.json", "cost_names_ym.json",
                    "users.json", "history.json"]

def _github_commit_files():
    try:
        import base64
        import requests as _req
        token = st.secrets.get("GITHUB_TOKEN", "")
        if not token:
            return
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
        base_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents"
        changed = []
        for fname in _DATA_FILES:
            fpath = BASE_DIR / fname
            if not fpath.exists():
                continue
            content_b64 = base64.b64encode(fpath.read_bytes()).decode()
            resp = _req.get(f"{base_url}/{fname}", headers=headers, timeout=10)
            sha = resp.json().get("sha") if resp.ok else None
            # Пропускаем если содержимое не изменилось
            if sha and resp.ok:
                remote_b64 = resp.json().get("content", "").replace("\n", "")
                if remote_b64 == content_b64:
                    continue
            payload = {"message": f"autosave: {fname}", "content": content_b64}
            if sha:
                payload["sha"] = sha
            r = _req.put(f"{base_url}/{fname}", json=payload, headers=headers, timeout=10)
            if r.ok:
                changed.append(fname)
    except Exception:
        pass

@st.cache_resource
def _start_git_autosave():
    def _loop():
        while True:
            time.sleep(3600)
            _github_commit_files()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t


# ── Telegram helpers ──────────────────────────────────────────────────────

def _tg_request(method: str, **kwargs):
    try:
        import requests as _req
        _req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
            json=kwargs,
            timeout=6,
        )
    except Exception:
        pass

def _tg_send(text: str, reply_markup: dict | None = None):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _tg_request("sendMessage", **payload)

def _tg_notify_registration(username: str):
    _tg_send(
        f"🔔 <b>Новая заявка на регистрацию</b>\nПользователь: <code>{username}</code>",
        reply_markup={
            "inline_keyboard": [[
                {"text": "✅ Одобрить", "callback_data": f"approve:{username}"},
                {"text": "❌ Отклонить", "callback_data": f"reject:{username}"},
            ]]
        },
    )

@st.cache_resource
def _start_tg_polling():
    """Запускает фоновый поток long-polling для обработки кнопок бота."""
    def _poll():
        offset = None
        while True:
            try:
                import requests as _req
                params: dict = {"timeout": 30}
                if offset is not None:
                    params["offset"] = offset
                resp = _req.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                    params=params,
                    timeout=35,
                )
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    cb = update.get("callback_query")
                    if not cb:
                        continue
                    data      = cb.get("data", "")
                    chat_id   = cb["message"]["chat"]["id"]
                    msg_id    = cb["message"]["message_id"]
                    cb_id     = cb["id"]
                    _tg_request("answerCallbackQuery", callback_query_id=cb_id)
                    if data.startswith("approve:"):
                        uname = data[len("approve:"):]
                        users = get_users()
                        if uname in users and users[uname].get("status") == "pending":
                            users[uname]["status"] = "approved"
                            set_users(users)
                            _tg_request("editMessageText",
                                        chat_id=chat_id, message_id=msg_id,
                                        text=f"✅ Пользователь <b>{uname}</b> одобрен.",
                                        parse_mode="HTML")
                        else:
                            _tg_request("editMessageText",
                                        chat_id=chat_id, message_id=msg_id,
                                        text=f"⚠️ Пользователь <b>{uname}</b> не найден или уже обработан.",
                                        parse_mode="HTML")
                    elif data.startswith("reject:"):
                        uname = data[len("reject:"):]
                        users = get_users()
                        if uname in users:
                            del users[uname]
                            set_users(users)
                            _tg_request("editMessageText",
                                        chat_id=chat_id, message_id=msg_id,
                                        text=f"❌ Пользователь <b>{uname}</b> отклонён и удалён.",
                                        parse_mode="HTML")
            except Exception:
                time.sleep(5)

    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    return t


def migrate_history_periods():
    """Пересчитывает период из filename используя актуальный regex с названием месяца."""
    hist = get_history()
    changed = False
    for kind in ("ozon", "ym"):
        for entry in hist.get(kind, []):
            filename = entry.get("filename", "")
            if not filename:
                continue
            new_period = period_from_filename(filename)
            if new_period and new_period != entry.get("period"):
                entry["period"] = new_period
                changed = True
    if changed:
        _save_history()

# ══════════════════════════════════════════════════════════════════════════
# ИСТОРИЯ ОТЧЁТОВ
# ══════════════════════════════════════════════════════════════════════════

def _parse_date_from_str(s: str) -> datetime | None:
    s = s.replace("_", ".").replace("-", ".")
    for fmt in ("%d.%m.%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None

def _fmt_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_RU[dt.month]} {dt.year}"

def period_from_filename(filename: str) -> str:
    """Извлекает период из имени файла. Возвращает пустую строку если не найдено."""
    # Год ограничен 19xx/20xx чтобы не ловить случайные числа типа 8206235
    tokens = re.findall(r"\d{2}[._-]\d{2}[._-](?:19|20)\d{2}|(?:19|20)\d{2}[._-]\d{2}[._-]\d{2}", filename)
    parsed = [d for t in tokens if (d := _parse_date_from_str(t)) is not None]
    if len(parsed) >= 2:
        parsed.sort()
        return f"{_fmt_date(parsed[0])} — {_fmt_date(parsed[-1])}"
    if len(parsed) == 1:
        return _fmt_date(parsed[0])
    return ""

def save_report_to_history(kind: str, filename: str, df_raw: pd.DataFrame, regular: pd.DataFrame, period: str = "") -> str:
    """Сохраняет сырой DataFrame в parquet и добавляет запись в историю."""
    HISTORY_DIR.mkdir(exist_ok=True)
    if not period:
        period = period_from_filename(filename)
    rec_id  = str(uuid.uuid4())[:8]
    parquet = HISTORY_DIR / f"{kind}_{rec_id}.parquet"

    try:
        df_raw.to_parquet(parquet, index=False)
    except Exception:
        return period

    metrics = {}
    if not regular.empty:
        metrics = {
            "revenue": round(float(regular["Выручка"].sum())        if "Выручка"        in regular.columns else 0, 0),
            "profit":  round(float(regular["Прибыль"].sum())        if "Прибыль"        in regular.columns else 0, 0),
            "orders":  int(regular["Количество"].sum()              if "Количество"     in regular.columns else 0),
            "margin":  round(float(regular["Рентабельность"].mean()) if "Рентабельность" in regular.columns else 0, 1),
        }

    entry = {
        "id":          rec_id,
        "filename":    filename,
        "period":      period,
        "uploaded_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "metrics":     metrics,
        "parquet":     str(parquet),
    }

    hist = get_history()
    # Убираем дублирующийся период для этого типа
    hist[kind] = [h for h in hist[kind] if h["period"] != period]
    hist[kind].insert(0, entry)
    hist[kind] = hist[kind][:20]          # храним последние 20
    _save_history()
    return period

def load_report_from_history(entry: dict):
    """Читает сохранённый parquet, возвращает DataFrame."""
    path = Path(entry["parquet"])
    if not path.exists():
        return None
    return pd.read_parquet(path)

# ══════════════════════════════════════════════════════════════════════════
# ПАРСЕРЫ
# ══════════════════════════════════════════════════════════════════════════


def parse_amount(s) -> float:
    if pd.isna(s):
        return 0.0
    s = str(s).replace("₽", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

def parse_accrual_excel(f) -> pd.DataFrame:
    raw = pd.read_excel(f, header=None, dtype=str)
    header_row = next(
        (i for i, row in raw.iterrows()
         if row.astype(str).str.contains("ID начисления", na=False).any()),
        None
    )
    if header_row is None:
        raise ValueError("Не найдена строка с заголовками ('ID начисления')")
    f.seek(0)
    df = pd.read_excel(f, header=header_row, dtype=str)
    df = df.dropna(how="all")
    df.columns = df.columns.str.strip()
    return df

def parse_ym_excel(f) -> pd.DataFrame:
    xf = pd.ExcelFile(f)
    if len(xf.sheet_names) < 2:
        raise ValueError("В файле менее 2 листов — ожидается минимум 2")
    sheet = xf.sheet_names[1]
    f.seek(0)
    raw = pd.read_excel(f, sheet_name=sheet, header=None, dtype=str, nrows=10)
    hdr_row = next(
        (i for i, row in raw.iterrows()
         if any("ваш sku" in str(v).lower() or "сумма транзакц" in str(v).lower() for v in row.values)),
        1
    )
    f.seek(0)
    df = pd.read_excel(f, sheet_name=sheet, header=hdr_row, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df

# ══════════════════════════════════════════════════════════════════════════
# БИЗНЕС-ЛОГИКА
# ══════════════════════════════════════════════════════════════════════════

def build_accrual_summary(df: pd.DataFrame):
    id_col  = "ID начисления"
    qty_col = "Количество"
    op_col  = "Тип начисления"
    amt_col = "Сумма итого, руб."

    df = df.copy()
    df[id_col]  = df[id_col].fillna("").astype(str).str.strip()
    df["_amt"]  = df[amt_col].apply(parse_amount)
    df["_qty"]  = df[qty_col].apply(lambda x: int(parse_amount(x)))
    df[op_col]  = df[op_col].fillna("").astype(str).str.strip()

    pivot = df[df[id_col] != ""].pivot_table(
        index=id_col, columns=op_col, values="_amt", aggfunc="sum", fill_value=0.0
    ).reset_index()
    ops = [c for c in pivot.columns if c != id_col]

    rev_cols  = [c for c in ops if "выручка" in c.lower() and "возврат" not in c.lower()]
    ret_r     = [c for c in ops if "возврат" in c.lower() and "выручка" in c.lower()]
    ret_l     = [c for c in ops if "обратная" in c.lower()]
    ret_other = [c for c in ops if "возврат" in c.lower() and c not in ret_r and c not in ret_l]
    ret_cols  = list(set(ret_r + ret_l + ret_other))
    exp_cols  = [c for c in ops if c not in rev_cols and c not in ret_cols]

    skip     = [c for c in ops if "эквайринг" in c.lower() or "дополнительная" in c.lower()]
    non_skip = [c for c in ops if c not in skip]
    pivot["_acq_only"] = pivot[non_skip].abs().sum(axis=1) == 0 if non_skip else False

    pivot["Выручка"]             = pivot[rev_cols].sum(axis=1) if rev_cols else 0.0
    pivot["Расходы"]             = pivot[exp_cols].sum(axis=1).abs() if exp_cols else 0.0
    pivot["Поступление от ОЗОН"] = pivot[ops].sum(axis=1) / 1.22
    pivot["_is_return"]          = (
        (pivot[ret_r].abs().sum(axis=1) > 0 if ret_r else pd.Series(False, index=pivot.index)) |
        (pivot[ret_l].abs().sum(axis=1) > 0 if ret_l else pd.Series(False, index=pivot.index))
    )
    pivot["_ret_log_cost"] = pivot[ret_l].sum(axis=1).abs() if ret_l else 0.0

    meta = df[df[id_col] != ""].groupby(id_col, sort=False).agg(
        date=("Дата начисления", "first"),
        article=("Артикул", "first"),
        sku=("SKU", "first"),
        name=("Название товара", "first"),
        qty=("_qty", "max"),
    ).reset_index()
    meta.columns = [id_col, "Дата начисления", "Артикул", "SKU", "Название товара", "_qty"]

    result = meta.merge(
        pivot[[id_col, "Выручка", "Расходы", "Поступление от ОЗОН",
               "_is_return", "_ret_log_cost", "_acq_only"]],
        on=id_col, how="left"
    )

    costs_db = get_costs()
    def get_cost(row):
        for key in [str(row.get("Артикул", "")).strip(), str(row.get("SKU", "")).strip()]:
            if key and key != "nan" and costs_db.get(key, 0) > 0:
                return costs_db[key]
        return 0.0

    result["_unit_cost"] = result.apply(get_cost, axis=1)
    result["Количество"] = result.apply(
        lambda r: int(r["_qty"]) if not bool(r.get("_acq_only", False)) else 0, axis=1
    )

    ret_settings = get_return_settings()
    def calc_cost(row):
        if row.get("_is_return", False):
            s     = ret_settings.get(str(row[id_col]), {})
            rtype = s.get("type", "возврат")
            qty   = max(int(row["_qty"]), 1)
            uc    = row["_unit_cost"]
            if rtype == "бой":
                return uc * qty
            if rtype == "восстановление":
                return max(0.0, uc * qty + float(s.get("restoration_cost", 0.0)))
            return 0.0
        if not row.get("Выручка", 0) or row.get("Выручка", 0) <= 0:
            return 0.0
        return row["_unit_cost"] * row["_qty"]

    result["Себестоимость"]  = result.apply(calc_cost, axis=1)
    result["Прибыль"]        = result["Поступление от ОЗОН"] - result["Себестоимость"]
    result["Рентабельность"] = result.apply(
        lambda r: (r["Поступление от ОЗОН"] / r["Себестоимость"] * 100 - 100)
        if r["Себестоимость"] > 0 else 0.0, axis=1
    )
    regular = result[~result["_is_return"]].copy()
    returns = result[result["_is_return"]].copy()
    return regular, returns

def build_ym_summary(df_raw: pd.DataFrame) -> pd.DataFrame:
    costs = get_costs("ym")
    def _find(*kws):
        return next((c for c in df_raw.columns if all(k.lower() in c.lower() for k in kws)), None)

    sku_col    = _find("ваш", "sku") or _find("sku")
    name_col   = _find("название", "товар")
    amount_col = _find("сумма", "транзакц")
    date_col   = _find("дата", "транзакц")
    order_col  = next((c for c in df_raw.columns
                       if "номер заказа" in c.lower() and "наш" not in c.lower()), None)

    if not sku_col or not amount_col:
        raise ValueError("Не найдены колонки: Ваш SKU, Сумма транзакции")

    df = df_raw.copy()
    df = df[df[sku_col].notna() & (df[sku_col].astype(str).str.strip().str.lower() != "nan")].copy()
    if df.empty:
        return pd.DataFrame()

    df["_sku"]    = df[sku_col].astype(str).str.strip()
    df["_order"]  = df[order_col].astype(str).str.strip() if order_col else ""
    df["_amount"] = df[amount_col].apply(parse_amount)
    df["_name"]   = df[name_col].astype(str).str.strip() if name_col else ""
    df["_date"]   = df[date_col].astype(str).str.strip() if date_col else ""

    out = []
    for (order_num, sku), grp in df.groupby(["_order", "_sku"], sort=False):
        if not sku or sku.lower() == "nan":
            continue
        revenue = grp.loc[grp["_amount"] > 0, "_amount"].sum()
        net     = grp["_amount"].sum()
        name    = next((str(r["_name"]).strip() for _, r in grp[grp["_amount"] > 0].iterrows()
                        if str(r["_name"]).strip() not in ("nan", "")), "")
        date    = next((str(r["_date"]).strip() for _, r in grp.iterrows()
                        if str(r["_date"]).strip() not in ("nan", "")), "")
        uc = costs.get(sku, 0.0)
        out.append({
            "SKU": sku, "Название товара": name, "Количество": 1,
            "Выручка": revenue, "Расходы": max(0.0, revenue - net),
            "Поступление от ОЗОН": net, "Себестоимость": uc,
            "Прибыль": net - uc, "Дата начисления": date,
            "Номер заказа": order_num if order_num not in ("nan", "") else "",
        })

    if not out:
        return pd.DataFrame()

    result = pd.DataFrame(out)
    result["Рентабельность"] = result.apply(
        lambda r: (r["Поступление от ОЗОН"] / r["Себестоимость"] * 100 - 100)
        if r["Себестоимость"] > 0 else 0.0, axis=1
    )
    result["Дата начисления"] = pd.to_datetime(result["Дата начисления"], dayfirst=True, errors="coerce")
    return result

def compute_insights(df: pd.DataFrame):
    if df is None or df.empty:
        return 0.0, pd.DataFrame()
    needed = {"SKU", "Название товара", "Количество", "Поступление от ОЗОН", "Себестоимость", "Прибыль"}
    if not needed.issubset(df.columns):
        return 0.0, pd.DataFrame()
    grp = df.groupby("SKU", sort=False).agg(
        name=("Название товара", "first"), qty=("Количество", "sum"),
        net=("Поступление от ОЗОН", "sum"), cost=("Себестоимость", "sum"),
        profit=("Прибыль", "sum"),
    ).reset_index()
    grp["margin"] = grp.apply(
        lambda r: (r["net"] / r["cost"] * 100 - 100) if r["cost"] > 0 else 0.0, axis=1
    )
    mx = float(grp["qty"].max())
    if mx <= 0:
        return 0.0, pd.DataFrame()
    threshold = mx / 2
    result = grp[(grp["qty"] < threshold) & (grp["margin"] > 50)].sort_values("margin", ascending=False)
    return threshold, result[["SKU", "name", "qty", "margin", "profit"]]

# ══════════════════════════════════════════════════════════════════════════
# ГРАФИКИ
# ══════════════════════════════════════════════════════════════════════════

def _base_layout(fig: go.Figure, t: dict, title: str, height: int):
    fig.update_layout(
        title=dict(text=title, font=dict(color=t["muted"], size=12)),
        paper_bgcolor=t["bg"], plot_bgcolor=t["card"],
        font=dict(color=t["text"], size=11), height=height,
        margin=dict(l=10, r=10, t=38, b=10),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=t["text"])),
    )
    fig.update_xaxes(gridcolor=t["border"], zerolinecolor=t["border"])
    fig.update_yaxes(gridcolor=t["border"], zerolinecolor=t["border"])

def _chart_top(df: pd.DataFrame, top_metric: str, t: dict, h: int) -> go.Figure:
    mcol = {"Прибыль": "Прибыль", "Выручка": "Выручка", "Продано": "Количество"}.get(top_metric, "Прибыль")
    fig = go.Figure()
    if "Название товара" in df.columns and mcol in df.columns:
        top = df.groupby("Название товара")[mcol].sum().sort_values().tail(10)
        fig.add_trace(go.Bar(
            y=top.index.tolist(), x=top.values.tolist(), orientation="h",
            marker_color=[t["danger"] if v < 0 else t["primary"] for v in top.values],
            showlegend=False,
            text=[f"{v:,.0f}" for v in top.values], textposition="outside",
        ))
    _base_layout(fig, t, "Топ товаров", h)
    return fig

def _chart_dynamics(df: pd.DataFrame, t: dict, h: int) -> go.Figure:
    fig = go.Figure()
    if "Дата начисления" in df.columns and "Выручка" in df.columns:
        by_d = (df.groupby("Дата начисления")[["Выручка", "Прибыль"]]
                .sum().reset_index().sort_values("Дата начисления"))
        dates = by_d["Дата начисления"].astype(str).tolist()
        fig.add_trace(go.Bar(x=dates, y=by_d["Выручка"].tolist(),
                             name="Выручка", marker_color=t["success"], opacity=0.65))
        fig.add_trace(go.Scatter(x=dates, y=by_d["Прибыль"].tolist(),
                                 name="Прибыль", line=dict(color=t["warning"], width=2),
                                 mode="lines+markers"))
    _base_layout(fig, t, "Динамика выручки и прибыли", h)
    return fig

def _chart_pie(df: pd.DataFrame, t: dict, h: int) -> go.Figure:
    fig = go.Figure()
    if "Название товара" in df.columns and "Прибыль" in df.columns:
        bp = df.groupby("Название товара")["Прибыль"].sum()
        bp = bp[bp > 0].sort_values(ascending=False)
        if not bp.empty:
            top5 = bp.head(5)
            rest = bp.iloc[5:].sum()
            if rest > 0:
                top5 = pd.concat([top5, pd.Series({"Остальные": rest})])
            palette = [t["primary"], "#A855F7", "#EAB308", t["success"], "#F97316", t["muted"]]
            fig.add_trace(go.Pie(
                labels=top5.index.tolist(), values=top5.values.tolist(),
                hole=0.55, marker_colors=palette[:len(top5)], showlegend=True,
            ))
    _base_layout(fig, t, "Доля в прибыли (топ-5)", h)
    return fig

def _chart_matrix(df: pd.DataFrame, t: dict, h: int) -> go.Figure:
    fig = go.Figure()
    if {"Название товара", "Количество", "Рентабельность", "Выручка"}.issubset(df.columns):
        grp = df.groupby("Название товара").agg(
            qty=("Количество", "sum"), margin=("Рентабельность", "mean"),
            revenue=("Выручка", "sum"),
        ).reset_index()
        grp = grp[grp["qty"] > 0].reset_index(drop=True)
        if not grp.empty:
            rev_max = grp["revenue"].max() or 1.0
            sizes   = (grp["revenue"] / rev_max * 40 + 6).clip(6, 46)
            label_idx = (set(grp.nlargest(3, "margin").index) | set(grp.nlargest(3, "qty").index))
            def _short(n: str) -> str: return n[:20] + "…" if len(n) > 20 else n
            labels = [_short(str(r["Название товара"])) if i in label_idx else "" for i, r in grp.iterrows()]
            hovers = [
                f"<b>{r['Название товара']}</b><br>Продано: {int(r['qty'])} шт.<br>"
                f"Рентабельность: {r['margin']:.1f}%<br>Выручка: {r['revenue']:,.0f} ₽"
                for _, r in grp.iterrows()
            ]
            fig.add_trace(go.Scatter(
                x=grp["qty"].tolist(), y=grp["margin"].tolist(),
                mode="markers+text", text=labels, hovertext=hovers, hoverinfo="text",
                textposition="top center", textfont=dict(size=9, color=t["text"]),
                marker=dict(size=sizes.tolist(),
                            color=[t["danger"] if m < 0 else t["primary"] for m in grp["margin"]],
                            opacity=0.8, line=dict(color="rgba(128,128,128,0.3)", width=1)),
                showlegend=False,
            ))
            x_min, x_max = grp["qty"].min() * 0.9, grp["qty"].max() * 1.1
            fig.add_trace(go.Scatter(
                x=[x_min, x_max], y=[0, 0],
                mode="lines", line=dict(color=t["muted"], dash="dot", width=1), showlegend=False,
            ))
    _base_layout(fig, t, "Матрица ассортимента", h)
    fig.update_layout(xaxis_title="Продано, шт.", yaxis_title="Рентабельность, %")
    return fig

def render_charts_section(df: pd.DataFrame, key_prefix: str, top_metric: str):
    """2×2 сетка графиков. Клик на ⤢ — разворачивает один на всю ширину, повторный — сворачивает."""
    t   = get_theme()
    exp = st.session_state.get(f"{key_prefix}exp")

    fns = {
        "top":      lambda h: _chart_top(df, top_metric, t, h),
        "dynamics": lambda h: _chart_dynamics(df, t, h),
        "pie":      lambda h: _chart_pie(df, t, h),
        "matrix":   lambda h: _chart_matrix(df, t, h),
    }

    def _tile(name: str, h: int):
        fig = fns[name](h)
        bcol, gcol = st.columns([1, 22])
        with bcol:
            st.write("")
            icon = "⤡" if exp == name else "⤢"
            if st.button(icon, key=f"{key_prefix}exp_{name}", help="Развернуть / свернуть"):
                st.session_state[f"{key_prefix}exp"] = None if exp == name else name
                st.rerun()
        with gcol:
            st.plotly_chart(fig, use_container_width=True, config=_PLOTLY_CFG)

    if exp and exp in fns:
        _tile(exp, 700)
    else:
        c1, c2 = st.columns(2)
        with c1: _tile("top",      340)
        with c2: _tile("dynamics", 340)
        c3, c4 = st.columns(2)
        with c3: _tile("pie",      340)
        with c4: _tile("matrix",   340)

# ── Полноэкранный график ───────────────────────────────────────────────────

_PLOTLY_CFG = dict(
    scrollZoom=True,
    doubleClick="reset",
    displayModeBar=True,
    modeBarButtonsToRemove=["lasso2d", "select2d"],
    toImageButtonOptions={"format": "png", "scale": 2},
)

@st.dialog("📊 График", width="large")
def _chart_fullscreen(fig: go.Figure):
    st.plotly_chart(fig, use_container_width=True, config=_PLOTLY_CFG)

def show_chart(fig: go.Figure, key: str):
    """Показывает график + кнопку открытия на весь экран."""
    st.plotly_chart(fig, use_container_width=True, config=_PLOTLY_CFG)
    if st.button("⛶ На весь экран", key=f"fs_{key}"):
        _chart_fullscreen(fig)

# ── Сравнение периодов ────────────────────────────────────────────────────

def load_report_processed(kind: str, entry: dict) -> pd.DataFrame | None:
    """Загружает сырой parquet и перегоняет через бизнес-логику с текущей себестоимостью."""
    df_raw = load_report_from_history(entry)
    if df_raw is None:
        return None
    try:
        if kind == "ozon":
            regular, _ = build_accrual_summary(df_raw)
            return regular
        else:
            return build_ym_summary(df_raw)
    except Exception:
        return None

def make_comparison_chart(dfs_by_period: dict, metric: str, t: dict) -> go.Figure:
    """dfs_by_period: {period_label: DataFrame} — каждый df содержит 'Дата начисления'."""
    palette = [t["primary"], t["success"], t["warning"], t["danger"],
               "#A855F7", "#F97316", "#06B6D4", "#EC4899"]
    metric_labels = {
        "Выручка":    "Выручка, ₽",
        "Прибыль":    "Чистая прибыль, ₽",
        "Количество": "Заказов, шт.",
    }

    fig = go.Figure()
    for i, (period, df) in enumerate(dfs_by_period.items()):
        if "Дата начисления" not in df.columns or metric not in df.columns:
            continue
        clean = df[df["Дата начисления"].notna()].copy()
        by_d = (clean.groupby("Дата начисления")[metric]
                .sum().reset_index().sort_values("Дата начисления"))
        by_d["day"] = range(1, len(by_d) + 1)
        color = palette[i % len(palette)]
        fig.add_trace(go.Scatter(
            x=by_d["day"], y=by_d[metric],
            name=period,
            mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=5, color=color),
            hovertemplate=(
                f"<b>{period}</b><br>"
                f"День %{{x}}<br>"
                f"{metric_labels.get(metric, metric)}: %{{y:,.0f}}<extra></extra>"
            ),
        ))

    fig.update_layout(
        paper_bgcolor=t["bg"], plot_bgcolor=t["card"],
        font=dict(color=t["text"], size=11), height=430,
        xaxis_title="День периода", yaxis_title=metric_labels.get(metric, metric),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=t["text"])),
        margin=dict(l=10, r=10, t=20, b=40),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor=t["border"])
    fig.update_yaxes(gridcolor=t["border"])
    return fig

def render_comparison_tab(kind: str, current_period: str, current_df: pd.DataFrame,
                          key_prefix: str):
    """Вкладка сравнения динамики нескольких отчётов."""
    t = get_theme()
    hist = get_history().get(kind, [])
    hist_options = {e["period"]: e for e in hist if e.get("parquet") and Path(e["parquet"]).exists()}

    all_options = list(hist_options.keys())
    if not all_options:
        st.info("Нет сохранённых отчётов для сравнения. Загрузите ещё один период.")
        return

    col_sel, col_met = st.columns([3, 1])
    with col_sel:
        selected = st.multiselect(
            "Периоды для сравнения",
            options=all_options,
            default=all_options[:min(3, len(all_options))],
            key=f"{key_prefix}cmp_periods",
        )
    with col_met:
        metric = st.selectbox(
            "Метрика",
            ["Выручка", "Прибыль", "Количество"],
            format_func=lambda x: {"Выручка": "Выручка", "Прибыль": "Чистая прибыль", "Количество": "Заказов"}[x],
            key=f"{key_prefix}cmp_metric",
        )

    if not selected:
        st.caption("Выберите хотя бы один период")
        return

    dfs_by_period: dict = {}
    if current_period and not current_df.empty and current_period in selected:
        dfs_by_period[current_period] = current_df
    for period_label in selected:
        if period_label == current_period:
            continue
        entry = hist_options.get(period_label)
        if entry:
            with st.spinner(f"Загрузка {period_label}…"):
                df_h = load_report_processed(kind, entry)
            if df_h is not None and not df_h.empty:
                dfs_by_period[period_label] = df_h

    if not dfs_by_period:
        st.warning("Не удалось загрузить данные для выбранных периодов")
        return

    fig = make_comparison_chart(dfs_by_period, metric, t)
    show_chart(fig, f"{key_prefix}cmp")

# ══════════════════════════════════════════════════════════════════════════
# КАЛЬКУЛЯТОР ЦЕН
# ══════════════════════════════════════════════════════════════════════════

DEFAULT_PRODUCTS = [
    ("Аптечка АМУ-1",                        23,  44,  630.20),
    ("Ключница К-148",                        13,  43,  410.55),
    ("Ключница К-20",                          3,  43,  236.90),
    ("Ключница К-40",                         13,  43,  410.55),
    ("Ключница К-60",                         14,  43,  425.50),
    ("Почтовый ящик ЯП-4",                   38,  45, 1010.85),
    ("Почтовый ящик ЯП-5",                   45,  45, 1114.35),
    ("Почтовый ящик ЯП-6",                   50,  45, 1354.70),
    ("Почтовый ящик ЯП-8",                   72,  45, 1829.65),
    ("Сейф СМ 20",                            14,  40,  425.50),
    ("Сейф СМ 20-Э",                          14,  40,  425.50),
    ("Сейф СМ 23",                            35,  40, 1010.85),
    ("Сейф СМ 23-Э",                          34,  40,  874.00),
    ("Сейф СМ 25",                            24,  40,  630.20),
    ("Сейф СМ 25-Э",                          24,  40,  630.20),
    ("Сейф СМ 30",                            37,  40, 1010.85),
    ("Сейф СМ 30-Э",                          37,  40, 1010.85),
    ("Сейф СМ 50",                            59,  40, 1354.70),
    ("Сейф СМ 50-Э",                          59,  40, 1354.70),
    ("Стеллаж металлический 200*100*40 4п",   44,  34, 1114.35),
    ("Стеллаж металлический 200*100*50 4п",   55,  34, 1354.70),
    ("Стеллаж металлический 200*100*40 6п",   65,  34, 1624.95),
    ("Шкаф ШБС 01-МИНИ",                      64,  40, 1624.95),
    ("Шкаф ШБС 01-МИНИ-Т",                    62,  40, 1624.95),
    ("Шкаф бухгалтерский ШБС-01-17",         348,  40, 6492.90),
    ("Шкаф бухгалтерский ШБС-02-17",         348,  40, 6492.90),
    ("Стеллаж металлический СТ-СПЭ 4(4)",    44,  40, 1114.35),
    ("Стеллаж металлический СТ-СПЭ 5(4)",    55,  40, 1354.70),
    ("Стеллаж металлический СТ-СПЭ 4(6)",    65,  40, 1624.95),
    ("Шкаф оружейный ШО-5",                  348,  45, 6492.90),
    ("Шкаф оружейный ШО-1",                   65,  45, 1624.95),
    ("Шкаф оружейный ШО-2",                   42,  45, 1114.35),
    ("Шкаф оружейный ШО-3",                   37,  45, 1010.85),
    ("Шкаф оружейный ШО-4",                   88,  45, 2117.15),
    ("Верстак 1200 0 0",                       56,  45, 1354.70),
    ("Верстак 1400 0 0",                       83,  45, 2117.15),
    ("Стеллаж СТ-СПЭ 10.3 4 п",              37,  34, 1010.85),
    ("Стеллаж СТ-СПЭ 10.3 6 п",              52,  34, 1354.70),
    ("Стеллаж СТ-СПЭ 10.6 4 п",              68,  34, 1624.95),
    ("Стеллаж СТ-СПЭ 10.6 6 п",              95,  34, 2117.15),
]

EDIT_COLS = ["name", "volume", "reward", "logistics", "sc", "pvz", "ret", "cost"]
CALC_COLS = ["reward_rub", "acquiring_rub", "commission", "price", "net_profit"]
ALL_COLS  = EDIT_COLS + CALC_COLS

COL_LABELS = {
    "name": "Наименование", "volume": "Объём, л", "reward": "Возн. МП, %",
    "logistics": "Логист. Дальн", "sc": "СЦ, руб", "pvz": "ПВЗ, руб",
    "ret": "Возврат, руб", "cost": "Себестоимость",
    "reward_rub": "Возн. МП, руб", "acquiring_rub": "Эквайринг, руб",
    "commission": "Комиссия ОЗОН", "price": "РЕК. ЦЕНА", "net_profit": "Чистая прибыль",
}

def _f(v, d=0.0):
    try:
        return float(v) if v is not None and str(v).strip() != "" else d
    except (ValueError, TypeError):
        return d

def calc_price_row(row, roi: float) -> dict:
    cost = _f(row.get("cost"))
    if cost <= 0:
        return {c: 0.0 for c in CALC_COLS}
    shipment = _f(row.get("volume")) * TARIFF_PER_L
    fixed    = (_f(row.get("sc"), 20) + _f(row.get("pvz"), 25) + _f(row.get("ret"), 15)
                + shipment + _f(row.get("logistics")))
    pct      = (_f(row.get("reward")) + ACQUIRING_PCT) / 100
    price    = (cost * (roi / 100 + 1) + fixed) / (1 - pct)
    acq      = price * ACQUIRING_PCT / 100
    rew      = price * _f(row.get("reward")) / 100
    comm     = (acq + _f(row.get("sc"), 20) + _f(row.get("pvz"), 25) + _f(row.get("ret"), 15)
                + shipment + _f(row.get("logistics")) + rew)
    return {
        "reward_rub": round(rew, 2), "acquiring_rub": round(acq, 2),
        "commission": round(comm, 2), "price": round(price, 2),
        "net_profit": round(price - cost - comm, 2),
    }

def recalculate_prices(df: pd.DataFrame, roi: float) -> pd.DataFrame:
    df = df.copy()
    for idx, row in df.iterrows():
        for k, v in calc_price_row(row.to_dict(), roi).items():
            df.at[idx, k] = v
    return df

def load_price_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
        roi  = float(s.get("roi", 30.0))
        rows = s.get("rows", [])
        if rows:
            df = pd.DataFrame(rows)
            for c in ALL_COLS:
                if c not in df.columns:
                    df[c] = 0.0
            return roi, df[ALL_COLS]
    except Exception:
        pass
    rows = [{"name": n, "volume": v, "reward": r, "logistics": l,
             "sc": 20, "pvz": 25, "ret": 15, "cost": 0.0,
             **{c: 0.0 for c in CALC_COLS}} for n, v, r, l in DEFAULT_PRODUCTS]
    return 30.0, pd.DataFrame(rows, columns=ALL_COLS)

def save_price_state(df: pd.DataFrame, roi: float):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"roi": str(roi), "rows": df[EDIT_COLS].to_dict(orient="records")},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def df_to_excel(df: pd.DataFrame, sheet: str = "Лист1") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=sheet)
    return buf.getvalue()

# ══════════════════════════════════════════════════════════════════════════
# UI — ОБЩИЕ КОМПОНЕНТЫ
# ══════════════════════════════════════════════════════════════════════════

def _parse_period_start(period: str) -> datetime | None:
    """Разбирает начальную дату из строки '1 мая 2026 — 31 мая 2026'."""
    try:
        part = period.split("—")[0].strip().split()
        if len(part) < 3:
            return None
        day  = int(part[0])
        mon  = next((k for k, v in MONTHS_RU.items() if v == part[1].lower()), None)
        year = int(part[2])
        if mon is None:
            return None
        return datetime(year, mon, day)
    except Exception:
        return None

def get_prev_metrics(kind: str, current_period: str) -> tuple[dict, str]:
    """Returns metrics from the most recent history entry strictly before current_period."""
    cur_start = _parse_period_start(current_period)
    best_entry: dict | None = None
    best_start: datetime | None = None
    for entry in get_history().get(kind, []):
        ep = entry.get("period", "")
        if ep == current_period or not entry.get("metrics"):
            continue
        ep_start = _parse_period_start(ep)
        if ep_start is None:
            continue
        if cur_start is not None and ep_start >= cur_start:
            continue   # будущие периоды не берём
        if best_start is None or ep_start > best_start:
            best_start = ep_start
            best_entry = entry
    if best_entry:
        return best_entry["metrics"], best_entry.get("period", "")
    return {}, ""

def render_kpi(df: pd.DataFrame, kind: str = "", current_period: str = ""):
    rev    = df["Выручка"].sum()         if "Выручка"        in df.columns else 0
    profit = df["Прибыль"].sum()         if "Прибыль"        in df.columns else 0
    qty    = int(df["Количество"].sum()) if "Количество"     in df.columns else 0
    margin = df["Рентабельность"].mean() if "Рентабельность" in df.columns else 0

    prev_m, _ = ({}, "")
    if kind and current_period:
        prev_m, _ = get_prev_metrics(kind, current_period)

    def _d_rub(cur: float, key: str) -> str | None:
        if key not in prev_m:
            return None
        return f"{cur - prev_m[key]:+,.0f} ₽"

    def _d_pct(cur: float, key: str) -> str | None:
        if key not in prev_m:
            return None
        return f"{cur - prev_m[key]:+.1f}%"

    def _d_qty(cur: float, key: str) -> str | None:
        if key not in prev_m:
            return None
        return f"{int(cur - prev_m[key]):+,} шт."

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Выручка",        f"{rev:,.0f} ₽",   delta=_d_rub(rev, "revenue"))
    c2.metric("Чистая прибыль", f"{profit:,.0f} ₽", delta=_d_rub(profit, "profit"))
    c3.metric("Рентабельность", f"{margin:.1f}%",   delta=_d_pct(margin, "margin"))
    c4.metric("Заказов",        f"{qty:,} шт.",     delta=_d_qty(qty, "orders"))

def render_sku_table(df: pd.DataFrame, source_col: str = "Поступление от ОЗОН",
                     key_prefix: str = "", df_raw: pd.DataFrame | None = None):
    grp = df.groupby("SKU", sort=False).agg(
        name  =("Название товара", "first"),
        qty   =("Количество",       "sum"),
        rev   =("Выручка",          "sum"),
        exp   =("Расходы",          "sum"),
        net   =(source_col,         "sum"),
        cost  =("Себестоимость",    "sum"),
        profit=("Прибыль",          "sum"),
    ).reset_index()
    grp["Рент., %"] = grp.apply(
        lambda r: round(r["net"] / r["cost"] * 100 - 100, 1) if r["cost"] > 0 else 0.0, axis=1
    )
    grp.columns = ["SKU", "Название товара", "Кол-во", "Выручка", "Расходы",
                   "Поступление", "Себестоимость", "Прибыль", "Рент., %"]

    search = st.text_input("🔍 Поиск", key=f"{key_prefix}search_{source_col}")
    if search:
        mask = grp.apply(lambda r: search.lower() in str(r.values).lower(), axis=1)
        grp  = grp[mask]

    # ── Строка итогов ──────────────────────────────────────────────────────
    net_tot  = grp["Поступление"].sum()
    cost_tot = grp["Себестоимость"].sum()
    totals = pd.DataFrame([{
        "SKU": "— ИТОГО —", "Название товара": "",
        "Кол-во":       grp["Кол-во"].sum(),
        "Выручка":      grp["Выручка"].sum(),
        "Расходы":      grp["Расходы"].sum(),
        "Поступление":  net_tot,
        "Себестоимость": cost_tot,
        "Прибыль":      grp["Прибыль"].sum(),
        "Рент., %":     round(net_tot / cost_tot * 100 - 100, 1) if cost_tot > 0 else 0.0,
    }])
    grp_display = pd.concat([grp, totals], ignore_index=True)

    fmt = {
        "Выручка": "{:,.2f}", "Расходы": "{:,.2f}", "Поступление": "{:,.2f}",
        "Себестоимость": "{:,.2f}", "Прибыль": "{:,.2f}", "Рент., %": "{:.1f}%",
    }

    st.caption("Кликните на строку, чтобы увидеть все операции по SKU")
    event = st.dataframe(
        grp_display.style.format(fmt).map(
            lambda v: "color: #EF4444" if isinstance(v, (int, float)) and v < 0
                      else "color: #22C55E" if isinstance(v, (int, float)) and v > 0 else "",
            subset=["Прибыль", "Рент., %"]
        ),
        use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        key=f"{key_prefix}tbl_{source_col}",
    )

    # ── Уровень 2: операции по выбранному SKU ─────────────────────────────
    rows = event.selection.rows if hasattr(event, "selection") else []
    if rows:
        idx = rows[0]
        if idx < len(grp):   # не строка итогов
            sel_sku  = grp.iloc[idx]["SKU"]
            sel_name = grp.iloc[idx]["Название товара"]
            ops = df[df["SKU"] == sel_sku].copy()
            if "Дата начисления" in ops.columns:
                ops = ops.sort_values("Дата начисления")
            detail_cols = [c for c in
                           ["ID начисления", "Номер заказа", "Дата начисления",
                            "Тип начисления", "Количество", "Выручка", "Расходы",
                            source_col, "Прибыль"]
                           if c in ops.columns]
            money_cols = [c for c in ["Выручка", "Расходы", source_col, "Прибыль"] if c in detail_cols]

            can_drill = df_raw is not None and "ID начисления" in ops.columns

            with st.expander(
                f"📋 Заказы: {sel_name}  ·  SKU {sel_sku}  ·  {len(ops)} шт."
                + (" · Кликните строку → все операции по начислению" if can_drill else ""),
                expanded=True,
            ):
                ops = ops.reset_index(drop=True)
                if can_drill:
                    ops_event = st.dataframe(
                        ops[detail_cols].style
                            .format({c: "{:,.2f}" for c in money_cols})
                            .map(lambda v: "color: #EF4444" if isinstance(v, (int, float)) and v < 0
                                 else "color: #22C55E" if isinstance(v, (int, float)) and v > 0 else "",
                                 subset=[c for c in ["Прибыль"] if c in detail_cols]),
                        use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row",
                        key=f"{key_prefix}ops_{sel_sku}",
                    )
                    # ── Уровень 3: сырые строки начисления ──────────────────
                    ops_rows = ops_event.selection.rows if hasattr(ops_event, "selection") else []
                    if ops_rows:
                        order_id = str(ops.iloc[ops_rows[0]].get("ID начисления", "")).strip()
                        if order_id:
                            raw_id_col = "ID начисления"
                            raw_match = df_raw[
                                df_raw[raw_id_col].astype(str).str.strip() == order_id
                            ].copy()
                            raw_show = [c for c in df_raw.columns
                                        if c not in ("ID начисления",)
                                        and not str(c).startswith("Unnamed")]
                            raw_show = ["ID начисления"] + raw_show
                            raw_show = [c for c in raw_show if c in raw_match.columns]
                            st.markdown(f"**🔍 Все строки начисления `{order_id}`** — {len(raw_match)} операций")
                            st.dataframe(
                                raw_match[raw_show].reset_index(drop=True),
                                use_container_width=True, hide_index=True,
                            )
                else:
                    st.dataframe(
                        ops[detail_cols].style
                            .format({c: "{:,.2f}" for c in money_cols})
                            .map(lambda v: "color: #EF4444" if isinstance(v, (int, float)) and v < 0
                                 else "color: #22C55E" if isinstance(v, (int, float)) and v > 0 else "",
                                 subset=[c for c in ["Прибыль"] if c in detail_cols]),
                        use_container_width=True, hide_index=True,
                    )

    st.download_button("📥 Скачать Excel", df_to_excel(grp, "Аналитика"),
                       "analytics.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"{key_prefix}dl_{source_col}")

def render_recommendations(df: pd.DataFrame):
    threshold, insights = compute_insights(df)
    if insights.empty:
        st.success("✅ Нет товаров с высокой маржой и слабыми продажами")
        return
    st.caption(f"Порог низких продаж: < {int(threshold)} шт. · лидер: {int(threshold * 2)} шт.")
    for _, r in insights.iterrows():
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            c1.markdown(f"**{r['name']}**  \n`SKU: {r['SKU']}`")
            c2.metric("Продано",        f"{int(r['qty'])} шт.")
            c3.metric("Рентабельность", f"{r['margin']:.1f}%")
            c4.metric("Прибыль",        f"{r['profit']:,.0f} ₽")
            st.caption("🔥 Высокая маржа + слабые продажи — запустить промо или снизить цену на 5–10%")

# ── Боковая панель истории ─────────────────────────────────────────────────

def delete_history_entry(kind: str, rec_id: str):
    hist = get_history()
    entry = next((e for e in hist[kind] if e["id"] == rec_id), None)
    if entry:
        try:
            Path(entry["parquet"]).unlink(missing_ok=True)
        except Exception:
            pass
        hist[kind] = [e for e in hist[kind] if e["id"] != rec_id]
        _save_history()

def render_history_sidebar(kind: str) -> dict | None:
    """
    Показывает историю загрузок в боковой панели.
    Возвращает запись истории, если пользователь нажал «Открыть».
    """
    entries = get_history().get(kind, [])
    if not entries:
        return None

    st.sidebar.markdown("---")
    st.sidebar.markdown("**📁 История отчётов**")

    selected = None
    for e in entries:
        m = e.get("metrics", {})
        caption = f"Загружен {e['uploaded_at']}"
        if m:
            caption += f" · Прибыль: {m.get('profit', 0):,.0f} ₽"

        with st.sidebar.container(border=True):
            st.markdown(f"**📅 {e['period']}**")
            st.caption(caption)
            st.caption(f"Файл: {e['filename']}")
            c1, c2 = st.columns([3, 1])
            with c1:
                if st.button("Открыть", key=f"hist_{kind}_{e['id']}", use_container_width=True):
                    selected = e
            with c2:
                if st.button("🗑️", key=f"del_{kind}_{e['id']}", help="Удалить из истории"):
                    delete_history_entry(kind, e["id"])
                    st.rerun()

    return selected

# ══════════════════════════════════════════════════════════════════════════
# СТРАНИЦЫ
# ══════════════════════════════════════════════════════════════════════════

def _load_ozon_report(df_raw: pd.DataFrame, filename: str, from_history: bool = False, period: str = ""):
    regular, returns = build_accrual_summary(df_raw)
    detected = period or period_from_filename(filename)
    st.session_state.ozon_df_raw    = df_raw
    st.session_state.ozon_regular   = regular
    st.session_state.ozon_returns   = returns
    st.session_state.ozon_period    = detected
    st.session_state.ozon_need_period = (detected == "")
    st.session_state.ozon_filename  = filename
    if not from_history:
        save_report_to_history("ozon", filename, df_raw, regular, period=detected)

def page_ozon():
    st.header("📊 OZON — Аналитика начислений")

    # История в сайдбаре
    hist_entry = render_history_sidebar("ozon")
    if hist_entry:
        df_hist = load_report_from_history(hist_entry)
        if df_hist is not None:
            with st.spinner("Загрузка из истории..."):
                _load_ozon_report(df_hist, hist_entry["filename"], from_history=True)
            st.rerun()
        else:
            st.sidebar.error("Файл истории не найден")

    uploaded = st.file_uploader(
        "Загрузить отчёт по начислениям (.xlsx)",
        type=["xlsx", "xls"],
        help="Финансы → Экономика магазина → Скачать отчёт по начислениям",
    )

    if uploaded is not None:
        cache_key = f"ozon_{uploaded.name}_{uploaded.size}"
        if st.session_state.get("ozon_cache_key") != cache_key:
            with st.spinner("Обработка данных..."):
                df_raw = parse_accrual_excel(uploaded)
                _load_ozon_report(df_raw, uploaded.name)
                st.session_state.ozon_cache_key = cache_key

    if "ozon_regular" not in st.session_state:
        st.info("Загрузите файл: **Финансы → Экономика магазина → Скачать отчёт по начислениям**")
        return

    # Если период не удалось определить из имени файла — просим ввести вручную
    if st.session_state.get("ozon_need_period"):
        st.warning("Не удалось определить период из имени файла. Укажите его вручную:")
        col_p, col_btn = st.columns([3, 1])
        with col_p:
            manual = st.text_input("Период (например: 01.05.2026 — 31.05.2026)",
                                   key="ozon_period_input",
                                   placeholder="01.05.2026 — 31.05.2026")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("✓ Сохранить", key="ozon_period_save"):
                if manual.strip():
                    st.session_state.ozon_period      = manual.strip()
                    st.session_state.ozon_need_period = False
                    # Обновляем запись в истории с указанным периодом
                    save_report_to_history(
                        "ozon",
                        st.session_state.get("ozon_filename", ""),
                        st.session_state.ozon_df_raw,
                        st.session_state.ozon_regular,
                        period=manual.strip(),
                    )
                    st.rerun()
        st.divider()

    period  = st.session_state.get("ozon_period", "")
    regular = st.session_state.ozon_regular
    returns = st.session_state.ozon_returns

    if period:
        st.caption(f"📅 Период отчёта: **{period}**")

    render_kpi(regular, kind="ozon", current_period=period)
    st.divider()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["📋 Начисления", "🔄 Возвраты", "📊 Графики", "📈 Сравнение", "💡 Рекомендации"])

    with tab1:
        render_sku_table(regular, key_prefix="ozon_",
                         df_raw=st.session_state.get("ozon_df_raw"))
        if returns is not None and not returns.empty:
            with st.expander(f"↩ Возвраты — {len(returns)} шт. (сводка)"):
                ret_summary = {
                    "Обратная логистика":  returns["_ret_log_cost"].sum(),
                    "Поступление от ОЗОН": returns["Поступление от ОЗОН"].sum(),
                    "Себестоимость":       returns["Себестоимость"].sum(),
                    "Прибыль/Убыток":      returns["Прибыль"].sum(),
                }
                st.dataframe(pd.DataFrame([ret_summary]), hide_index=True, use_container_width=True)

    with tab2:
        if returns is None or returns.empty:
            st.success("✅ Возвратов нет")
        else:
            st.subheader("Типы возвратов")
            st.caption("Измените тип → нажмите «Сохранить» → данные пересчитаются")

            ret_settings = get_return_settings()
            rows = []
            for _, row in returns.iterrows():
                aid  = str(row["ID начисления"])
                s    = ret_settings.get(aid, {})
                rkey = s.get("type", "возврат")
                rows.append({
                    "ID начисления":    aid,
                    "SKU":              str(row.get("SKU", "")),
                    "Название товара":  str(row.get("Название товара", ""))[:50],
                    "Тип возврата":     RETURN_KEYS_LABELS.get(rkey, "Возврат к продаже"),
                    "Стоим. доработки": float(s.get("restoration_cost", 0.0)),
                    "Себестоимость":    float(row.get("Себестоимость", 0.0)),
                    "Прибыль":          float(row.get("Прибыль", 0.0)),
                })
            ret_df = pd.DataFrame(rows)

            edited = st.data_editor(
                ret_df,
                column_config={
                    "ID начисления":    st.column_config.TextColumn(disabled=True),
                    "SKU":              st.column_config.TextColumn(disabled=True),
                    "Название товара":  st.column_config.TextColumn(disabled=True),
                    "Тип возврата":     st.column_config.SelectboxColumn(
                        options=list(RETURN_KEYS_LABELS.values())),
                    "Стоим. доработки": st.column_config.NumberColumn(format="%.2f", min_value=0.0),
                    "Себестоимость":    st.column_config.NumberColumn(format="%.2f", disabled=True),
                    "Прибыль":          st.column_config.NumberColumn(format="%.2f", disabled=True),
                },
                hide_index=True, use_container_width=True,
            )

            if st.button("💾 Сохранить и пересчитать", type="primary"):
                new_settings = dict(ret_settings)
                for _, row in edited.iterrows():
                    aid  = row["ID начисления"]
                    rkey = RETURN_TYPE_KEYS.get(row["Тип возврата"], "возврат")
                    new_settings[aid] = {"type": rkey}
                    if rkey == "восстановление":
                        new_settings[aid]["restoration_cost"] = float(row["Стоим. доработки"])
                set_return_settings(new_settings)
                regular_new, returns_new = build_accrual_summary(st.session_state.ozon_df_raw)
                st.session_state.ozon_regular = regular_new
                st.session_state.ozon_returns = returns_new
                st.success("✓ Сохранено и пересчитано")
                st.rerun()

    with tab3:
        metric = st.radio("Топ товаров по:", ["Прибыль", "Выручка", "Продано"], horizontal=True)
        render_charts_section(regular, "ozon_", metric)

    with tab4:
        render_comparison_tab("ozon", period, regular, "ozon_")

    with tab5:
        st.subheader("💡 Умные рекомендации")
        render_recommendations(regular)


def _load_ym_report(df_raw: pd.DataFrame, filename: str, from_history: bool = False, period: str = ""):
    df       = build_ym_summary(df_raw)
    detected = period or period_from_filename(filename)
    st.session_state.ym_df_raw      = df_raw
    st.session_state.ym_df          = df
    st.session_state.ym_period      = detected
    st.session_state.ym_need_period = (detected == "")
    st.session_state.ym_filename    = filename
    if not from_history and not df.empty:
        save_report_to_history("ym", filename, df_raw, df, period=detected)

def page_ym():
    st.header("🎯 Яндекс Маркет — Аналитика")

    hist_entry = render_history_sidebar("ym")
    if hist_entry:
        df_hist = load_report_from_history(hist_entry)
        if df_hist is not None:
            with st.spinner("Загрузка из истории..."):
                _load_ym_report(df_hist, hist_entry["filename"], from_history=True)
            st.rerun()
        else:
            st.sidebar.error("Файл истории не найден")

    uploaded = st.file_uploader(
        "Загрузить отчёт о платежах (.xlsx)",
        type=["xlsx", "xls"],
        help="Финансы → Финансовые отчёты → О платежах за период",
    )

    if uploaded is not None:
        cache_key = f"ym_{uploaded.name}_{uploaded.size}"
        if st.session_state.get("ym_cache_key") != cache_key:
            with st.spinner("Обработка данных..."):
                df_raw = parse_ym_excel(uploaded)
                _load_ym_report(df_raw, uploaded.name)
                st.session_state.ym_cache_key = cache_key

    if "ym_df" not in st.session_state:
        st.info("Загрузите файл: **Финансы → Финансовые отчёты → О платежах за период**")
        return

    df = st.session_state.ym_df
    if df.empty:
        st.error("Не удалось загрузить данные. Проверьте формат файла.")
        return

    if st.session_state.get("ym_need_period"):
        st.warning("Не удалось определить период из имени файла. Укажите его вручную:")
        col_p, col_btn = st.columns([3, 1])
        with col_p:
            manual = st.text_input("Период (например: 01.05.2026 — 31.05.2026)",
                                   key="ym_period_input",
                                   placeholder="01.05.2026 — 31.05.2026")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("✓ Сохранить", key="ym_period_save"):
                if manual.strip():
                    st.session_state.ym_period      = manual.strip()
                    st.session_state.ym_need_period = False
                    save_report_to_history(
                        "ym",
                        st.session_state.get("ym_filename", ""),
                        st.session_state.ym_df_raw,
                        st.session_state.ym_df,
                        period=manual.strip(),
                    )
                    st.rerun()
        st.divider()

    period = st.session_state.get("ym_period", "")
    if period:
        st.caption(f"📅 Период отчёта: **{period}**")

    render_kpi(df, kind="ym", current_period=period)
    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📋 Сводка по SKU", "📊 Графики", "📈 Сравнение", "💡 Рекомендации"])

    with tab1:
        render_sku_table(df, source_col="Поступление от ОЗОН", key_prefix="ym_")

    with tab2:
        metric = st.radio("Топ товаров по:", ["Прибыль", "Выручка", "Продано"],
                          horizontal=True, key="ym_metric")
        render_charts_section(df, "ym_", metric)

    with tab3:
        render_comparison_tab("ym", period, df, "ym_")

    with tab4:
        st.subheader("💡 Умные рекомендации")
        render_recommendations(df)


def _make_costs_excel(costs: dict, cost_names: dict) -> bytes:
    """Генерирует Excel с тремя колонками: SKU, Название, Себестоимость."""
    rows = [{"SKU / Артикул": sku,
             "Название товара": cost_names.get(sku, ""),
             "Себестоимость, руб.": float(v)}
            for sku, v in sorted(costs.items())]
    if not rows:
        rows = [{"SKU / Артикул": "", "Название товара": "", "Себестоимость, руб.": 0.0}]
    return df_to_excel(pd.DataFrame(rows), "Себестоимость")


def _costs_panel(kind: str):
    k = kind
    costs      = get_costs(k)
    cost_names = get_cost_names(k)

    c_tmpl, c_exp, _ = st.columns([2, 2, 6])
    with c_tmpl:
        tmpl_bytes = df_to_excel(
            pd.DataFrame({"SKU / Артикул": [""], "Название товара": [""], "Себестоимость, руб.": [0.0]}),
            "Себестоимость",
        )
        st.download_button(
            "📋 Скачать шаблон Excel",
            tmpl_bytes,
            "шаблон_себестоимость.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"costs_tmpl_{k}",
        )
    with c_exp:
        st.download_button(
            "📤 Экспорт текущей базы",
            _make_costs_excel(costs, cost_names),
            f"себестоимость_{k}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"costs_exp_{k}",
        )

    st.divider()
    col_left, col_right = st.columns([1, 2])

    with col_left:
        with st.container(border=True):
            st.subheader("📥 Загрузить заполненный файл")
            st.caption("Колонки: **SKU / Артикул**, **Название товара**, **Себестоимость, руб.**")
            imp = st.file_uploader("Excel или CSV", type=["xlsx", "xls", "csv"], key=f"costs_imp_{k}")
            if imp:
                try:
                    df_imp = (pd.read_csv(imp, dtype=str) if imp.name.endswith(".csv")
                              else pd.read_excel(imp, dtype=str))
                    df_imp.columns = [str(c).strip() for c in df_imp.columns]
                    cols_lower = {c.lower(): c for c in df_imp.columns}
                    sku_col   = next((cols_lower[x] for x in cols_lower
                                      if any(t in x for t in ["sku", "артикул", "id"])), df_imp.columns[0])
                    name_col  = next((cols_lower[x] for x in cols_lower
                                      if any(t in x for t in ["название", "наименование", "name"])), None)
                    cost_col  = next((cols_lower[x] for x in cols_lower
                                      if any(t in x for t in ["себестоимость", "цена", "cost", "price"])), None)
                    new_costs = dict(get_costs(k))
                    new_names = dict(get_cost_names(k))
                    count_c, count_n = 0, 0
                    for _, row in df_imp.iterrows():
                        sv = str(row.get(sku_col, "")).strip()
                        if not sv or sv.lower() in ("nan", "sku / артикул", ""):
                            continue
                        if cost_col:
                            cs = (str(row.get(cost_col, "")).replace("₽", "")
                                  .replace("\xa0", "").replace(" ", "").replace(",", "."))
                            try:
                                new_costs[sv] = float(cs)
                                count_c += 1
                            except ValueError:
                                pass
                        if name_col:
                            nv = str(row.get(name_col, "")).strip()
                            if nv and nv.lower() != "nan":
                                new_names[sv] = nv
                                count_n += 1
                    set_costs(new_costs, k)
                    set_cost_names(new_names, k)
                    parts = []
                    if count_c: parts.append(f"{count_c} цен")
                    if count_n: parts.append(f"{count_n} названий")
                    st.success(f"✓ Импортировано: {', '.join(parts) or '0 записей'}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")

        with st.container(border=True):
            st.subheader("➕ Добавить / изменить")
            sku_in  = st.text_input("Артикул или SKU", key=f"costs_sku_in_{k}")
            name_in = st.text_input("Название (необязательно)", key=f"costs_name_in_{k}")
            cost_in = st.number_input("Себестоимость, руб.", min_value=0.0, step=100.0, key=f"costs_cost_in_{k}")
            if st.button("💾 Сохранить", type="primary", use_container_width=True, key=f"costs_save_{k}"):
                if sku_in.strip():
                    c = dict(get_costs(k))
                    c[sku_in.strip()] = cost_in
                    set_costs(c, k)
                    if name_in.strip():
                        n = dict(get_cost_names(k))
                        n[sku_in.strip()] = name_in.strip()
                        set_cost_names(n, k)
                    st.success(f"✓ {sku_in.strip()} = {cost_in:.2f} руб.")
                    st.rerun()

        with st.container(border=True):
            st.subheader("🗑️ Удалить")
            del_sku = st.text_input("SKU для удаления", key=f"costs_del_sku_{k}")
            if st.button("Удалить", type="secondary", use_container_width=True, key=f"costs_del_{k}"):
                cur = dict(get_costs(k))
                if del_sku.strip() in cur:
                    del cur[del_sku.strip()]
                    set_costs(cur, k)
                    cur_n = dict(get_cost_names(k))
                    cur_n.pop(del_sku.strip(), None)
                    set_cost_names(cur_n, k)
                    st.success(f"✓ Удалено: {del_sku}")
                    st.rerun()
                else:
                    st.warning("SKU не найден")

    with col_right:
        costs      = get_costs(k)
        cost_names = get_cost_names(k)
        st.subheader(f"Текущая база ({len(costs)} записей)")
        if costs:
            rows_c = [{"Артикул / SKU": sku_v,
                       "Название товара": cost_names.get(sku_v, ""),
                       "Себестоимость, руб.": float(v)}
                      for sku_v, v in sorted(costs.items())]
            df_costs = pd.DataFrame(rows_c)
            search_c = st.text_input("🔍 Поиск", key=f"costs_search_{k}")
            if search_c:
                mask = (df_costs["Артикул / SKU"].str.contains(search_c, case=False, na=False) |
                        df_costs["Название товара"].str.contains(search_c, case=False, na=False))
                df_costs = df_costs[mask]
            sel_event = st.dataframe(
                df_costs, use_container_width=True, hide_index=True, height=500,
                on_select="rerun", selection_mode="multi-row", key=f"costs_table_{k}",
            )
            sel_rows = sel_event.selection.rows if sel_event.selection else []
            if sel_rows:
                sel_skus = [df_costs.iloc[i]["Артикул / SKU"] for i in sel_rows]
                st.caption(f"Выбрано: {len(sel_skus)} — {', '.join(sel_skus[:5])}{'…' if len(sel_skus) > 5 else ''}")
                if st.button(f"🗑 Удалить выбранные ({len(sel_skus)})", type="primary",
                             use_container_width=True, key=f"costs_del_sel_{k}"):
                    cur = dict(get_costs(k))
                    cur_n = dict(get_cost_names(k))
                    for sku_v in sel_skus:
                        cur.pop(sku_v, None)
                        cur_n.pop(sku_v, None)
                    set_costs(cur, k)
                    set_cost_names(cur_n, k)
                    st.rerun()
        else:
            st.info("База пуста — скачайте шаблон, заполните и загрузите.")


def page_costs():
    st.header("💰 База себестоимости")
    st.caption("Общая для всех пользователей — изменения видны сразу у всех")

    tab_oz, tab_ym = st.tabs(["🟠 OZON", "🟡 Яндекс Маркет"])
    with tab_oz:
        _costs_panel("ozon")
    with tab_ym:
        _costs_panel("ym")


def page_calculator():
    st.header("🛒 Калькулятор цен ОЗОН · Дальний кластер")

    if "calc_initialized" not in st.session_state:
        roi, df = load_price_state()
        st.session_state.calc_roi         = roi
        st.session_state.calc_df          = recalculate_prices(df, roi)
        st.session_state.calc_initialized = True

    col_roi, col_upload, _ = st.columns([2, 3, 5])

    with col_roi:
        roi_new = st.number_input("Желаемая рентабельность, %",
                                  min_value=0.0, max_value=9999.0,
                                  value=float(st.session_state.calc_roi),
                                  step=1.0, format="%.1f")
        if roi_new != st.session_state.calc_roi:
            st.session_state.calc_roi = roi_new
            st.session_state.calc_df  = recalculate_prices(st.session_state.calc_df, roi_new)
            save_price_state(st.session_state.calc_df, roi_new)
            st.rerun()

    with col_upload:
        up = st.file_uploader("📂 Загрузить себестоимость (Excel)", type=["xlsx"],
                              help="Колонки: Наименование, Себестоимость")
        if up:
            try:
                cost_df = pd.read_excel(up, skiprows=1)
                cost_df.columns = [str(c).strip() for c in cost_df.columns]
                ncol = next((c for c in cost_df.columns if "наим" in c.lower()), None)
                ccol = next((c for c in cost_df.columns if "себес" in c.lower()), None)
                if ncol and ccol:
                    cm = {str(r[ncol]).strip().lower(): float(r[ccol])
                          for _, r in cost_df.iterrows() if pd.notna(r.get(ccol))}
                    df = st.session_state.calc_df.copy()
                    matched = 0
                    for idx, row in df.iterrows():
                        key = str(row["name"]).strip().lower()
                        if key in cm:
                            df.at[idx, "cost"] = cm[key]
                            matched += 1
                    st.session_state.calc_df = recalculate_prices(df, st.session_state.calc_roi)
                    save_price_state(st.session_state.calc_df, st.session_state.calc_roi)
                    st.success(f"✓ Обновлено: {matched} товаров")
                    st.rerun()
            except Exception as e:
                st.error(f"Ошибка: {e}")

    edited = st.data_editor(
        st.session_state.calc_df,
        column_config={
            "name":          st.column_config.TextColumn("Наименование",    width="large"),
            "volume":        st.column_config.NumberColumn("Объём, л",      format="%.0f", min_value=0),
            "reward":        st.column_config.NumberColumn("Возн. МП, %",   format="%.0f", min_value=0),
            "logistics":     st.column_config.NumberColumn("Логист. Дальн", format="%.2f", min_value=0),
            "sc":            st.column_config.NumberColumn("СЦ, руб",       format="%.0f", min_value=0),
            "pvz":           st.column_config.NumberColumn("ПВЗ, руб",      format="%.0f", min_value=0),
            "ret":           st.column_config.NumberColumn("Возврат, руб",  format="%.0f", min_value=0),
            "cost":          st.column_config.NumberColumn("Себестоимость", format="%.2f", min_value=0),
            "reward_rub":    st.column_config.NumberColumn("Возн. МП, руб",   format="%.2f", disabled=True),
            "acquiring_rub": st.column_config.NumberColumn("Эквайринг, руб",  format="%.2f", disabled=True),
            "commission":    st.column_config.NumberColumn("Комиссия ОЗОН",   format="%.2f", disabled=True),
            "price":         st.column_config.NumberColumn("РЕК. ЦЕНА",       format="%.2f", disabled=True),
            "net_profit":    st.column_config.NumberColumn("Чистая прибыль",  format="%.2f", disabled=True),
        },
        num_rows="dynamic", use_container_width=True, hide_index=True,
    )

    try:
        changed = not edited[EDIT_COLS].reset_index(drop=True).equals(
            st.session_state.calc_df[EDIT_COLS].reset_index(drop=True))
    except Exception:
        changed = True

    if changed:
        for c in ["volume", "reward", "logistics", "cost"]:
            edited[c] = pd.to_numeric(edited[c], errors="coerce").fillna(0)
        edited["sc"]  = pd.to_numeric(edited["sc"],  errors="coerce").fillna(20)
        edited["pvz"] = pd.to_numeric(edited["pvz"], errors="coerce").fillna(25)
        edited["ret"] = pd.to_numeric(edited["ret"], errors="coerce").fillna(15)
        for c in CALC_COLS:
            if c not in edited.columns:
                edited[c] = 0.0
        st.session_state.calc_df = recalculate_prices(edited[ALL_COLS], st.session_state.calc_roi)
        save_price_state(st.session_state.calc_df, st.session_state.calc_roi)
        st.rerun()

    st.divider()
    dc1, dc2, _ = st.columns([2, 2, 6])
    with dc1:
        st.download_button(
            "📊 Скачать таблицу цен",
            df_to_excel(st.session_state.calc_df.rename(columns=COL_LABELS), "Цены ОЗОН"),
            "ozon_prices.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with dc2:
        tmpl = st.session_state.calc_df[["name", "cost"]].rename(
            columns={"name": "Наименование", "cost": "Себестоимость, руб."})
        st.download_button(
            "📋 Шаблон себестоимости",
            df_to_excel(tmpl, "Себестоимость"),
            "себестоимость_шаблон.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# ══════════════════════════════════════════════════════════════════════════
# АВТОРИЗАЦИЯ
# ══════════════════════════════════════════════════════════════════════════

def page_auth():
    t = get_theme()
    st.markdown(
        f"<h2 style='text-align:center;color:{t['text']};margin-bottom:8px'>📊 Аналитика маркетплейсов</h2>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='max-width:420px;margin:0 auto'>", unsafe_allow_html=True)

    tab_in, tab_reg = st.tabs(["Войти", "Регистрация"])

    with tab_in:
        login = st.text_input("Логин", key="auth_login")
        password = st.text_input("Пароль", type="password", key="auth_password")
        if st.button("Войти", type="primary", use_container_width=True, key="auth_login_btn"):
            users = get_users()
            # admin может войти всегда
            if login == ADMIN_LOGIN and password == ADMIN_PASSWORD:
                st.session_state["logged_in"] = True
                st.session_state["username"] = ADMIN_LOGIN
                st.session_state["role"] = "admin"
                st.rerun()
            elif login in users:
                u = users[login]
                if u["password"] != _hash_pw(password):
                    st.error("Неверный пароль.")
                elif u.get("status") != "approved":
                    st.warning("Ваш аккаунт ещё не одобрен администратором.")
                else:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = login
                    st.session_state["role"] = u.get("role", "user")
                    st.rerun()
            else:
                st.error("Пользователь не найден.")

    with tab_reg:
        new_login = st.text_input("Придумайте логин", key="reg_login")
        new_pw    = st.text_input("Придумайте пароль", type="password", key="reg_pw")
        new_pw2   = st.text_input("Повторите пароль", type="password", key="reg_pw2")
        if st.button("Зарегистрироваться", type="primary", use_container_width=True, key="reg_btn"):
            users = get_users()
            if not new_login.strip():
                st.error("Введите логин.")
            elif new_login in users or new_login == ADMIN_LOGIN:
                st.error("Логин уже занят.")
            elif len(new_pw) < 4:
                st.error("Пароль должен быть не короче 4 символов.")
            elif new_pw != new_pw2:
                st.error("Пароли не совпадают.")
            else:
                users[new_login] = {
                    "password": _hash_pw(new_pw),
                    "status": "pending",
                    "role": "user",
                }
                set_users(users)
                _tg_notify_registration(new_login)
                st.success("Заявка отправлена. Ожидайте одобрения администратора.")

    st.markdown("</div>", unsafe_allow_html=True)


@st.dialog("🔧 Панель разработчика", width="large")
def admin_panel():
    is_admin = st.session_state.get("role") == "admin"
    if not is_admin:
        pw = st.text_input("Пароль администратора", type="password", key="adm_pw_input")
        if pw != ADMIN_PASSWORD:
            if pw:
                st.error("Неверный пароль.")
            st.stop()

    users = get_users()
    pending = {k: v for k, v in users.items() if v.get("status") == "pending"}
    approved = {k: v for k, v in users.items() if v.get("status") == "approved" and k != ADMIN_LOGIN}

    st.subheader("Заявки на регистрацию")
    if not pending:
        st.info("Новых заявок нет.")
    else:
        for uname, _ in list(pending.items()):
            c1, c2, c3 = st.columns([4, 2, 2])
            c1.write(f"**{uname}**")
            if c2.button("✅ Одобрить", key=f"appr_{uname}"):
                users[uname]["status"] = "approved"
                set_users(users)
                st.rerun()
            if c3.button("❌ Отклонить", key=f"deny_{uname}"):
                del users[uname]
                set_users(users)
                st.rerun()

    st.markdown("---")
    st.subheader("Пользователи")
    if not approved:
        st.info("Нет одобренных пользователей.")
    else:
        for uname in list(approved.keys()):
            c1, c2, c3 = st.columns([3, 4, 2])
            c1.write(f"**{uname}**")
            new_comment = c2.text_input(
                "Комментарий",
                value=users[uname].get("comment", ""),
                key=f"comment_{uname}",
                label_visibility="collapsed",
                placeholder="Комментарий...",
            )
            if new_comment != users[uname].get("comment", ""):
                users[uname]["comment"] = new_comment
                set_users(users)
            if c3.button("🗑 Удалить", key=f"del_{uname}"):
                del users[uname]
                set_users(users)
                st.rerun()

    st.markdown("---")
    if st.button("💾 Сохранить данные в GitHub сейчас", type="primary", use_container_width=True):
        with st.spinner("Сохраняю..."):
            _github_commit_files()
        st.success("Готово — проверь коммиты на GitHub.")


# ══════════════════════════════════════════════════════════════════════════
# ГЛАВНАЯ
# ══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Аналитика маркетплейсов",
    page_icon="📊",
    layout="wide",
)

# Применяем тему до любого контента
apply_theme(get_theme())
# Убеждаемся что admin-аккаунт существует
_ensure_admin()
# Запускаем фоновый polling Telegram (один раз на весь процесс)
_start_tg_polling()
# Автосохранение данных в GitHub раз в час
_start_git_autosave()
# Переводим старые числовые периоды в истории в формат с месяцем словом
migrate_history_periods()

# ── Проверка авторизации ──────────────────────────────────────────────────
if not st.session_state.get("logged_in"):
    page_auth()
    st.stop()

# ── Сайдбар ───────────────────────────────────────────────────────────────
st.sidebar.title("📊 Аналитика")

_uname = st.session_state.get("username", "")
st.sidebar.caption(f"👤 {_uname}")
if st.sidebar.button("Выйти", key="logout_btn"):
    for _k in ["logged_in", "username", "role"]:
        st.session_state.pop(_k, None)
    st.rerun()

page = st.sidebar.radio(
    "Раздел",
    ["📊 OZON Аналитика", "🎯 Яндекс Маркет", "💰 Себестоимость", "🛒 Калькулятор цен"],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")

with st.sidebar.expander("📖 Инструкция по использованию"):
    st.markdown("""
**📊 OZON Аналитика**
Загрузите: *Финансы → Экономика магазина → Скачать отчёт по начислениям*
- **Начисления** — сводка по SKU с итогами. Кликните строку → раскроются все операции по SKU
- **Возвраты** — смените тип возврата (бой / восстановление / к продаже) → пересчёт прибыли
- **Графики** — 4 чарта. Кнопка **⤢** разворачивает один на всю ширину, **⤡** — сворачивает
- **Сравнение** — выберите несколько отчётов из истории и метрику; линии наложатся по дням периода
- **Рекомендации** — товары с высокой маржой и слабыми продажами (кандидаты для промо)

---
**🎯 Яндекс Маркет**
Загрузите: *Финансы → Финансовые отчёты → О платежах за период*
Логика разделов — аналогична OZON.

---
**💰 Себестоимость**
Общая база для всех пользователей, изменения видны сразу.
- Добавляйте SKU вручную или **импортируйте Excel** (колонки: SKU, Себестоимость)
- В таблице справа отредактируйте **Название** SKU и нажмите «Сохранить названия»
- Себестоимость учитывается во всех расчётах прибыли и рентабельности

---
**🛒 Калькулятор цен · Дальний кластер**
Рассчитывает рекомендуемую цену так, чтобы после всех расходов вышла нужная рентабельность.

*Что учитывает формула:*
| Статья | Как задаётся |
|---|---|
| Себестоимость | колонка «Себестоимость» |
| Вознаграждение МП | % от цены (колонка «Возн. МП, %») |
| Эквайринг | 1.5% от цены (фиксировано) |
| Логистика до СЦ | колонка «Логист. Дальн» |
| Объёмный вес | 1.9 ₽/л × объём |
| СЦ + ПВЗ + Возврат | колонки «СЦ», «ПВЗ», «Возврат» |

*Как использовать:*
1. Установите **Желаемую рентабельность** (%) — цены пересчитаются автоматически
2. Введите **себестоимость** для каждого товара в колонке «Себестоимость»
3. Скорректируйте вознаграждение МП и логистику если нужно
4. Скачайте результат в Excel кнопкой «📥 Скачать Excel»
5. Используйте «📋 Шаблон себестоимости» для загрузки в базу через раздел Себестоимость
""")

st.sidebar.markdown("---")
if st.sidebar.button("🔧 Разработчикам", key="dev_panel_btn"):
    admin_panel()

# ── Страницы ──────────────────────────────────────────────────────────────
if page == "📊 OZON Аналитика":
    page_ozon()
elif page == "🎯 Яндекс Маркет":
    page_ym()
elif page == "💰 Себестоимость":
    page_costs()
elif page == "🛒 Калькулятор цен":
    page_calculator()
