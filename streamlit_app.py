"""
ОЗОН Калькулятор цен — веб-версия на Streamlit
"""
import io
import json
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Константы ─────────────────────────────────────────────────────────────
TARIFF_PER_L  = 1.9
ACQUIRING_PCT = 1.5
STATE_FILE    = Path(__file__).parent / "ozon_state.json"

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

EDITABLE_COLS = ["name", "volume", "reward", "logistics", "sc", "pvz", "ret", "cost"]
COMPUTED_COLS = ["reward_rub", "acquiring_rub", "commission", "price", "net_profit"]
ALL_COLS      = EDITABLE_COLS + COMPUTED_COLS

COL_LABELS = {
    "name":          "Наименование",
    "volume":        "Объём, л",
    "reward":        "Возн. МП, %",
    "logistics":     "Логист. Дальн",
    "sc":            "СЦ, руб",
    "pvz":           "ПВЗ, руб",
    "ret":           "Возврат, руб",
    "cost":          "Себестоимость",
    "reward_rub":    "Возн. МП, руб",
    "acquiring_rub": "Эквайринг, руб",
    "commission":    "Комиссия ОЗОН",
    "price":         "РЕК. ЦЕНА",
    "net_profit":    "Чистая прибыль",
}

# ── Расчёт ────────────────────────────────────────────────────────────────
def _f(val, default=0.0) -> float:
    try:
        return float(val) if val is not None and str(val).strip() != "" else default
    except (ValueError, TypeError):
        return default

def calc_row(row, roi: float) -> dict:
    cost = _f(row.get("cost"))
    if cost <= 0:
        return {c: 0.0 for c in COMPUTED_COLS}

    volume     = _f(row.get("volume"))
    reward_pct = _f(row.get("reward"))
    logistics  = _f(row.get("logistics"))
    sc         = _f(row.get("sc"), 20)
    pvz        = _f(row.get("pvz"), 25)
    ret        = _f(row.get("ret"), 15)

    shipment         = volume * TARIFF_PER_L
    fixed_commission = sc + pvz + ret + shipment + logistics
    pct_rate         = (reward_pct + ACQUIRING_PCT) / 100

    price      = (cost * (roi / 100 + 1) + fixed_commission) / (1 - pct_rate)
    acquiring  = price * ACQUIRING_PCT / 100
    reward_rub = price * reward_pct / 100
    commission = acquiring + sc + pvz + ret + shipment + logistics + reward_rub
    net_profit = price - cost - commission

    return {
        "reward_rub":    round(reward_rub, 2),
        "acquiring_rub": round(acquiring, 2),
        "commission":    round(commission, 2),
        "price":         round(price, 2),
        "net_profit":    round(net_profit, 2),
    }

def recalculate(df: pd.DataFrame, roi: float) -> pd.DataFrame:
    df = df.copy()
    for idx, row in df.iterrows():
        for k, v in calc_row(row.to_dict(), roi).items():
            df.at[idx, k] = v
    return df

# ── Сохранение / загрузка ─────────────────────────────────────────────────
def make_default_df() -> pd.DataFrame:
    rows = [
        {"name": n, "volume": v, "reward": r, "logistics": l,
         "sc": 20, "pvz": 25, "ret": 15, "cost": 0.0,
         **{c: 0.0 for c in COMPUTED_COLS}}
        for n, v, r, l in DEFAULT_PRODUCTS
    ]
    return pd.DataFrame(rows, columns=ALL_COLS)

def load_state() -> tuple[float, pd.DataFrame]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        roi  = float(state.get("roi", 30.0))
        rows = state.get("rows", [])
        if rows:
            df = pd.DataFrame(rows)
            for c in ALL_COLS:
                if c not in df.columns:
                    df[c] = 0.0
            return roi, df[ALL_COLS]
    except Exception:
        pass
    return 30.0, make_default_df()

def save_state(df: pd.DataFrame, roi: float):
    state = {
        "roi":  str(roi),
        "rows": df[EDITABLE_COLS].to_dict(orient="records"),
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ── Excel-утилиты ─────────────────────────────────────────────────────────
def df_to_excel(df: pd.DataFrame, sheet: str) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=sheet)
    return buf.getvalue()

def import_costs_from_excel(file, df: pd.DataFrame, roi: float) -> tuple[pd.DataFrame, int]:
    cost_df = pd.read_excel(file, skiprows=1)
    cost_df.columns = [str(c).strip() for c in cost_df.columns]
    name_col = next((c for c in cost_df.columns if "наим" in c.lower()), None)
    cost_col = next((c for c in cost_df.columns if "себес" in c.lower()), None)
    if not name_col or not cost_col:
        raise ValueError("Не найдены колонки 'Наименование' и 'Себестоимость'")
    cost_map = {
        str(r[name_col]).strip().lower(): float(r[cost_col])
        for _, r in cost_df.iterrows()
        if pd.notna(r.get(cost_col))
    }
    df = df.copy()
    matched = 0
    for idx, row in df.iterrows():
        key = str(row["name"]).strip().lower()
        if key in cost_map:
            df.at[idx, "cost"] = cost_map[key]
            matched += 1
    return recalculate(df, roi), matched

