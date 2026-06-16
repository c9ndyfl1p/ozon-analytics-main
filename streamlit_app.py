"""
Аналитика маркетплейсов — OZON + Яндекс Маркет (Streamlit)
"""
import io
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ── Пути к файлам ─────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
COSTS_FILE   = BASE_DIR / "costs_db.json"
RETURNS_FILE = BASE_DIR / "returns_settings.json"
STATE_FILE   = BASE_DIR / "ozon_state.json"
HISTORY_FILE = BASE_DIR / "history.json"
HISTORY_DIR  = BASE_DIR / "history"

# ── Константы ─────────────────────────────────────────────────────────────
TARIFF_PER_L  = 1.9
ACQUIRING_PCT = 1.5

RETURN_TYPE_KEYS   = {"Бой товара": "бой", "Восстановление": "восстановление", "Возврат к продаже": "возврат"}
RETURN_KEYS_LABELS = {"бой": "Бой товара", "восстановление": "Восстановление", "возврат": "Возврат к продаже"}

C_PRIMARY = "#3B82F6"
C_SUCCESS = "#22C55E"
C_DANGER  = "#EF4444"
C_WARNING = "#F59E0B"
C_MUTED   = "#94A3B8"
C_BG      = "#0F172A"
C_CARD    = "#1E293B"

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
    return {
        "costs":           _read_json(COSTS_FILE, {}),
        "return_settings": _read_json(RETURNS_FILE, {}),
        "history":         _read_json(HISTORY_FILE, {"ozon": [], "ym": []}),
    }

# Обёртки для чтения/записи через shared state
def get_costs() -> dict:
    return _shared()["costs"]

def set_costs(costs: dict):
    _shared()["costs"] = costs
    _write_json(COSTS_FILE, costs)

def get_return_settings() -> dict:
    return _shared()["return_settings"]

def set_return_settings(data: dict):
    _shared()["return_settings"] = data
    _write_json(RETURNS_FILE, data)

def get_history() -> dict:
    return _shared()["history"]

def _save_history():
    _write_json(HISTORY_FILE, _shared()["history"])

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

def period_from_filename(filename: str) -> str:
    """Извлекает период из имени файла. Возвращает пустую строку если не найдено."""
    # Год ограничен 19xx/20xx чтобы не ловить случайные числа типа 8206235
    tokens = re.findall(r"\d{2}[._-]\d{2}[._-](?:19|20)\d{2}|(?:19|20)\d{2}[._-]\d{2}[._-]\d{2}", filename)
    parsed = [d for t in tokens if (d := _parse_date_from_str(t)) is not None]
    if len(parsed) >= 2:
        parsed.sort()
        return f"{parsed[0].strftime('%d.%m.%Y')} — {parsed[-1].strftime('%d.%m.%Y')}"
    if len(parsed) == 1:
        return parsed[0].strftime("%d.%m.%Y")
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
            "revenue": round(float(regular["Выручка"].sum())  if "Выручка"    in regular.columns else 0, 0),
            "profit":  round(float(regular["Прибыль"].sum())  if "Прибыль"    in regular.columns else 0, 0),
            "orders":  int(regular["Количество"].sum()        if "Количество" in regular.columns else 0),
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
    costs = get_costs()
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