# ── Страница ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ОЗОН Калькулятор цен",
    page_icon="🛒",
    layout="wide",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #0F172A; }
[data-testid="stHeader"]           { background: #0F172A; }
section[data-testid="stSidebar"]   { background: #1E293B; }
</style>
""", unsafe_allow_html=True)

# ── Инициализация сессии ──────────────────────────────────────────────────
if "initialized" not in st.session_state:
    roi, df = load_state()
    st.session_state.roi         = roi
    st.session_state.df          = recalculate(df, roi)
    st.session_state.initialized = True

# ── Заголовок ─────────────────────────────────────────────────────────────
st.title("🛒 ОЗОН — Калькулятор цен · Дальний кластер")

# ── Панель управления ─────────────────────────────────────────────────────
col_roi, col_upload, col_spacer = st.columns([2, 3, 5])

with col_roi:
    roi_new = st.number_input(
        "Желаемая рентабельность, %",
        min_value=0.0, max_value=9999.0,
        value=float(st.session_state.roi),
        step=1.0, format="%.1f",
    )
    if roi_new != st.session_state.roi:
        st.session_state.roi = roi_new
        st.session_state.df  = recalculate(st.session_state.df, roi_new)
        save_state(st.session_state.df, roi_new)
        st.rerun()

with col_upload:
    uploaded = st.file_uploader(
        "📂 Загрузить себестоимость из Excel",
        type=["xlsx"],
        help="Колонки: Наименование, Себестоимость, руб",
    )
    if uploaded:
        try:
            new_df, matched = import_costs_from_excel(
                uploaded, st.session_state.df, st.session_state.roi
            )
            st.session_state.df = new_df
            save_state(new_df, st.session_state.roi)
            st.success(f"✓ Обновлено {matched} товаров")
            st.rerun()
        except Exception as e:
            st.error(f"Ошибка: {e}")

# ── Таблица ───────────────────────────────────────────────────────────────
column_config = {
    "name":          st.column_config.TextColumn("Наименование", width="large"),
    "volume":        st.column_config.NumberColumn("Объём, л",        format="%.0f",  min_value=0),
    "reward":        st.column_config.NumberColumn("Возн. МП, %",     format="%.0f",  min_value=0),
    "logistics":     st.column_config.NumberColumn("Логист. Дальн",   format="%.2f",  min_value=0),
    "sc":            st.column_config.NumberColumn("СЦ, руб",         format="%.0f",  min_value=0),
    "pvz":           st.column_config.NumberColumn("ПВЗ, руб",        format="%.0f",  min_value=0),
    "ret":           st.column_config.NumberColumn("Возврат, руб",    format="%.0f",  min_value=0),
    "cost":          st.column_config.NumberColumn("Себестоимость",   format="%.2f",  min_value=0),
    "reward_rub":    st.column_config.NumberColumn("Возн. МП, руб",   format="%.2f",  disabled=True),
    "acquiring_rub": st.column_config.NumberColumn("Эквайринг, руб",  format="%.2f",  disabled=True),
    "commission":    st.column_config.NumberColumn("Комиссия ОЗОН",   format="%.2f",  disabled=True),
    "price":         st.column_config.NumberColumn("РЕК. ЦЕНА",       format="%.2f",  disabled=True),
    "net_profit":    st.column_config.NumberColumn("Чистая прибыль",  format="%.2f",  disabled=True),
}

edited = st.data_editor(
    st.session_state.df,
    column_config=column_config,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key="main_table",
)

# Обнаруживаем изменения и пересчитываем
try:
    changed = not edited[EDITABLE_COLS].reset_index(drop=True).equals(
        st.session_state.df[EDITABLE_COLS].reset_index(drop=True)
    )
except Exception:
    changed = True

if changed:
    for c in ["volume", "reward", "logistics", "cost"]:
        edited[c] = pd.to_numeric(edited[c], errors="coerce").fillna(0)
    edited["sc"]  = pd.to_numeric(edited["sc"],  errors="coerce").fillna(20)
    edited["pvz"] = pd.to_numeric(edited["pvz"], errors="coerce").fillna(25)
    edited["ret"] = pd.to_numeric(edited["ret"], errors="coerce").fillna(15)
    for c in COMPUTED_COLS:
        if c not in edited.columns:
            edited[c] = 0.0
    st.session_state.df = recalculate(edited[ALL_COLS], st.session_state.roi)
    save_state(st.session_state.df, st.session_state.roi)
    st.rerun()

# ── Экспорт ───────────────────────────────────────────────────────────────
st.divider()
dl1, dl2, _ = st.columns([2, 2, 6])

with dl1:
    export_df = st.session_state.df.rename(columns=COL_LABELS)
    st.download_button(
        "📊 Скачать таблицу цен (Excel)",
        data=df_to_excel(export_df, "Цены ОЗОН"),
        file_name="ozon_prices.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

with dl2:
    tmpl_df = st.session_state.df[["name", "cost"]].rename(
        columns={"name": "Наименование", "cost": "Себестоимость, руб"}
    )
    st.download_button(
        "📋 Шаблон себестоимости (Excel)",
        data=df_to_excel(tmpl_df, "Себестоимость"),
        file_name="себестоимость_шаблон.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