def make_analytics_charts(df: pd.DataFrame, top_metric: str = "Прибыль") -> go.Figure:
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=["Топ товаров", "Динамика выручки и прибыли",
                        "Доля в прибыли (топ-5)", "Матрица ассортимента"],
        specs=[[{"type": "bar"}, {"type": "xy"}],
               [{"type": "pie"}, {"type": "scatter"}]],
        horizontal_spacing=0.12, vertical_spacing=0.22,
    )

    # 1. Топ товаров
    mcol = {"Прибыль": "Прибыль", "Выручка": "Выручка", "Продано": "Количество"}.get(top_metric, "Прибыль")
    if "Название товара" in df.columns and mcol in df.columns:
        top = df.groupby("Название товара")[mcol].sum().sort_values().tail(10)
        colors = [C_DANGER if v < 0 else C_PRIMARY for v in top.values]
        fig.add_trace(go.Bar(
            y=top.index.tolist(), x=top.values.tolist(), orientation="h",
            marker_color=colors, showlegend=False,
            text=[f"{v:,.0f}" for v in top.values], textposition="outside",
        ), row=1, col=1)

    # 2. Динамика
    if "Дата начисления" in df.columns and "Выручка" in df.columns:
        by_d = (df.groupby("Дата начисления")[["Выручка", "Прибыль"]]
                .sum().reset_index().sort_values("Дата начисления"))
        dates = by_d["Дата начисления"].astype(str).tolist()
        fig.add_trace(go.Bar(x=dates, y=by_d["Выручка"].tolist(),
                             name="Выручка", marker_color=C_SUCCESS, opacity=0.65), row=1, col=2)
        fig.add_trace(go.Scatter(x=dates, y=by_d["Прибыль"].tolist(),
                                 name="Прибыль", line=dict(color=C_WARNING, width=2),
                                 mode="lines+markers"), row=1, col=2)

    # 3. Пирог
    if "Название товара" in df.columns and "Прибыль" in df.columns:
        bp = df.groupby("Название товара")["Прибыль"].sum()
        bp = bp[bp > 0].sort_values(ascending=False)
        if not bp.empty:
            top5 = bp.head(5)
            rest = bp.iloc[5:].sum()
            if rest > 0:
                top5 = pd.concat([top5, pd.Series({"Остальные": rest})])
            palette = [C_PRIMARY, "#A855F7", "#EAB308", C_SUCCESS, "#F97316", C_MUTED]
            fig.add_trace(go.Pie(
                labels=top5.index.tolist(), values=top5.values.tolist(),
                hole=0.55, marker_colors=palette[:len(top5)], showlegend=True,
            ), row=2, col=1)

    # 4. Матрица
    if {"Название товара", "Количество", "Рентабельность", "Выручка"}.issubset(df.columns):
        grp = df.groupby("Название товара").agg(
            qty=("Количество", "sum"), margin=("Рентабельность", "mean"),
            revenue=("Выручка", "sum"),
        ).reset_index()
        grp = grp[grp["qty"] > 0].reset_index(drop=True)
        if not grp.empty:
            rev_max = grp["revenue"].max() or 1.0
            sizes   = (grp["revenue"] / rev_max * 40 + 6).clip(6, 46)

            # Подписываем только выбросы — топ-3 по марже и топ-3 по продажам
            label_idx = (set(grp.nlargest(3, "margin").index) |
                         set(grp.nlargest(3, "qty").index))

            def _short(name: str) -> str:
                return name[:20] + "…" if len(name) > 20 else name

            labels = [_short(str(row["Название товара"])) if i in label_idx else ""
                      for i, row in grp.iterrows()]
            hovers = [
                f"<b>{row['Название товара']}</b><br>"
                f"Продано: {int(row['qty'])} шт.<br>"
                f"Рентабельность: {row['margin']:.1f}%<br>"
                f"Выручка: {row['revenue']:,.0f} ₽"
                for _, row in grp.iterrows()
            ]

            fig.add_trace(go.Scatter(
                x=grp["qty"].tolist(), y=grp["margin"].tolist(),
                mode="markers+text",
                text=labels,
                hovertext=hovers,
                hoverinfo="text",
                textposition="top center",
                textfont=dict(size=9, color="#E2E8F0"),
                marker=dict(
                    size=sizes.tolist(),
                    color=[C_DANGER if m < 0 else C_PRIMARY for m in grp["margin"]],
                    opacity=0.8,
                    line=dict(color="rgba(255,255,255,0.25)", width=1),
                ),
                showlegend=False,
            ), row=2, col=2)
            x_min = grp["qty"].min() * 0.9
            x_max = grp["qty"].max() * 1.1
            fig.add_trace(go.Scatter(
                x=[x_min, x_max], y=[0, 0],
                mode="lines", line=dict(color=C_MUTED, dash="dot", width=1),
                showlegend=False,
            ), row=2, col=2)

    fig.update_layout(
        paper_bgcolor=C_BG, plot_bgcolor=C_CARD,
        font=dict(color="#E2E8F0", size=11), height=680,
        margin=dict(l=10, r=10, t=60, b=10),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    for ann in fig.layout.annotations:
        ann.font.color = C_MUTED
        ann.font.size  = 12
    return fig

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

def render_kpi(df: pd.DataFrame):
    rev    = df["Выручка"].sum()         if "Выручка"        in df.columns else 0
    profit = df["Прибыль"].sum()         if "Прибыль"        in df.columns else 0
    qty    = int(df["Количество"].sum()) if "Количество"     in df.columns else 0
    margin = df["Рентабельность"].mean() if "Рентабельность" in df.columns else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Выручка",        f"{rev:,.0f} ₽")
    c2.metric("Чистая прибыль", f"{profit:,.0f} ₽",
              delta="▲" if profit >= 0 else "▼",
              delta_color="normal" if profit >= 0 else "inverse")
    c3.metric("Рентабельность", f"{margin:.1f}%")
    c4.metric("Заказов",        f"{qty:,} шт.")

def render_sku_table(df: pd.DataFrame, source_col: str = "Поступление от ОЗОН", key_prefix: str = ""):
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

    st.dataframe(
        grp.style.format({
            "Выручка": "{:,.2f}", "Расходы": "{:,.2f}", "Поступление": "{:,.2f}",
            "Себестоимость": "{:,.2f}", "Прибыль": "{:,.2f}", "Рент., %": "{:.1f}%",
        }).map(
            lambda v: "color: #EF4444" if isinstance(v, (int, float)) and v < 0
                      else "color: #22C55E" if isinstance(v, (int, float)) and v > 0 else "",
            subset=["Прибыль", "Рент., %"]
        ),
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

    render_kpi(regular)
    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(["📋 Начисления", "🔄 Возвраты", "📊 Графики", "💡 Рекомендации"])

    with tab1:
        render_sku_table(regular, key_prefix="ozon_")
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
        st.plotly_chart(make_analytics_charts(regular, metric), use_container_width=True)

    with tab4:
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

    render_kpi(df)
    st.divider()

    tab1, tab2, tab3 = st.tabs(["📋 Сводка по SKU", "📊 Графики", "💡 Рекомендации"])

    with tab1:
        render_sku_table(df, source_col="Поступление от ОЗОН", key_prefix="ym_")

    with tab2:
        metric = st.radio("Топ товаров по:", ["Прибыль", "Выручка", "Продано"],
                          horizontal=True, key="ym_metric")
        st.plotly_chart(make_analytics_charts(df, metric), use_container_width=True)

    with tab3:
        st.subheader("💡 Умные рекомендации")
        render_recommendations(df)


def page_costs():
    st.header("💰 База себестоимости")
    st.caption("Общая для всех пользователей — изменения видны сразу у всех")

    costs = get_costs()

    col_form, col_table = st.columns([1, 2])

    with col_form:
        with st.container(border=True):
            st.subheader("Добавить / изменить")
            sku  = st.text_input("Артикул или SKU")
            cost = st.number_input("Себестоимость, руб.", min_value=0.0, step=100.0)
            if st.button("💾 Сохранить", type="primary", use_container_width=True):
                if sku.strip():
                    costs = dict(get_costs())
                    costs[sku.strip()] = cost
                    set_costs(costs)
                    st.success(f"✓ {sku} = {cost:.2f} руб.")
                    st.rerun()

        with st.container(border=True):
            st.subheader("Импорт из Excel / CSV")
            st.caption("Колонки: SKU Ozon, SKU Яндекс, Себестоимость")
            imp = st.file_uploader("Выбрать файл", type=["xlsx", "xls", "csv"])
            if imp:
                try:
                    df_imp = (pd.read_csv(imp, dtype=str) if imp.name.endswith(".csv")
                              else pd.read_excel(imp, dtype=str))
                    df_imp.columns = [str(c).strip().lower() for c in df_imp.columns]
                    ozon_col = next((c for c in df_imp.columns if "ozon" in c), None)
                    ym_col   = next((c for c in df_imp.columns if "яндекс" in c), None)
                    cost_col = next((c for c in df_imp.columns if any(x in c for x in
                                    ["себестоимость", "цена", "cost", "price"])), None)
                    if not ozon_col and not ym_col:
                        ozon_col = next((c for c in df_imp.columns if any(x in c for x in
                                        ["sku", "артикул", "id"])), df_imp.columns[0])
                    if not cost_col:
                        cost_col = df_imp.columns[1] if len(df_imp.columns) > 1 else df_imp.columns[0]
                    sku_cols = [c for c in [ozon_col, ym_col] if c]
                    new_costs = dict(get_costs())
                    count = 0
                    for _, row in df_imp.iterrows():
                        cs = (str(row.get(cost_col, "")).replace("₽", "")
                              .replace("\xa0", "").replace(" ", "").replace(",", "."))
                        try:
                            cv = float(cs)
                        except ValueError:
                            continue
                        for col in sku_cols:
                            sv = str(row.get(col, "")).strip()
                            if sv and sv.lower() != "nan":
                                new_costs[sv] = cv
                                count += 1
                    set_costs(new_costs)
                    st.success(f"✓ Импортировано: {count} артикулов")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")

        with st.container(border=True):
            st.subheader("Удалить")
            del_sku = st.text_input("SKU для удаления")
            if st.button("🗑️ Удалить", type="secondary", use_container_width=True):
                cur = dict(get_costs())
                if del_sku in cur:
                    del cur[del_sku]
                    set_costs(cur)
                    st.success(f"✓ Удалено: {del_sku}")
                    st.rerun()
                else:
                    st.warning("SKU не найден")

    with col_table:
        costs = get_costs()
        st.subheader(f"Текущая база ({len(costs)} записей)")
        if costs:
            df_costs = pd.DataFrame(list(costs.items()), columns=["Артикул / SKU", "Себестоимость, руб."])
            df_costs = df_costs.sort_values("Артикул / SKU").reset_index(drop=True)
            search_c = st.text_input("🔍 Поиск по SKU")
            if search_c:
                df_costs = df_costs[df_costs["Артикул / SKU"].str.contains(search_c, case=False, na=False)]
            st.dataframe(df_costs, use_container_width=True, hide_index=True, height=500)
        else:
            st.info("База пуста. Добавьте записи через форму или импортируйте из файла.")


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
# ГЛАВНАЯ
# ══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Аналитика маркетплейсов",
    page_icon="📊",
    layout="wide",
)

st.sidebar.title("📊 Аналитика")
page = st.sidebar.radio(
    "Раздел",
    ["📊 OZON Аналитика", "🎯 Яндекс Маркет", "💰 Себестоимость", "🛒 Калькулятор цен"],
    label_visibility="collapsed",
)

if page == "📊 OZON Аналитика":
    page_ozon()
elif page == "🎯 Яндекс Маркет":
    page_ym()
elif page == "💰 Себестоимость":
    page_costs()
elif page == "🛒 Калькулятор цен":
    page_calculator()
