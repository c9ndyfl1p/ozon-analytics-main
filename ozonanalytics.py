import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import json
import os
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
try:
    from PIL import Image, ImageTk
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# Import Ozon calculator - Mass price calculator
try:
    from ozon_mass_price_calc import OzonMassCalcWidget as MassCalc
    _CALCULATOR_AVAILABLE = True
except ImportError:
    _CALCULATOR_AVAILABLE = False

# ══════════════════════════════════════════════════════════════════════════════
# НАСТРОЙКА ДИНАМИЧЕСКИХ ПУТЕЙ
# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
COSTS_FILE   = BASE_DIR / "costs_db.json"
RETURNS_FILE = BASE_DIR / "returns_settings.json"

RETURN_TYPE_OPTIONS = ["Бой товара", "Восстановление", "Возврат к продаже"]
RETURN_TYPE_KEYS    = {"Бой товара": "бой", "Восстановление": "восстановление", "Возврат к продаже": "возврат"}
RETURN_KEYS_LABELS  = {"бой": "Бой товара", "восстановление": "Восстановление", "возврат": "Возврат к продаже"}


def load_costs() -> dict:
    if COSTS_FILE.exists():
        try:
            with open(COSTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_costs(costs: dict):
    try:
        with open(COSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(costs, f, ensure_ascii=False, indent=4)
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось сохранить себестоимость: {e}")

def load_return_settings() -> dict:
    if RETURNS_FILE.exists():
        try:
            with open(RETURNS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_return_settings(data: dict):
    try:
        with open(RETURNS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось сохранить настройки возвратов: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ПАРСЕРЫ
# ══════════════════════════════════════════════════════════════════════════════

def parse_accrual_excel(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None, dtype=str)
    header_row = None
    for i, row in raw.iterrows():
        if row.astype(str).str.contains("ID начисления", na=False).any():
            header_row = i
            break
    if header_row is None:
        raise ValueError("Не найдена строка с заголовками ('ID начисления')")
    df = pd.read_excel(path, header=header_row, dtype=str)
    df = df.dropna(how="all")
    df.columns = df.columns.str.strip()
    return df


def parse_goods_excel(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None, dtype=str, nrows=10)
    header_row = 0
    for i, row in raw.iterrows():
        non_empty = row.dropna().astype(str).str.strip()
        non_empty = non_empty[non_empty != ""]
        if len(non_empty) >= 3:
            header_row = i
            break
    df = pd.read_excel(path, header=header_row, dtype=str)
    df = df.dropna(how="all")
    df.columns = df.columns.str.strip()
    return df


def parse_ym_orders_excel(path: str) -> pd.DataFrame:
    """
    Reads Yandex Market netting (взаимозачёт) XLSX.
    Reads the SECOND sheet (index 1) — first sheet is ignored.
    Row 0 of the sheet is a section header; row 1 contains column names.
    """
    xf = pd.ExcelFile(path)
    if len(xf.sheet_names) < 2:
        raise ValueError("В файле менее 2 листов — ожидается минимум 2")

    sheet = xf.sheet_names[1]

    # Find header row by scanning for 'Ваш SKU' or 'Сумма транзакц'
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str, nrows=10)
    hdr_row = 1  # default: second row
    for i, row in raw.iterrows():
        vals_l = [str(v).lower() for v in row.values]
        if any("ваш sku" in v or "сумма транзакц" in v for v in vals_l):
            hdr_row = i
            break

    df = pd.read_excel(path, sheet_name=sheet, header=hdr_row, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df



# ══════════════════════════════════════════════════════════════════════════════
# ЛОГИКА РАСЧЁТОВ
# ══════════════════════════════════════════════════════════════════════════════

def parse_amount(s) -> float:
    if pd.isna(s):
        return 0.0
    s = str(s).replace("₽", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def build_accrual_summary(df: pd.DataFrame):
    """Возвращает (regular_df, returns_df) — начисления без возвратов и возвраты отдельно."""
    amount_col         = "Сумма итого, руб."
    id_col             = "ID начисления"
    sku_col            = "SKU"
    name_col           = "Название товара"
    qty_col            = "Количество"
    operation_type_col = "Тип начисления"

    df = df.copy()
    df[id_col]             = df[id_col].fillna("").astype(str).str.strip()
    df["_amount"]          = df[amount_col].apply(parse_amount)
    df["_qty"]             = df[qty_col].apply(lambda x: int(parse_amount(x)))
    df[operation_type_col] = df[operation_type_col].fillna("").astype(str).str.strip()

    pivot = df[df[id_col] != ""].pivot_table(
        index=id_col, columns=operation_type_col, values="_amount", aggfunc="sum", fill_value=0.0
    ).reset_index()

    all_op_cols = [c for c in pivot.columns if c != id_col]

    # выручка без возврата
    revenue_cols       = [c for c in all_op_cols if "выручка" in c.lower() and "возврат" not in c.lower()]
    # возврат выручки
    return_rev_cols    = [c for c in all_op_cols if "возврат" in c.lower() and "выручка" in c.lower()]
    # обратная логистика
    reverse_log_cols   = [c for c in all_op_cols if "обратная" in c.lower()]
    # прочие возвраты (без выручки/обратной логистики)
    other_return_cols  = [c for c in all_op_cols
                          if "возврат" in c.lower() and c not in return_rev_cols and c not in reverse_log_cols]
    all_return_cols    = list(set(return_rev_cols + reverse_log_cols + other_return_cols))
    # расходы = всё кроме выручки и возвратов
    expense_cols       = [c for c in all_op_cols if c not in revenue_cols and c not in all_return_cols]

    # если в начислении только эквайринг или дополнительная обработка — не считать в количество
    acquiring_cols      = [c for c in all_op_cols if "эквайринг" in c.lower()]
    add_processing_cols = [c for c in all_op_cols if "дополнительная" in c.lower()]
    skip_qty_cols       = list(set(acquiring_cols + add_processing_cols))
    non_skip_qty_cols   = [c for c in all_op_cols if c not in skip_qty_cols]
    if non_skip_qty_cols:
        pivot["_is_acquiring_only"] = pivot[non_skip_qty_cols].abs().sum(axis=1) == 0
    else:
        pivot["_is_acquiring_only"] = False

    pivot["Выручка"]           = pivot[revenue_cols].sum(axis=1) if revenue_cols else 0.0
    pivot["Расходы"]           = pivot[expense_cols].sum(axis=1).abs() if expense_cols else 0.0
    pivot["Поступление от ОЗОН"] = pivot[all_op_cols].sum(axis=1) / 1.22

    has_rev_return  = pivot[return_rev_cols].abs().sum(axis=1) > 0   if return_rev_cols  else pd.Series(False, index=pivot.index)
    has_rev_log     = pivot[reverse_log_cols].abs().sum(axis=1) > 0  if reverse_log_cols else pd.Series(False, index=pivot.index)
    pivot["_is_return"] = has_rev_return | has_rev_log

    pivot["_reverse_logistics_cost"] = pivot[reverse_log_cols].sum(axis=1).abs() if reverse_log_cols else 0.0

    meta = df[df[id_col] != ""].groupby(id_col, sort=False).agg({
        "Дата начисления": "first",
        "Артикул": "first",
        sku_col: "first",
        name_col: "first",
        "_qty": "max"
    }).reset_index()

    result = meta.merge(
        pivot[[id_col, "Выручка", "Расходы", "Поступление от ОЗОН", "_is_return", "_reverse_logistics_cost", "_is_acquiring_only"]],
        on=id_col, how="left"
    )

    costs_db = load_costs()

    def get_unit_cost(row):
        for key in [str(row.get("Артикул", "")).strip(), str(row.get("SKU", "")).strip()]:
            if key and key != "nan":
                cost = costs_db.get(key, 0.0)
                if cost > 0:
                    return cost
        return 0.0

    result["_unit_cost"] = result.apply(get_unit_cost, axis=1)
    result["Количество"] = result.apply(
        lambda r: int(r["_qty"]) if not bool(r.get("_is_acquiring_only", False)) else 0,
        axis=1
    )

    return_settings = load_return_settings()

    def calc_cost(row):
        if row.get("_is_return", False):
            accrual_id = str(row["ID начисления"])
            setting    = return_settings.get(accrual_id, {})
            rtype      = setting.get("type", "возврат")
            qty        = max(int(row["_qty"]), 1)
            unit_cost  = row["_unit_cost"]
            if rtype == "бой":
                return unit_cost * qty
            elif rtype == "восстановление":
                restoration = float(setting.get("restoration_cost", 0.0))
                return max(0.0, unit_cost * qty +  restoration)
            else:
                return 0.0
        else:
            if pd.isna(row.get("Выручка", 0)) or row.get("Выручка", 0) <= 0:
                return 0.0
            return row["_unit_cost"] * row["_qty"]

    result["Себестоимость"] = result.apply(calc_cost, axis=1)
    result["Прибыль"]       = result["Поступление от ОЗОН"] - result["Себестоимость"]
    result["Рентабельность"] = result.apply(
        lambda r: (r["Поступление от ОЗОН"] / r["Себестоимость"] * 100 - 100) if r["Себестоимость"] > 0 else 0.0,
        axis=1
    )

    regular_df = result[~result["_is_return"]].copy()
    returns_df = result[ result["_is_return"]].copy()
    return regular_df, returns_df


# ══════════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ И СТИЛИ ИНТЕРФЕЙСА
# ══════════════════════════════════════════════════════════════════════════════

LEFT_COLS = {
    "Группировка / SKU", "ID начисления", "Дата начисления", "Артикул", "SKU",
    "Название товара", "Схема работы", "Группа услуг",
}
NON_MONEY = {
    "Группировка / SKU", "ID начисления", "Дата начисления", "Артикул", "SKU",
    "Название товара", "Схема работы", "Количество", "Группа услуг", "Рентабельность",
}

COLORS = {
    "bg":           "#0F172A",
    "sidebar":      "#020817",
    "card":         "#1E293B",
    "primary":      "#3B82F6",
    "primary_dark": "#2563EB",
    "success":      "#22C55E",
    "danger":       "#EF4444",
    "warning":      "#F59E0B",
    "text":         "#F1F5F9",
    "text_muted":   "#94A3B8",
    "border":       "#334155",
    "row_alt":      "#263146",
    "total_bg":     "#1E3A5F",
    "returns_bg":   "#431407",
    "neg":          "#F87171",
    "sku_bg":       "#1A2740",
}

def compute_promo_insights(df: pd.DataFrame):
    """
    Returns (threshold, result_df).
    threshold = max_sales_per_sku / 2.
    result_df — SKUs where qty < threshold AND margin > 50%, sorted by margin desc.
    """
    if df is None or df.empty:
        return 0.0, pd.DataFrame()
    required = {"SKU", "Название товара", "Количество", "Поступление от ОЗОН", "Себестоимость", "Прибыль"}
    if not required.issubset(df.columns):
        return 0.0, pd.DataFrame()

    grp = df.groupby("SKU", sort=False).agg(
        name=("Название товара", "first"),
        qty=("Количество", "sum"),
        net=("Поступление от ОЗОН", "sum"),
        cost=("Себестоимость", "sum"),
        profit=("Прибыль", "sum"),
    ).reset_index()
    grp["margin"] = grp.apply(
        lambda r: (r["net"] / r["cost"] * 100 - 100) if r["cost"] > 0 else 0.0, axis=1
    )

    max_sales = float(grp["qty"].max())
    if max_sales <= 0:
        return 0.0, pd.DataFrame()
    threshold = max_sales / 2

    result = grp[(grp["qty"] < threshold) & (grp["margin"] > 50)].copy()
    result = result.sort_values("margin", ascending=False)
    return threshold, result[["SKU", "name", "qty", "margin", "profit"]]


def build_ym_summary(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Normalizes YM netting transactions to the analytics column schema.
    Groups multiple transaction rows per order into one summary row per (order, SKU).
    Revenue = customer payment accruals.
    Fees    = revenue minus net (all YM deductions).
    Net     = sum of all transaction amounts for the order+SKU.
    """
    costs = load_costs()

    def _find(*kw_list):
        for col in df_raw.columns:
            col_l = col.lower()
            if all(k.lower() in col_l for k in kw_list):
                return col
        return None

    sku_col    = _find("ваш", "sku") or _find("sku")
    name_col   = _find("название", "товар")
    amount_col = _find("сумма", "транзакц")
    src_col    = _find("источник", "транзакц")
    date_col   = _find("дата", "транзакц")
    # "Номер заказа или отгрузки" — avoid matching "Наш номер заказа"
    order_col  = next(
        (c for c in df_raw.columns
         if "номер заказа" in c.lower() and "наш" not in c.lower()),
        None
    )

    if not sku_col or not amount_col:
        raise ValueError("Не найдены обязательные колонки (Ваш SKU, Сумма транзакции)")

    df = df_raw.copy()
    df = df[
        df[sku_col].notna() &
        (df[sku_col].astype(str).str.strip() != "") &
        (df[sku_col].astype(str).str.lower() != "nan")
    ].copy()

    if df.empty:
        return pd.DataFrame()

    df["_sku"]    = df[sku_col].astype(str).str.strip()
    df["_order"]  = df[order_col].astype(str).str.strip() if order_col else ""
    df["_amount"] = df[amount_col].apply(parse_amount)
    df["_name"]   = df[name_col].astype(str).str.strip() if name_col else ""
    df["_date"]   = df[date_col].astype(str).str.strip()  if date_col else ""
    df["_src"]    = df[src_col].astype(str).str.strip()   if src_col  else ""

    out = []
    for (order_num, sku), group in df.groupby(["_order", "_sku"], sort=False):
        if not sku or sku.lower() == "nan":
            continue

        # Revenue = all positive amounts (customer payment + any YM subsidies/bonuses)
        revenue = group.loc[group["_amount"] > 0, "_amount"].sum()

        net  = group["_amount"].sum()
        fees = max(0.0, revenue - net)

        # Name: from first positive-amount row with non-empty name
        name = ""
        for _, r in group[group["_amount"] > 0].iterrows():
            n = str(r["_name"]).strip()
            if n and n.lower() not in ("nan", ""):
                name = n
                break

        # Date: first non-empty transaction date in the group
        date = ""
        for _, r in group.iterrows():
            d = str(r["_date"]).strip()
            if d and d.lower() not in ("nan", ""):
                date = d
                break

        cost_unit = costs.get(sku, 0.0)
        order_str = order_num if order_num not in ("nan", "") else ""

        out.append({
            "SKU":                 sku,
            "Название товара":     name,
            "Количество":          1,
            "Выручка":             revenue,
            "Расходы":             fees,
            "Поступление от ОЗОН": net,
            "Себестоимость":       cost_unit,
            "Прибыль":             net - cost_unit,
            "Дата начисления":     date,
            "Номер заказа":        order_str,
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


def _darken(hex_color: str, factor: float = 0.82) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(*(max(0, int(c * factor)) for c in (r, g, b)))

def setup_styles():
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    bg     = COLORS["bg"]
    card   = COLORS["card"]
    border = COLORS["border"]
    text   = COLORS["text"]
    muted  = COLORS["text_muted"]
    pri    = COLORS["primary"]

    style.configure("TFrame",      background=bg)
    style.configure("TLabel",      background=bg, foreground=text)
    style.configure("TLabelframe", background=card, bordercolor=border)
    style.configure("TLabelframe.Label",
                    background=card, foreground=muted, font=("", 9, "bold"))

    style.configure("TNotebook", background=bg, tabmargins=[2, 2, 0, 0], borderwidth=0)
    style.configure("TNotebook.Tab",
                    padding=[14, 7], font=("", 10),
                    background=bg, foreground=muted, borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", card), ("active", COLORS["row_alt"])],
              foreground=[("selected", text), ("active", text)])

    style.configure("Treeview",
                    background=card, fieldbackground=card, foreground=text,
                    rowheight=28, relief="flat", borderwidth=0)
    style.configure("Treeview.Heading",
                    background=COLORS["sidebar"], foreground=muted,
                    font=("", 9, "bold"), relief="flat", borderwidth=0)
    style.map("Treeview.Heading",
              background=[("active", pri)],
              foreground=[("active", "#ffffff")])
    style.map("Treeview",
              background=[("selected", pri)],
              foreground=[("selected", "#ffffff")])

    style.configure("Sash",        sashthickness=5, sashpad=0, background=border)
    style.configure("TSeparator",  background=border)
    style.configure("TPanedwindow", background=bg)

    style.configure("TScrollbar",
                    background="#475569", troughcolor=bg,
                    bordercolor=bg, arrowcolor=muted,
                    darkcolor="#475569", lightcolor="#475569")
    style.map("TScrollbar",
              background=[("active", "#64748B"), ("pressed", "#64748B")],
              arrowcolor=[("active", text)])

    style.configure("TCombobox",
                    background=card, foreground=text,
                    fieldbackground=card, selectbackground=pri,
                    selectforeground="white", arrowcolor=muted,
                    bordercolor=border, lightcolor=card, darkcolor=card,
                    insertcolor=text)
    style.map("TCombobox",
              background=[("readonly", card), ("active", card), ("pressed", card)],
              foreground=[("readonly", text), ("active", text)],
              fieldbackground=[("readonly", card), ("focus", card)],
              bordercolor=[("focus", pri)],
              selectbackground=[("focus", pri)],
              arrowcolor=[("active", text), ("pressed", text)])

    style.configure("TEntry",
                    background=card, foreground=text,
                    fieldbackground=card, insertcolor=text,
                    bordercolor=border, lightcolor=card, darkcolor=card,
                    selectbackground=pri, selectforeground="white")
    style.map("TEntry",
              bordercolor=[("focus", pri)],
              lightcolor=[("focus", pri)],
              darkcolor=[("focus", pri)])

def _autofit_tree_columns(tree: ttk.Treeview, left_cols: set = None, max_w: int = 380, min_w: int = 55):
    import tkinter.font as tkfont
    font = tkfont.nametofont("TkDefaultFont")
    pad  = 22
    left_cols = left_cols or set()
    widths = {col: font.measure(str(col)) + pad for col in tree["columns"]}
    for iid in tree.get_children():
        for col, val in zip(tree["columns"], tree.item(iid, "values")):
            w = font.measure(str(val)) + pad
            if w > widths[col]:
                widths[col] = w
    for col, w in widths.items():
        tree.column(col, width=max(min_w, min(w, max_w)), anchor="w" if col in left_cols else "e")


class FlatButton(tk.Frame):
    """Label-based button — respects bg/fg on macOS where tk.Button ignores them."""

    def __init__(self, master, text="", command=None, **kw):
        bg     = kw.pop("bg",     COLORS["card"])
        fg     = kw.pop("fg",     COLORS["text"])
        font   = kw.pop("font",   ("", 10))
        padx   = kw.pop("padx",   10)
        pady   = kw.pop("pady",   4)
        width  = kw.pop("width",  None)
        cursor = kw.pop("cursor", "hand2")
        for k in ("relief", "bd", "highlightthickness", "activebackground", "activeforeground"):
            kw.pop(k, None)

        super().__init__(master, bg=bg, cursor=cursor, bd=0, relief="flat", highlightthickness=0)
        self._bg      = bg
        self._hover   = _darken(bg)
        self._command = command

        lbl_kw = dict(text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady,
                      cursor=cursor, bd=0, relief="flat")
        if width is not None:
            lbl_kw["width"] = width
        self._lbl = tk.Label(self, **lbl_kw)
        self._lbl.pack(fill="both", expand=True)

        for w in (self, self._lbl):
            w.bind("<Enter>",    self._on_enter)
            w.bind("<Leave>",    self._on_leave)
            w.bind("<Button-1>", self._on_click)

    def _on_enter(self, _=None):
        super().configure(bg=self._hover)
        self._lbl.configure(bg=self._hover)

    def _on_leave(self, _=None):
        super().configure(bg=self._bg)
        self._lbl.configure(bg=self._bg)

    def _on_click(self, _=None):
        if self._command:
            self._command()

    def configure(self, **kw):
        if "bg" in kw:
            self._bg    = kw.pop("bg")
            self._hover = _darken(self._bg)
            super().configure(bg=self._bg)
            self._lbl.configure(bg=self._bg)
        if "fg" in kw:
            self._lbl.configure(fg=kw.pop("fg"))
        if "text" in kw:
            self._lbl.configure(text=kw.pop("text"))
        for k in ("relief", "bd", "activebackground", "activeforeground", "highlightthickness"):
            kw.pop(k, None)
        if kw:
            super().configure(**kw)

    config = configure


def create_button(master, text, command, **kwargs) -> "FlatButton":
    return FlatButton(master, text=text, command=command, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# РАЗДЕЛ ВОЗВРАТОВ (вкладка внутри начислений)
# ══════════════════════════════════════════════════════════════════════════════

class ReturnsSection(ttk.Frame):
    """Отображает возвраты и позволяет настраивать тип каждого возврата."""

    def __init__(self, parent, on_change: callable):
        super().__init__(parent)
        self._df: pd.DataFrame | None = None
        self._on_change = on_change
        self._selected_id: str | None = None
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")

        # ── Таблица возвратов ──────────────────────────────────────────────
        left = ttk.Frame(paned)
        paned.add(left, weight=4)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self._cols = [
            "ID начисления", "SKU", "Название товара",
            "Расходы", "Себестоимость", "Тип возврата", "Стоимость доработки", "Прибыль / Убыток"
        ]
        self._tree = ttk.Treeview(left, columns=self._cols, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(left, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(left, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # ── Форма настройки ───────────────────────────────────────────────
        right = ttk.LabelFrame(paned, text="Настройка возврата", padding=12)
        paned.add(right, weight=1)

        ttk.Label(right, text="Тип возврата:").pack(anchor="w", pady=(0, 4))
        self._type_var = tk.StringVar(value="Возврат к продаже")
        self._type_cb = ttk.Combobox(right, textvariable=self._type_var,
                                      values=RETURN_TYPE_OPTIONS, state="readonly", width=22)
        self._type_cb.pack(anchor="w", fill="x", pady=(0, 8))
        self._type_var.trace_add("write", self._on_type_change)

        # Поле стоимости доработки — всегда под типом, активно только для «Восстановление»
        self._restoration_frame = ttk.LabelFrame(right, text="Стоимость доработки (руб.)", padding=6)
        self._restoration_frame.pack(anchor="w", fill="x", pady=(0, 10))
        self._restoration_var = tk.StringVar(value="0")
        self._restoration_entry = ttk.Entry(self._restoration_frame,
                                             textvariable=self._restoration_var, width=18)
        self._restoration_entry.pack(anchor="w", fill="x")

        create_button(right, text="Сохранить", command=self._save_setting,
                      bg="#3498db", fg="white", pady=5, width=20).pack(anchor="w", fill="x", pady=(0, 8))

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=(0, 8))

        # Подсказки по типам
        hint_frame = ttk.LabelFrame(right, text="Описание типов", padding=6)
        hint_frame.pack(anchor="w", fill="x", pady=(0, 8))
        hints = (
            "Бой товара — себестоимость\nсписывается полностью.\n\n"
            "Восстановление — из себестоимости\nвычитается стоимость доработки.\n\n"
            "Возврат к продаже — себестоимость\nне учитывается (товар вернулся)."
        )
        ttk.Label(hint_frame, text=hints, font=("", 8), foreground=COLORS["text_muted"],
                  justify="left", wraplength=180).pack(anchor="w")

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=8)
        self._info_var = tk.StringVar(value="Выберите строку для настройки")
        ttk.Label(right, textvariable=self._info_var, font=("", 8),
                  foreground=COLORS["text_muted"], wraplength=180, justify="left").pack(anchor="w")

        self._update_restoration_visibility()

    def load(self, df: pd.DataFrame):
        self._df = df
        self._render()

    def _render(self):
        if self._df is None:
            return
        tree = self._tree
        tree.delete(*tree.get_children())
        tree["columns"] = self._cols

        left_set = {"ID начисления", "SKU", "Название товара", "Тип возврата"}
        for c in self._cols:
            tree.heading(c, text=c)
            tree.column(c, anchor="w" if c in left_set else "e", width=100)
        tree.column("Название товара",      width=200)
        tree.column("ID начисления",        width=130)
        tree.column("Стоимость доработки",  width=130)

        return_settings = load_return_settings()
        total_exp = 0.0
        total_cost = 0.0
        total_profit = 0.0

        for _, row in self._df.iterrows():
            accrual_id = str(row["ID начисления"])
            setting    = return_settings.get(accrual_id, {})
            rtype_key  = setting.get("type", "возврат")
            rtype_lbl  = RETURN_KEYS_LABELS.get(rtype_key, "Возврат к продаже")

            exp    = float(row.get("_reverse_logistics_cost", 0.0))
            cost   = float(row["Себестоимость"])
            profit = float(row["Прибыль"])

            total_exp    += exp
            total_cost   += cost
            total_profit += profit

            if rtype_key == "восстановление":
                restoration_val = f"{float(setting.get('restoration_cost', 0.0)):,.2f}"
            else:
                restoration_val = "—"

            tag = "neg" if profit < 0 else "pos"
            tree.insert("", "end", iid=accrual_id, values=[
                accrual_id,
                str(row.get("SKU", "")),
                str(row.get("Название товара", "")),
                f"{exp:,.2f}",
                f"{cost:,.2f}",
                rtype_lbl,
                restoration_val,
                f"{profit:,.2f}",
            ], tags=(tag,))

        tree.insert("", "end", iid="_ret_total", values=[
            "ИТОГО ВОЗВРАТЫ:", "", "",
            f"{total_exp:,.2f}",
            f"{total_cost:,.2f}",
            "", "",
            f"{total_profit:,.2f}",
        ], tags=("total_ret",))

        tree.tag_configure("neg",       foreground=COLORS["neg"])
        tree.tag_configure("pos",       foreground=COLORS["success"])
        tree.tag_configure("total_ret", font=("", 10, "bold"), background=COLORS["returns_bg"])

        _autofit_tree_columns(tree, left_cols=left_set, max_w=300)

    def _on_select(self, event):
        sel = self._tree.selection()
        if not sel or sel[0] == "_ret_total":
            return
        accrual_id = sel[0]
        self._selected_id = accrual_id
        settings   = load_return_settings()
        setting    = settings.get(accrual_id, {})
        rtype_key  = setting.get("type", "возврат")
        rtype_lbl  = RETURN_KEYS_LABELS.get(rtype_key, "Возврат к продаже")
        self._type_var.set(rtype_lbl)
        self._restoration_var.set(str(setting.get("restoration_cost", "0")))
        self._info_var.set(f"ID: {accrual_id}")
        self._update_restoration_visibility()

    def _on_type_change(self, *args):
        self._update_restoration_visibility(reset_value=True)

    def _update_restoration_visibility(self, reset_value: bool = False):
        if self._type_var.get() == "Восстановление":
            self._restoration_entry.configure(state="normal")
        else:
            if reset_value:
                self._restoration_var.set("0")
            self._restoration_entry.configure(state="disabled")

    def _save_setting(self):
        if not self._selected_id:
            messagebox.showwarning("Внимание", "Выберите возврат для настройки")
            return
        rtype_lbl = self._type_var.get()
        rtype_key = RETURN_TYPE_KEYS.get(rtype_lbl, "возврат")
        settings  = load_return_settings()
        settings[self._selected_id] = {"type": rtype_key}
        if rtype_key == "восстановление":
            try:
                restoration = float(self._restoration_var.get().replace(",", ".").replace(" ", ""))
                if restoration < 0:
                    raise ValueError
                settings[self._selected_id]["restoration_cost"] = restoration
            except ValueError:
                messagebox.showwarning("Внимание", "Введите корректную стоимость доработки")
                return
        save_return_settings(settings)
        self._on_change()
        self._render()


# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ГРАФИКОВ
# ══════════════════════════════════════════════════════════════════════════════

def _draw_analytics_chart(ax, idx: int, df: pd.DataFrame,
                          compact: bool, top_metric: str) -> None:
    import numpy as np

    C_POS   = COLORS["primary"]
    C_NEG   = COLORS["danger"]
    C_GRID  = COLORS["border"]
    C_TEXT  = COLORS["text"]
    C_MUTED = COLORS["text_muted"]
    fs_t = 9.5 if compact else 14
    fs_l = 7.5 if compact else 11
    fs_k = 7.5 if compact else 10
    fs_v = 6.5 if compact else 9
    fs_g = 7   if compact else 10

    def _fmt_k(x, _=None):
        if abs(x) >= 1_000_000: return f"{x/1_000_000:.1f}M"
        if abs(x) >= 1_000:     return f"{x/1_000:.0f}k"
        return f"{x:.0f}"

    def _fmt_pct(x, _=None): return f"{x:.0f}%"

    def _style(a):
        a.set_facecolor(COLORS["card"])
        a.spines["top"].set_visible(False)
        a.spines["right"].set_visible(False)
        a.spines["left"].set_color(C_GRID)
        a.spines["bottom"].set_color(C_GRID)
        a.tick_params(colors=C_MUTED, labelsize=fs_k)
        a.set_axisbelow(True)

    if idx == 0:
        _style(ax)
        metric_col = {"Прибыль": "Прибыль", "Выручка": "Выручка", "Продано": "Количество"}.get(
            top_metric, "Прибыль"
        )
        if "Название товара" in df.columns and metric_col in df.columns:
            by_name = df.groupby("Название товара")[metric_col].sum().sort_values().tail(10)
            colors  = [C_NEG if v < 0 else C_POS for v in by_name.values]
            bars    = ax.barh(range(len(by_name)), by_name.values,
                              color=colors, height=0.62, edgecolor="none")
            ax.set_yticks(range(len(by_name)))
            ax.set_yticklabels([str(s) for s in by_name.index], fontsize=fs_l, color=C_TEXT)
            ax.set_title(f"Топ товаров  ·  {top_metric}",
                         fontsize=fs_t, fontweight="bold", color=C_TEXT, pad=8, loc="left")
            ax.axvline(0, color=C_MUTED, linewidth=0.8)
            ax.xaxis.set_major_formatter(_fmt_k)
            ax.grid(axis="x", color=C_GRID, linestyle="--", linewidth=0.6, alpha=0.8)
            max_val = max((abs(v) for v in by_name.values), default=1)
            for bar, val in zip(bars, by_name.values):
                offset  = max_val * 0.02
                ha      = "left" if val >= 0 else "right"
                lbl_txt = str(int(val)) if metric_col == "Количество" else f"{val:,.0f}"
                ax.text(val + (offset if val >= 0 else -offset),
                        bar.get_y() + bar.get_height() / 2,
                        lbl_txt, ha=ha, va="center", fontsize=fs_v, color=C_TEXT)

    elif idx == 1:
        _style(ax)
        if "Дата начисления" in df.columns and "Выручка" in df.columns and "Прибыль" in df.columns:
            by_date = (df.groupby("Дата начисления")[["Выручка", "Прибыль"]]
                       .sum().reset_index().sort_values("Дата начисления"))
            x     = np.arange(len(by_date))
            rev_v = by_date["Выручка"].values
            prf_v = by_date["Прибыль"].values
            ax.bar(x, rev_v, color=C_POS, width=0.55, alpha=0.65,
                   edgecolor="none", label="Выручка")
            ax2b = ax.twinx()
            ax2b.plot(x, prf_v, color=COLORS["warning"],
                      linewidth=2, marker="o", markersize=3.5 if compact else 6,
                      label="Прибыль", zorder=4)
            ax2b.axhline(0, color=C_MUTED, linewidth=0.6)
            ax2b.spines["top"].set_visible(False)
            ax2b.spines["right"].set_color(C_GRID)
            ax2b.spines["left"].set_visible(False)
            ax2b.spines["bottom"].set_visible(False)
            ax2b.tick_params(axis="y", colors=COLORS["warning"], labelsize=fs_k)
            ax2b.yaxis.set_major_formatter(_fmt_k)
            if len(by_date) >= 3:
                z = np.polyfit(x, prf_v, 1)
                ax2b.plot(x, np.poly1d(z)(x), color=COLORS["danger"],
                          linewidth=1.2, linestyle=":", alpha=0.8,
                          label="Тренд прибыли", zorder=3)
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2b.get_legend_handles_labels()
            ax.legend(h1 + h2, l1 + l2,
                      fontsize=fs_g, frameon=False, labelcolor=C_MUTED, loc="upper left")
            ax.set_xticks(x)
            ax.set_xticklabels(by_date["Дата начисления"],
                               rotation=45, ha="right", fontsize=fs_k - 1)
            ax.set_title("Динамика  ·  Выручка + Прибыль",
                         fontsize=fs_t, fontweight="bold", color=C_TEXT, pad=8, loc="left")
            ax.set_ylabel("Выручка, руб.", fontsize=fs_l, color=C_MUTED, labelpad=4)
            ax.yaxis.set_major_formatter(_fmt_k)
            ax.grid(axis="y", color=C_GRID, linestyle="--", linewidth=0.6, alpha=0.8)

    elif idx == 2:
        ax.set_facecolor(COLORS["card"])
        if "Название товара" in df.columns and "Прибыль" in df.columns:
            by_profit = df.groupby("Название товара")["Прибыль"].sum()
            by_profit = by_profit[by_profit > 0].sort_values(ascending=False)
            if not by_profit.empty:
                top5       = by_profit.head(5)
                others_val = by_profit.iloc[5:].sum() if len(by_profit) > 5 else 0.0
                if others_val > 0:
                    top5 = pd.concat([top5, pd.Series({"Остальные": others_val})])
                palette = ["#3B82F6", "#A855F7", "#EAB308", "#22C55E", "#F97316", "#94A3B8"]
                wedges, _, autotexts = ax.pie(
                    top5.values, labels=None, autopct="%1.0f%%", startangle=90,
                    wedgeprops={"width": 0.55, "edgecolor": COLORS["bg"], "linewidth": 1.5},
                    colors=palette[:len(top5)], pctdistance=0.75
                )
                for at in autotexts:
                    at.set_fontsize(6.5 if compact else 10)
                    at.set_color("white")
                ax.text(0, 0, f"{top5.sum():,.0f}\nруб.",
                        ha="center", va="center",
                        fontsize=8 if compact else 14,
                        fontweight="bold", color=C_TEXT, linespacing=1.4)
                ax.legend(wedges, [str(s) for s in top5.index],
                          loc="lower center",
                          bbox_to_anchor=(0.5, -0.22 if compact else -0.12),
                          fontsize=6.5 if compact else 10,
                          frameon=False, ncol=2 if compact else 3, labelcolor=C_TEXT)
        ax.set_title("Доля в прибыли  ·  Топ-5",
                     fontsize=fs_t, fontweight="bold", color=C_TEXT, pad=8, loc="left")

    elif idx == 3:
        _style(ax)
        if {"Название товара", "Количество", "Рентабельность", "Выручка"}.issubset(df.columns):
            grp = df.groupby("Название товара").agg(
                qty=("Количество",       "sum"),
                margin=("Рентабельность", "mean"),
                revenue=("Выручка",        "sum")
            ).reset_index()
            grp = grp[grp["qty"] > 0].copy()
            if not grp.empty:
                rev_max  = grp["revenue"].max() or 1.0
                sz_max   = 600 if compact else 1400
                sizes    = (grp["revenue"] / rev_max * sz_max + 30).clip(30, sz_max + 100)
                med_qty    = grp["qty"].median()
                med_margin = grp["margin"].median()
                pos = grp["margin"] >= 0
                ax.scatter(grp.loc[pos,  "qty"], grp.loc[pos,  "margin"],
                           s=sizes[pos],  alpha=0.65, color=C_POS,
                           edgecolors=COLORS["bg"], linewidth=0.8)
                ax.scatter(grp.loc[~pos, "qty"], grp.loc[~pos, "margin"],
                           s=sizes[~pos], alpha=0.65, color=C_NEG,
                           edgecolors=COLORS["bg"], linewidth=0.8)
                ax.axvline(med_qty,    color=C_MUTED, linestyle="--", linewidth=0.8, alpha=0.7)
                ax.axhline(med_margin, color=C_MUTED, linestyle="--", linewidth=0.8, alpha=0.7)
                ax.axhline(0, color=C_NEG, linewidth=0.6, alpha=0.4)
                fq = 6.5 if compact else 10
                ax.text(0.98, 0.98, "Звёзды",        transform=ax.transAxes,
                        ha="right", va="top",    fontsize=fq, color=COLORS["success"], alpha=0.8)
                ax.text(0.02, 0.98, "Нишевые",       transform=ax.transAxes,
                        ha="left",  va="top",    fontsize=fq, color=C_MUTED, alpha=0.8)
                ax.text(0.98, 0.02, "Дойные коровы", transform=ax.transAxes,
                        ha="right", va="bottom", fontsize=fq, color=C_MUTED, alpha=0.8)
                ax.text(0.02, 0.02, "Аутсайдеры",    transform=ax.transAxes,
                        ha="left",  va="bottom", fontsize=fq, color=C_NEG, alpha=0.8)
                top_n  = 5 if compact else len(grp)
                fs_ann = 5.5 if compact else 8.5
                for _, row in grp.nlargest(top_n, "revenue").iterrows():
                    ax.annotate(str(row["Название товара"]),
                                (row["qty"], row["margin"]),
                                fontsize=fs_ann, color=C_MUTED, ha="center",
                                xytext=(0, 8), textcoords="offset points")
                ax.set_xlabel("Продано, шт.", fontsize=fs_l, color=C_MUTED, labelpad=4)
                ax.set_ylabel("Рентабельность, %", fontsize=fs_l, color=C_MUTED, labelpad=4)
                ax.yaxis.set_major_formatter(_fmt_pct)
                ax.grid(color=C_GRID, linestyle="--", linewidth=0.5, alpha=0.7)
        ax.set_title("Матрица ассортимента",
                     fontsize=fs_t, fontweight="bold", color=C_TEXT, pad=8, loc="left")


# ══════════════════════════════════════════════════════════════════════════════
# ВКЛАДКА НАЧИСЛЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════

class InsightsPanel(tk.Frame):
    """Scrollable dark panel showing promo recommendations."""

    def __init__(self, master):
        super().__init__(master, bg=COLORS["bg"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=COLORS["sidebar"])
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="💡  Умные рекомендации",
                 font=("", 13, "bold"), bg=COLORS["sidebar"],
                 fg=COLORS["text"], anchor="w").pack(side="left", padx=16, pady=10)
        self._threshold_lbl = tk.Label(
            header, text="", font=("", 9),
            bg=COLORS["sidebar"], fg=COLORS["text_muted"]
        )
        self._threshold_lbl.pack(side="right", padx=16)

        # ── Scrollable canvas ─────────────────────────────────────────────────
        container = tk.Frame(self, bg=COLORS["bg"])
        container.grid(row=1, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(container, bg=COLORS["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._inner = tk.Frame(self._canvas, bg=COLORS["bg"])
        self._win_id = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", lambda _: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")
        ))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(
            self._win_id, width=e.width
        ))
        self._canvas.bind("<Enter>", lambda _: self._canvas.bind_all(
            "<MouseWheel>", self._on_wheel
        ))
        self._canvas.bind("<Leave>", lambda _: self._canvas.unbind_all("<MouseWheel>"))

    def _on_wheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self, df: pd.DataFrame):
        threshold, insights = compute_promo_insights(df)

        if threshold > 0:
            leader = int(threshold * 2)
            self._threshold_lbl.configure(
                text=f"Порог низких продаж: < {int(threshold)} шт.  ·  лидер: {leader} шт."
            )
        else:
            self._threshold_lbl.configure(text="")

        for w in self._inner.winfo_children():
            w.destroy()

        if insights.empty:
            tk.Frame(self._inner, bg=COLORS["bg"], height=40).pack()
            tk.Label(self._inner, text="✅",
                     font=("", 28), bg=COLORS["bg"], fg=COLORS["success"]).pack()
            tk.Label(self._inner,
                     text="Нет товаров с высокой маржинальностью\nи слабыми продажами",
                     font=("", 11), bg=COLORS["bg"],
                     fg=COLORS["text_muted"], justify="center").pack(pady=(8, 0))
            return

        for _, row in insights.iterrows():
            self._build_card(row, threshold)
        tk.Frame(self._inner, bg=COLORS["bg"], height=20).pack()

    def _build_card(self, row, threshold: float):
        wrapper = tk.Frame(self._inner, bg=COLORS["bg"])
        wrapper.pack(fill="x", padx=16, pady=(12, 0))

        # 1-px border effect
        border = tk.Frame(wrapper, bg=COLORS["border"])
        border.pack(fill="x")
        card = tk.Frame(border, bg=COLORS["card"])
        card.pack(fill="x", padx=1, pady=1)

        # Accent stripe
        tk.Frame(card, bg=COLORS["warning"], width=4).pack(side="left", fill="y")

        body = tk.Frame(card, bg=COLORS["card"])
        body.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        # Product name
        name_text = str(row["name"])
        tk.Label(body, text=name_text,
                 font=("", 10, "bold"), bg=COLORS["card"],
                 fg=COLORS["text"], anchor="w", wraplength=600,
                 justify="left").pack(anchor="w")

        tk.Label(body, text=f"SKU: {row['SKU']}",
                 font=("", 8), bg=COLORS["card"],
                 fg=COLORS["text_muted"]).pack(anchor="w", pady=(2, 8))

        # Metrics chips row
        chips = tk.Frame(body, bg=COLORS["card"])
        chips.pack(anchor="w", pady=(0, 8))

        def _chip(parent, label, value, color):
            c = tk.Frame(parent, bg=COLORS["bg"],
                         highlightbackground=COLORS["border"], highlightthickness=1)
            c.pack(side="left", padx=(0, 6))
            tk.Label(c, text=label, font=("", 7), bg=COLORS["bg"],
                     fg=COLORS["text_muted"]).pack(padx=7, pady=(4, 0))
            tk.Label(c, text=value, font=("", 10, "bold"), bg=COLORS["bg"],
                     fg=color).pack(padx=7, pady=(0, 4))

        _chip(chips, "Продано",        f"{int(row['qty'])} шт.",    COLORS["text"])
        _chip(chips, "Порог",          f"< {int(threshold)} шт.",   COLORS["warning"])
        _chip(chips, "Рентабельность", f"{row['margin']:.1f}%",     COLORS["success"])
        _chip(chips, "Прибыль",
              f"{row['profit']:,.0f} ₽",
              COLORS["success"] if row["profit"] >= 0 else COLORS["danger"])

        # Recommendation box
        rec = tk.Frame(body, bg="#1C2A1A",
                       highlightbackground=COLORS["success"], highlightthickness=1)
        rec.pack(fill="x")
        tk.Label(rec,
                 text=("🔥  Высокая маржинальность при слабых продажах "
                       "(менее половины от лидера категории). "
                       "Рекомендуется запустить товар в промо-акцию Ozon "
                       "или снизить цену на 5–10%, чтобы поднять карточку в топ."),
                 font=("", 9), bg="#1C2A1A", fg="#86EFAC",
                 anchor="w", wraplength=620, justify="left").pack(
            anchor="w", padx=10, pady=7
        )


class AccrualTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._df_raw:     pd.DataFrame | None = None
        self._df_regular: pd.DataFrame | None = None
        self._df_returns: pd.DataFrame | None = None
        self._sort_col:   str | None = None
        self._sort_asc:   bool = True
        self._expanded_skus = set()
        self._top_metric:      str                 = "Прибыль"
        self._last_df:         pd.DataFrame | None = None
        self._kpi_val_labels:  dict                = {}
        self._metric_btns:     dict                = {}
        self._chart_main_axes: list                = []
        self._chart_cid:       object              = None
        self._detail_df_raw:    pd.DataFrame | None = None
        self._detail_tab:       str                 = "all"
        self._detail_group_var: tk.StringVar | None = None
        self._detail_group_cb:  ttk.Combobox | None = None
        self._detail_search_var: tk.StringVar | None = None
        self._detail_count_var: tk.StringVar | None = None
        self._detail_seg_btns:  dict               = {}
        self._insights_panel:  "InsightsPanel | None" = None
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        tb = ttk.Frame(self)
        tb.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        create_button(tb, text="Экспорт CSV", command=self._export_csv,
                      width=12, padx=5, pady=2).pack(side="left", padx=2)
        create_button(tb, text="🖨️ Печать", command=self._open_print_form,
                      width=12, padx=5, pady=2, bg="#3498db", fg="white").pack(side="left", padx=2)

        ttk.Label(tb, text="Фильтр:").pack(side="left", padx=(10, 2))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        ttk.Entry(tb, textvariable=self._search_var, width=28).pack(side="left")
        self._status = tk.StringVar(value="")
        ttk.Label(tb, textvariable=self._status, foreground="gray").pack(side="right", padx=6)

        main_nb = ttk.Notebook(self)
        main_nb.grid(row=1, column=0, sticky="nsew")

        # ── Вкладка «Начисления» ─────────────────────────────────────────────
        tables_frame = ttk.Frame(main_nb)
        main_nb.add(tables_frame, text="Начисления")
        tables_frame.columnconfigure(0, weight=1)
        tables_frame.rowconfigure(0, weight=1)

        paned = ttk.PanedWindow(tables_frame, orient="vertical")
        paned.grid(row=0, column=0, sticky="nsew")

        top = ttk.LabelFrame(paned, text="Сводка по начислениям (Группировка по SKU)")
        paned.add(top, weight=3)
        top.columnconfigure(0, weight=1)
        top.rowconfigure(0, weight=1)

        self._tree_summary = ttk.Treeview(top, show="headings", selectmode="browse")
        vsb1 = ttk.Scrollbar(top, orient="vertical",   command=self._tree_summary.yview)
        hsb1 = ttk.Scrollbar(top, orient="horizontal", command=self._tree_summary.xview)
        self._tree_summary.configure(yscrollcommand=vsb1.set, xscrollcommand=hsb1.set)
        self._tree_summary.grid(row=0, column=0, sticky="nsew")
        vsb1.grid(row=0, column=1, sticky="ns")
        hsb1.grid(row=1, column=0, sticky="ew")
        self._tree_summary.bind("<ButtonRelease-1>", self._on_click)

        bot_nb = ttk.Notebook(paned)
        paned.add(bot_nb, weight=2)

        # Детали начислений
        detail_frame = ttk.Frame(bot_nb)
        bot_nb.add(detail_frame, text="Детали начислений")
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(1, weight=1)

        filter_bar = tk.Frame(detail_frame, bg=COLORS["bg"])
        filter_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 0))
        self._build_detail_filter_bar(filter_bar)

        self._tree_detail = ttk.Treeview(detail_frame, show="headings", selectmode="browse")
        vsb2 = ttk.Scrollbar(detail_frame, orient="vertical",   command=self._tree_detail.yview)
        hsb2 = ttk.Scrollbar(detail_frame, orient="horizontal", command=self._tree_detail.xview)
        self._tree_detail.configure(yscrollcommand=vsb2.set, xscrollcommand=hsb2.set)
        self._tree_detail.grid(row=1, column=0, sticky="nsew")
        vsb2.grid(row=1, column=1, sticky="ns")
        hsb2.grid(row=2, column=0, sticky="ew")

        # Возвраты
        returns_frame = ttk.Frame(bot_nb)
        bot_nb.add(returns_frame, text="🔄 Возвраты")
        returns_frame.columnconfigure(0, weight=1)
        returns_frame.rowconfigure(0, weight=1)
        self._returns_section = ReturnsSection(returns_frame, on_change=self._refresh_from_returns)
        self._returns_section.grid(row=0, column=0, sticky="nsew")

        # ── Вкладка «Графики» — на полную высоту ────────────────────────────
        chart_frame = ttk.Frame(main_nb)
        main_nb.add(chart_frame, text="📊 Графики")
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(2, weight=1)

        kpi_frame = tk.Frame(chart_frame, bg=COLORS["bg"])
        kpi_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 0))
        self._build_kpi_cards(kpi_frame)

        btn_bar = tk.Frame(chart_frame, bg=COLORS["bg"])
        btn_bar.grid(row=1, column=0, sticky="w", padx=8, pady=2)
        self._build_metric_buttons(btn_bar)

        self._fig = Figure(figsize=(14, 7), dpi=90)
        self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
        self._canvas.get_tk_widget().grid(row=2, column=0, sticky="nsew")

        # ── Вкладка «Рекомендации» ───────────────────────────────────────────
        insights_frame = ttk.Frame(main_nb)
        main_nb.add(insights_frame, text="💡 Рекомендации")
        insights_frame.columnconfigure(0, weight=1)
        insights_frame.rowconfigure(0, weight=1)
        self._insights_panel = InsightsPanel(insights_frame)
        self._insights_panel.grid(row=0, column=0, sticky="nsew")

    # ── Фильтр-бар деталей ───────────────────────────────────────────────────

    def _build_detail_filter_bar(self, parent: tk.Frame):
        # Segmented control
        seg_frame = tk.Frame(parent, bg=COLORS["card"],
                             highlightbackground=COLORS["border"], highlightthickness=1)
        seg_frame.pack(side="left", padx=(0, 8), pady=1)
        for key, label in [("all", "Все"), ("income", "Доходы"),
                           ("expense", "Расходы"), ("penalty", "Штрафы")]:
            btn = FlatButton(
                seg_frame, text=label, font=("", 8),
                padx=9, pady=3, cursor="hand2",
                command=lambda k=key: self._set_detail_tab(k)
            )
            btn.pack(side="left")
            self._detail_seg_btns[key] = btn

        # Group dropdown
        tk.Label(parent, text="Группа:", bg=COLORS["bg"],
                 fg=COLORS["text_muted"], font=("", 8)).pack(side="left", padx=(0, 3))
        self._detail_group_var = tk.StringVar(value="Все группы")
        self._detail_group_cb = ttk.Combobox(
            parent, textvariable=self._detail_group_var,
            values=["Все группы"], state="readonly", width=18
        )
        self._detail_group_cb.pack(side="left", padx=(0, 8))
        self._detail_group_var.trace_add("write", lambda *_: self._apply_detail_filters())

        # Search
        tk.Label(parent, text="🔍", bg=COLORS["bg"],
                 fg=COLORS["text_muted"], font=("", 9)).pack(side="left", padx=(0, 2))
        self._detail_search_var = tk.StringVar()
        self._detail_search_var.trace_add("write", lambda *_: self._apply_detail_filters())
        ttk.Entry(parent, textvariable=self._detail_search_var, width=20).pack(side="left", padx=(0, 6))

        # Counter
        self._detail_count_var = tk.StringVar(value="")
        tk.Label(parent, textvariable=self._detail_count_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"], font=("", 8)).pack(side="right", padx=4)

        self._update_detail_seg_btns()

    def _update_detail_seg_btns(self):
        for key, btn in self._detail_seg_btns.items():
            if key == self._detail_tab:
                btn.configure(bg=COLORS["primary"], fg="white")
            else:
                btn.configure(bg=COLORS["card"], fg=COLORS["text_muted"])

    def _set_detail_tab(self, tab: str):
        self._detail_tab = tab
        self._update_detail_seg_btns()
        self._apply_detail_filters()

    # ── Загрузка данных ───────────────────────────────────────────────────────

    def load(self, df_raw: pd.DataFrame):
        self._df_raw = df_raw
        self._df_regular, self._df_returns = build_accrual_summary(df_raw)
        self._render_summary()
        self._returns_section.load(self._df_returns)
        self._render_charts(self._df_regular)

    def _refresh_from_returns(self):
        """Пересчитывает всё после изменения настроек возврата."""
        if self._df_raw is None:
            return
        self._df_regular, self._df_returns = build_accrual_summary(self._df_raw)
        self._render_summary()
        self._returns_section.load(self._df_returns)
        self._render_charts(self._df_regular)

    # ── Сводная таблица ───────────────────────────────────────────────────────

    def _render_summary(self):
        if self._df_regular is None:
            return
        tree = self._tree_summary
        tree.delete(*tree.get_children())

        cols = [
            "Группировка / SKU", "Название товара", "Продано", "Выручка", "Расходы",
            "Поступление от ОЗОН", "Себестоимость", "Прибыль", "Рентабельность"
        ]
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c, command=lambda _c=c: self._sort(_c))
            tree.column(c, width=130, anchor="e", stretch=False)
        tree.column("Группировка / SKU", width=180, anchor="w")
        tree.column("Название товара",   width=240, anchor="w")
        tree.column("Продано",           width=70,  anchor="e")

        # Регулярные начисления по SKU
        total_qty    = 0
        total_rev    = 0.0
        total_exp    = 0.0
        total_no_vat = 0.0
        total_cost   = 0.0
        total_fin    = 0.0

        grouped = self._df_regular.groupby("SKU")
        for sku, group in grouped:
            qty    = int(group["Количество"].sum())
            rev    = group["Выручка"].sum()
            exp    = group["Расходы"].sum()
            no_vat = group["Поступление от ОЗОН"].sum()
            c      = group["Себестоимость"].sum()
            fin    = group["Прибыль"].sum()
            margin = (no_vat / c * 100 - 100) if c > 0 else 0.0

            total_qty    += qty
            total_rev    += rev
            total_exp    += exp
            total_no_vat += no_vat
            total_cost   += c
            total_fin    += fin

            prefix = "▼ " if sku in self._expanded_skus else "▶ "
            name   = str(group.iloc[0].get("Название товара", "")) if "Название товара" in group.columns else ""

            sku_tag = "sku_neg" if fin < 0 else "sku_group"
            tree.insert("", "end", iid=f"group_{sku}", tags=(sku_tag,), values=[
                f"{prefix}{sku}", name,
                str(qty),
                f"{rev:,.2f}", f"{exp:,.2f}", f"{no_vat:,.2f}",
                f"{c:,.2f}", f"{fin:,.2f}", f"{margin:.2f}%"
            ])

            if sku in self._expanded_skus:
                for _, child_row in group.iterrows():
                    c_margin = (child_row["Поступление от ОЗОН"] / child_row["Себестоимость"] * 100 - 100) if child_row["Себестоимость"] > 0 else 0.0
                    child_name = str(child_row.get("Название товара", "")) if "Название товара" in child_row.index else ""
                    c_tag = "neg" if child_row["Прибыль"] < 0 else "child"
                    tree.insert("", "end", iid=str(child_row["ID начисления"]), tags=(c_tag,), values=[
                        f"    ID: {child_row['ID начисления']}",
                        child_name,
                        str(int(child_row["Количество"])),
                        f"{child_row['Выручка']:,.2f}",
                        f"{child_row['Расходы']:,.2f}",
                        f"{child_row['Поступление от ОЗОН']:,.2f}",
                        f"{child_row['Себестоимость']:,.2f}",
                        f"{child_row['Прибыль']:,.2f}",
                        f"{c_margin:.2f}%"
                    ])

        # Строка сводки по возвратам
        ret_exp    = 0.0
        ret_no_vat = 0.0
        ret_cost   = 0.0
        ret_fin    = 0.0
        if self._df_returns is not None and not self._df_returns.empty:
            ret_exp    = self._df_returns["_reverse_logistics_cost"].sum()
            ret_no_vat = self._df_returns["Поступление от ОЗОН"].sum()
            ret_cost   = self._df_returns["Себестоимость"].sum()
            ret_fin    = self._df_returns["Прибыль"].sum()
            n_ret      = len(self._df_returns)
            tree.insert("", "end", iid="returns_summary_row", tags=("returns_row",), values=[
                f"↩ Возвраты ({n_ret} шт.)",
                "", "",
                f"{ret_exp:,.2f}",
                f"{ret_no_vat:,.2f}",
                f"{ret_cost:,.2f}",
                f"{ret_fin:,.2f}",
                ""
            ])

        # Итого с учётом возвратов
        grand_no_vat = total_no_vat + ret_no_vat
        grand_cost   = total_cost   + ret_cost
        grand_fin    = total_fin    + ret_fin
        grand_margin = (grand_no_vat / grand_cost * 100 - 100) if grand_cost > 0 else 0.0
        tree.insert("", "end", iid="total_row_summary", tags=("total_summary",), values=[
            "ИТОГО ПО ВСЕМ ТОВАРАМ:",
            "",
            str(total_qty),
            f"{total_rev:,.2f}",
            f"{total_exp + ret_exp:,.2f}",
            f"{grand_no_vat:,.2f}",
            f"{grand_cost:,.2f}",
            f"{grand_fin:,.2f}",
            f"{grand_margin:.2f}%"
        ])

        tree.tag_configure("sku_group",    font=("", 10, "bold"), background=COLORS["sku_bg"])
        tree.tag_configure("sku_neg",      font=("", 10, "bold"), background=COLORS["sku_bg"], foreground=COLORS["neg"])
        tree.tag_configure("neg",          foreground=COLORS["neg"])
        tree.tag_configure("child",        foreground=COLORS["text"])
        tree.tag_configure("returns_row",  font=("", 10, "bold"), background=COLORS["returns_bg"], foreground=COLORS["warning"])
        tree.tag_configure("total_summary", font=("", 10, "bold"), background=COLORS["total_bg"])

        _autofit_tree_columns(tree, left_cols={"Группировка / SKU", "Название товара"})
        self._status.set(f"{len(self._df_regular)} записей + {len(self._df_returns) if self._df_returns is not None else 0} возвратов")

    # ── Детали ────────────────────────────────────────────────────────────────

    def _on_click(self, event):
        item_id = self._tree_summary.focus()
        if not item_id or self._df_raw is None:
            return
        if item_id in ("total_row_summary", "returns_summary_row"):
            return
        if item_id.startswith("group_"):
            sku = item_id.replace("group_", "")
            if sku in self._expanded_skus:
                self._expanded_skus.remove(sku)
            else:
                self._expanded_skus.add(sku)
            self._render_summary()
        else:
            df_detail = self._df_raw[
                self._df_raw["ID начисления"].astype(str).str.strip() == item_id
            ].copy()
            self._render_detail(df_detail)

    def _render_detail(self, df: pd.DataFrame):
        self._detail_df_raw = df.copy()
        group_col = "Группа услуг"
        if self._detail_group_var is not None and group_col in df.columns:
            groups = ["Все группы"] + sorted(
                df[group_col].dropna().astype(str).str.strip().unique().tolist()
            )
            if self._detail_group_cb is not None:
                self._detail_group_cb["values"] = groups
            self._detail_group_var.set("Все группы")
        self._apply_detail_filters()

    def _apply_detail_filters(self):
        if self._detail_df_raw is None:
            return
        df         = self._detail_df_raw.copy()
        amount_col = "Сумма итого, руб."
        op_col     = "Тип начисления"

        if self._detail_tab != "all" and amount_col in df.columns:
            amounts = df[amount_col].apply(parse_amount)
            if self._detail_tab == "income":
                df = df[amounts > 0]
            elif self._detail_tab == "expense":
                df = df[amounts < 0]
                if op_col in df.columns:
                    pen = df[op_col].astype(str).str.lower().str.contains(
                        r"штраф|эквайр|дополнительн", regex=True
                    )
                    df = df[~pen]
            elif self._detail_tab == "penalty":
                if op_col in df.columns:
                    pen = df[op_col].astype(str).str.lower().str.contains(
                        r"штраф|эквайр|дополнительн", regex=True
                    )
                    df = df[pen]
                else:
                    df = df[df[amount_col].apply(parse_amount) < 0]

        group_col = "Группа услуг"
        group_val = self._detail_group_var.get() if self._detail_group_var else "Все группы"
        if group_val and group_val != "Все группы" and group_col in df.columns:
            df = df[df[group_col].astype(str).str.strip() == group_val]

        q = (self._detail_search_var.get() if self._detail_search_var else "").strip().lower()
        if q:
            mask = df.apply(lambda r: r.astype(str).str.lower().str.contains(q).any(), axis=1)
            df = df[mask]

        self._render_detail_filtered(df)

    def _render_detail_filtered(self, df: pd.DataFrame):
        tree = self._tree_detail
        tree.delete(*tree.get_children())

        if df.empty:
            if self._detail_count_var:
                self._detail_count_var.set("Нет строк")
            return

        non_empty = [c for c in df.columns
                     if df[c].notna().any() and (df[c].astype(str).str.strip() != "").any()]
        df   = df[non_empty]
        cols = list(df.columns)
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c)

        amount_col = "Сумма итого, руб."
        op_col     = "Тип начисления"

        for _, row in df.iterrows():
            vals = [("" if pd.isna(row[c]) else str(row[c])) for c in cols]
            tag = ""
            if amount_col in cols:
                amt = parse_amount(row.get(amount_col, 0))
                op  = str(row.get(op_col, "")).lower() if op_col in cols else ""
                if amt > 0:
                    tag = "detail_income"
                elif any(kw in op for kw in ("штраф", "эквайр", "дополнительн")):
                    tag = "detail_penalty"
                else:
                    tag = "detail_expense"
            tree.insert("", "end", values=vals, tags=(tag,) if tag else ())

        tree.tag_configure("detail_income",  foreground="#4ADE80")
        tree.tag_configure("detail_expense", foreground="#F87171")
        tree.tag_configure("detail_penalty", foreground="#F59E0B")

        _autofit_tree_columns(tree, left_cols=LEFT_COLS)
        if self._detail_count_var:
            self._detail_count_var.set(f"Найдено: {len(df)} строк")

    # ── Графики ───────────────────────────────────────────────────────────────

    def _build_kpi_cards(self, parent: tk.Frame):
        KPI_DEFS = [
            ("Выручка",         "выручка",        "₽",    False),
            ("Чистая прибыль",  "прибыль",        "₽",    True),
            ("Рентабельность",  "рентабельность", "%",    True),
            ("Заказов, шт.",    "количество",     "шт.",  False),
        ]
        for i, (title, key, unit, colored) in enumerate(KPI_DEFS):
            card = tk.Frame(parent, bg=COLORS["card"],
                            highlightbackground=COLORS["border"],
                            highlightthickness=1)
            card.grid(row=0, column=i, padx=4, pady=2, sticky="ew")
            parent.columnconfigure(i, weight=1)
            tk.Label(card, text=title, bg=COLORS["card"],
                     fg=COLORS["text_muted"], font=("", 9)).pack(anchor="w", padx=8, pady=(5, 0))
            var = tk.StringVar(value="—")
            lbl = tk.Label(card, textvariable=var, bg=COLORS["card"],
                           fg=COLORS["text"], font=("", 16, "bold"))
            lbl.pack(anchor="w", padx=8, pady=(0, 5))
            self._kpi_val_labels[key] = (var, lbl, unit, colored)

    def _build_metric_buttons(self, parent: tk.Frame):
        tk.Label(parent, text="Топ товаров:", bg=COLORS["bg"],
                 fg=COLORS["text_muted"], font=("", 8)).pack(side="left", padx=(0, 4))
        for label in ["Прибыль", "Выручка", "Продано"]:
            btn = FlatButton(
                parent, text=label, font=("", 8),
                padx=8, pady=3, cursor="hand2",
                command=lambda l=label: self._set_top_metric(l)
            )
            btn.pack(side="left", padx=1)
            self._metric_btns[label] = btn
        self._update_metric_btn_styles()

    def _update_metric_btn_styles(self):
        for label, btn in self._metric_btns.items():
            if label == self._top_metric:
                btn.configure(bg=COLORS["primary"], fg="white")
            else:
                btn.configure(bg=COLORS["card"], fg=COLORS["text"])

    def _set_top_metric(self, metric: str):
        self._top_metric = metric
        self._update_metric_btn_styles()
        if self._last_df is not None:
            self._render_charts(self._last_df)

    def _update_kpi_cards(self, df: pd.DataFrame):
        total_rev  = float(df["Выручка"].sum())         if "Выручка"        in df.columns else 0.0
        total_prf  = float(df["Прибыль"].sum())         if "Прибыль"        in df.columns else 0.0
        total_qty  = int(df["Количество"].sum())        if "Количество"     in df.columns else 0
        avg_margin = float(df["Рентабельность"].mean()) if "Рентабельность" in df.columns else 0.0

        def _fmt(val, key, unit):
            if key == "количество":
                return f"{int(val):,} {unit}".replace(",", " ")
            if key == "рентабельность":
                return f"{val:.1f}{unit}"
            if abs(val) >= 1_000_000:
                return f"{val/1_000_000:.1f}M {unit}"
            if abs(val) >= 1_000:
                return f"{val/1_000:.0f} т.{unit}"
            return f"{val:.0f} {unit}"

        data = {
            "выручка":        total_rev,
            "прибыль":        total_prf,
            "рентабельность": avg_margin,
            "количество":     total_qty,
        }
        for key, (var, lbl, unit, colored) in self._kpi_val_labels.items():
            val = data.get(key, 0.0)
            var.set(_fmt(val, key, unit))
            if colored:
                lbl.configure(fg=COLORS["success"] if float(val) >= 0 else COLORS["danger"])

    def _draw_chart(self, ax, idx: int, df: pd.DataFrame, compact: bool = True):
        _draw_analytics_chart(ax, idx, df, compact, self._top_metric)

    def _on_chart_click(self, event):
        if event.inaxes is None or self._last_df is None:
            return
        for i, ax in enumerate(self._chart_main_axes):
            if event.inaxes is ax:
                self._open_chart_fullscreen(i)
                return

    def _open_chart_fullscreen(self, idx: int):
        top = tk.Toplevel(self)
        titles = ["Топ товаров", "Динамика", "Доля в прибыли", "Матрица ассортимента"]
        top.title(titles[idx])
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        top.geometry(f"{sw}x{sh}+0+0")
        try:
            top.state("zoomed")
        except Exception:
            top.attributes("-fullscreen", True)

        top.columnconfigure(0, weight=1)
        top.rowconfigure(1, weight=1)

        bar = tk.Frame(top, bg=COLORS["sidebar"], height=36)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        tk.Label(bar, text=titles[idx], bg=COLORS["sidebar"], fg="white",
                 font=("", 11, "bold")).grid(row=0, column=0, padx=12, pady=6, sticky="w")
        tk.Label(bar, text="Нажмите на график, чтобы закрыть",
                 bg=COLORS["sidebar"], fg="#94a3b8",
                 font=("", 9)).grid(row=0, column=1, padx=4, sticky="w")
        FlatButton(bar, text="✕  Закрыть", command=top.destroy,
                   bg=COLORS["sidebar"], fg="white",
                   font=("", 9), padx=10, pady=2, cursor="hand2").grid(row=0, column=2, padx=8, pady=4, sticky="e")

        dpi   = 96
        fig_w = sw / dpi
        fig_h = (sh - 44) / dpi
        fig_full = Figure(figsize=(fig_w, fig_h), dpi=dpi)
        fig_full.patch.set_facecolor(COLORS["bg"])
        canvas_full = FigureCanvasTkAgg(fig_full, master=top)
        canvas_full.get_tk_widget().grid(row=1, column=0, sticky="nsew")

        ax_full = fig_full.add_subplot(1, 1, 1)
        self._draw_chart(ax_full, idx, self._last_df, compact=False)
        fig_full.tight_layout(pad=2.5)
        canvas_full.draw()

        canvas_full.mpl_connect("button_press_event", lambda *_: top.destroy())

    def _render_charts(self, df: pd.DataFrame):
        if df is None or df.empty:
            return
        self._last_df = df
        self._update_kpi_cards(df)
        self._fig.clear()
        self._fig.patch.set_facecolor(COLORS["bg"])

        gs  = self._fig.add_gridspec(2, 2, hspace=0.5, wspace=0.35)
        ax1 = self._fig.add_subplot(gs[0, 0])
        ax2 = self._fig.add_subplot(gs[0, 1])
        ax3 = self._fig.add_subplot(gs[1, 0])
        ax4 = self._fig.add_subplot(gs[1, 1])

        self._draw_chart(ax1, 0, df, compact=True)
        self._draw_chart(ax2, 1, df, compact=True)
        self._draw_chart(ax3, 2, df, compact=True)
        self._draw_chart(ax4, 3, df, compact=True)

        self._chart_main_axes = [ax1, ax2, ax3, ax4]
        if self._chart_cid is not None:
            self._canvas.mpl_disconnect(self._chart_cid)
        self._chart_cid = self._canvas.mpl_connect("button_press_event", self._on_chart_click)

        self._fig.tight_layout(pad=1.5)
        self._canvas.draw()

        if self._insights_panel is not None:
            self._insights_panel.refresh(df)

    # ── Сортировка / фильтр ───────────────────────────────────────────────────

    def _sort(self, col: str):
        if self._df_regular is None:
            return
        asc = True if self._sort_col != col else not self._sort_asc
        df = self._df_regular.copy()
        try:
            df = df.sort_values(col, ascending=asc)
        except TypeError:
            df = df.sort_values(col, ascending=asc, key=lambda x: x.astype(str))
        self._sort_col = col
        self._sort_asc = asc
        self._df_regular = df
        self._render_summary()

    def _filter(self):
        if self._df_raw is None:
            return
        q = self._search_var.get().strip().lower()
        if not q:
            self._df_regular, self._df_returns = build_accrual_summary(self._df_raw)
            self._render_summary()
            self._returns_section.load(self._df_returns)
            return
        self._df_regular, self._df_returns = build_accrual_summary(self._df_raw)
        mask = self._df_regular.apply(
            lambda r: r.astype(str).str.lower().str.contains(q).any(), axis=1)
        self._df_regular = self._df_regular[mask]
        self._render_summary()

    # ── Экспорт / Печать ─────────────────────────────────────────────────────

    def _export_csv(self):
        if self._df_regular is None:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv")],
                                         initialfile="accruals.csv")
        if p:
            self._df_regular.to_csv(p, index=False, encoding="utf-8-sig")
            messagebox.showinfo("Экспорт", f"Сохранено: {p}")

    def _open_print_form(self):
        if self._df_regular is None or self._df_regular.empty:
            messagebox.showwarning("Внимание", "Нет данных для формирования печатной формы.")
            return

        print_window = tk.Toplevel(self)
        print_window.title("Форма для печати отчёта")
        print_window.geometry("1200x650")
        print_window.transient(self)
        print_window.grab_set()

        ptb = ttk.Frame(print_window)
        ptb.pack(fill="x", padx=10, pady=5)

        required_cols = [
            "Название товара", "Количество", "Выручка", "Расходы",
            "Поступление от ОЗОН", "Себестоимость", "Прибыль", "Рентабельность"
        ]

        p_tree = ttk.Treeview(print_window, columns=required_cols, show="headings", selectmode="none")
        vsb = ttk.Scrollbar(print_window, orient="vertical",   command=p_tree.yview)
        hsb = ttk.Scrollbar(print_window, orient="horizontal", command=p_tree.xview)
        p_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        p_tree.pack(fill="both", expand=True, padx=10, pady=(0, 5))
        vsb.pack(side="right", fill="y", before=p_tree)
        hsb.pack(fill="x", padx=10)

        for c in required_cols:
            p_tree.heading(c, text=c)
            p_tree.column(c, anchor="w" if c == "Название товара" else "e",
                          stretch=c == "Название товара", width=130)
        p_tree.column("Название товара", width=300)

        grouped = self._df_regular.groupby("SKU")
        sum_qty = 0; sum_rev = 0.0; sum_exp = 0.0
        sum_no_vat = 0.0; sum_cost = 0.0; sum_fin = 0.0
        html_rows = []

        for sku, group in grouped:
            q      = group["Количество"].sum()
            rev    = group["Выручка"].sum()
            exp    = group["Расходы"].sum()
            no_vat = group["Поступление от ОЗОН"].sum()
            c      = group["Себестоимость"].sum()
            fin    = group["Прибыль"].sum()
            m      = (no_vat / c * 100 - 100) if c > 0 else 0.0
            sum_qty += q; sum_rev += rev; sum_exp += exp
            sum_no_vat += no_vat; sum_cost += c; sum_fin += fin
            name_str = str(group.iloc[0]["Название товара"])
            vals = [name_str, str(q), f"{rev:,.2f}", f"{exp:,.2f}",
                    f"{no_vat:,.2f}", f"{c:,.2f}", f"{fin:,.2f}", f"{m:.2f}%"]
            p_tree.insert("", "end", values=vals)
            html_rows.append(
                f"<tr><td>{name_str}</td><td>{q}</td><td>{rev:,.2f}</td>"
                f"<td>{exp:,.2f}</td><td>{no_vat:,.2f}</td><td>{c:,.2f}</td>"
                f"<td>{fin:,.2f}</td><td>{m:.2f}%</td></tr>"
            )

        # Строка возвратов в печатной форме
        if self._df_returns is not None and not self._df_returns.empty:
            ret_exp    = self._df_returns["_reverse_logistics_cost"].sum()
            ret_no_vat = self._df_returns["Поступление от ОЗОН"].sum()
            ret_cost   = self._df_returns["Себестоимость"].sum()
            ret_fin    = self._df_returns["Прибыль"].sum()
            n_ret      = len(self._df_returns)
            ret_vals = [f"Возвраты ({n_ret} шт.)", "",  "", f"{ret_exp:,.2f}",
                        f"{ret_no_vat:,.2f}", f"{ret_cost:,.2f}", f"{ret_fin:,.2f}", ""]
            p_tree.insert("", "end", values=ret_vals, tags=("ret_print",))
            p_tree.tag_configure("ret_print", font=("", 9, "bold"), background="#fef3c7")
            html_rows.append(
                f"<tr class='ret'><td>Возвраты ({n_ret} шт.)</td><td></td><td></td>"
                f"<td>{ret_exp:,.2f}</td><td>{ret_no_vat:,.2f}</td><td>{ret_cost:,.2f}</td>"
                f"<td>{ret_fin:,.2f}</td><td></td></tr>"
            )
            sum_exp    += ret_exp
            sum_no_vat += ret_no_vat
            sum_cost   += ret_cost
            sum_fin    += ret_fin

        total_margin = (sum_no_vat / sum_cost * 100 - 100) if sum_cost > 0 else 0.0
        total_vals = ["ИТОГО ПО ВСЕМ ТОВАРАМ:", str(sum_qty),
                      f"{sum_rev:,.2f}", f"{sum_exp:,.2f}", f"{sum_no_vat:,.2f}",
                      f"{sum_cost:,.2f}", f"{sum_fin:,.2f}", f"{total_margin:.2f}%"]
        p_tree.insert("", "end", values=total_vals, tags=("total_print",))
        p_tree.tag_configure("total_print", font=("", 10, "bold"), background="#dcdde1")

        def sys_print():
            import tempfile, platform, subprocess
            th_elements = "".join([f"<th>{col}</th>" for col in required_cols])
            html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Печать отчёта Ozon</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:20px}}
  h2{{text-align:center;margin-bottom:20px}}
  table{{width:100%;border-collapse:collapse;margin-top:10px;font-size:12px}}
  th,td{{border:1px solid #111;padding:6px 8px;text-align:left}}
  th{{background-color:#f2f2f2}}
  td:not(:first-child),th:not(:first-child){{text-align:right}}
  .bold{{font-weight:bold;background-color:#eaeaea}}
  .ret{{background-color:#fef3c7;font-weight:bold}}
  @media print{{button{{display:none}}}}
</style></head><body>
<h2>Отчёт по начислениям Ozon</h2>
<table><thead><tr>{th_elements}</tr></thead><tbody>
{"".join(html_rows)}
<tr class="bold"><td>ИТОГО ПО ВСЕМ ТОВАРАМ:</td><td>{sum_qty}</td><td>{sum_rev:,.2f}</td>
<td>{sum_exp:,.2f}</td><td>{sum_no_vat:,.2f}</td><td>{sum_cost:,.2f}</td>
<td>{sum_fin:,.2f}</td><td>{total_margin:.2f}%</td></tr>
</tbody></table>
<script>window.onload=function(){{window.print()}}</script>
</body></html>"""
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
                f.write(html_content)
                temp_path = f.name
            current_os = platform.system()
            if current_os == "Darwin":
                subprocess.run(["open", temp_path])
            elif current_os == "Windows":
                os.startfile(temp_path)
            else:
                subprocess.run(["xdg-open", temp_path])

        create_button(ptb, text="🖨️ Отправить на печать", command=sys_print,
                      width=22, pady=4, bg="#2ecc71", fg="white").pack(side="left")
        create_button(ptb, text="Закрыть", command=print_window.destroy,
                      width=12, pady=4).pack(side="right")
        ttk.Label(print_window,
                  text="Печатный вид документа (включает возвраты в итоговую строку)",
                  font=("", 10, "italic"), foreground="gray").pack(anchor="w", padx=10, pady=(0, 5))


# ══════════════════════════════════════════════════════════════════════════════
# ВКЛАДКА ТОВАРОВ
# ══════════════════════════════════════════════════════════════════════════════

class GoodsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._df_full: pd.DataFrame | None = None
        self._sort_col: str | None = None
        self._sort_asc: bool = True
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        tb = ttk.Frame(self)
        tb.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        create_button(tb, text="Экспорт CSV", command=self._export_csv,
                      width=12, padx=5, pady=2).pack(side="left", padx=2)
        ttk.Label(tb, text="Фильтр:").pack(side="left", padx=(10, 2))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        ttk.Entry(tb, textvariable=self._search_var, width=28).pack(side="left")
        self._status = tk.StringVar(value="")
        ttk.Label(tb, textvariable=self._status, foreground="gray").pack(side="right", padx=6)

        frame = ttk.Frame(self)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self._tree = ttk.Treeview(frame, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

    def load(self, df: pd.DataFrame):
        self._df_full = df
        self._render(df)

    def _render(self, df: pd.DataFrame):
        tree = self._tree
        tree.delete(*tree.get_children())
        cols = list(df.columns)
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c, command=lambda _c=c: self._sort(_c))
        for _, row in df.iterrows():
            vals = [("" if pd.isna(row[c]) else str(row[c])) for c in cols]
            tree.insert("", "end", values=vals)
        _autofit_tree_columns(tree, left_cols=LEFT_COLS, max_w=400)
        self._status.set(f"{len(df)} строк")

    def _sort(self, col: str):
        if self._df_full is None:
            return
        asc = True if self._sort_col != col else not self._sort_asc
        df = self._df_full.copy()
        try:
            df = df.sort_values(col, ascending=asc)
        except TypeError:
            df = df.sort_values(col, ascending=asc, key=lambda x: x.astype(str))
        self._sort_col = col
        self._sort_asc = asc
        self._render(df)

    def _filter(self):
        if self._df_full is None:
            return
        q = self._search_var.get().strip().lower()
        if not q:
            self._render(self._df_full)
            return
        mask = self._df_full.apply(
            lambda r: r.astype(str).str.lower().str.contains(q).any(), axis=1)
        self._render(self._df_full[mask])

    def _export_csv(self):
        if self._df_full is None:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv")],
                                         initialfile="goods.csv")
        if p:
            self._df_full.to_csv(p, index=False, encoding="utf-8-sig")
            messagebox.showinfo("Экспорт", f"Сохранено: {p}")


# ══════════════════════════════════════════════════════════════════════════════
# ВКЛАДКА НАСТРОЙКИ СЕБЕСТОИМОСТИ
# ══════════════════════════════════════════════════════════════════════════════

class CostsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self._reload_data()

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        form = ttk.LabelFrame(self, text="Управление базой", padding=10)
        form.grid(row=0, column=0, sticky="nsw", padx=6, pady=6)

        create_button(form, text="📥   Импорт из Excel / CSV", command=self._import_from_file,
                      width=25, pady=6, bg="#2ecc71", fg="white").pack(anchor="w", pady=(5, 20))
        ttk.Separator(form, orient="horizontal").pack(fill="x", pady=(0, 15))

        ttk.Label(form, text="Артикул или SKU:").pack(anchor="w", pady=(0, 2))
        self._sku_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._sku_var, width=25).pack(anchor="w", pady=(0, 10))

        ttk.Label(form, text="Себестоимость (руб):").pack(anchor="w", pady=(0, 2))
        self._cost_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._cost_var, width=25).pack(anchor="w", pady=(0, 15))

        create_button(form, text="Сохранить", command=self._save_entry,
                      width=25, pady=4, bg="#3498db", fg="white").pack(anchor="w", pady=2)
        create_button(form, text="Удалить выбранное", command=self._delete_entry,
                      width=25, pady=4, bg="#e74c3c", fg="white").pack(anchor="w", pady=10)

        table_frame = ttk.LabelFrame(self, text="Текущая база данных себестоимости", padding=6)
        table_frame.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(table_frame, columns=("sku", "cost"), show="headings", selectmode="browse")
        self._tree.heading("sku",  text="Артикул / SKU")
        self._tree.heading("cost", text="Себестоимость, руб.")
        self._tree.column("sku",  width=250, anchor="w")
        self._tree.column("cost", width=150, anchor="e")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

    def _reload_data(self):
        self._tree.delete(*self._tree.get_children())
        for sku, cost in sorted(load_costs().items()):
            self._tree.insert("", "end", iid=sku, values=(sku, f"{cost:,.2f}"))

    def _on_select(self, _event):
        sel = self._tree.selection()
        if sel:
            sku = sel[0]
            db = load_costs()
            if sku in db:
                self._sku_var.set(sku)
                self._cost_var.set(str(db[sku]))

    def _save_entry(self):
        sku = self._sku_var.get().strip()
        cost_str = self._cost_var.get().strip().replace(" ", "").replace(",", ".")
        if not sku:
            messagebox.showwarning("Внимание", "Введите артикул или SKU")
            return
        try:
            cost = float(cost_str)
            if cost < 0: raise ValueError
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректную цену")
            return
        db = load_costs()
        db[sku] = cost
        save_costs(db)
        self._sku_var.set("")
        self._cost_var.set("")
        self._reload_data()

    def _delete_entry(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Выберите товар для удаления")
            return
        sku = sel[0]
        if messagebox.askyesno("Удаление", f"Удалить себестоимость для {sku}?"):
            db = load_costs()
            if sku in db:
                del db[sku]
                save_costs(db)
                self._sku_var.set("")
                self._cost_var.set("")
                self._reload_data()

    def _import_from_file(self):
        path = filedialog.askopenfilename(
            title="Выбрать файл себестоимости",
            filetypes=[("Excel/CSV файлы", "*.xlsx *.xls *.csv"), ("Все файлы", "*.*")]
        )
        if not path:
            return
        try:
            df = pd.read_csv(path, dtype=str) if path.endswith(".csv") else pd.read_excel(path, dtype=str)
            if df.empty:
                raise ValueError("Файл пуст")
            df.columns = [str(c).strip().lower() for c in df.columns]

            # Detect dual-SKU format (SKU OZON + SKU Яндекс + Цена)
            ozon_col = next((c for c in df.columns if "ozon" in c), None)
            ym_col   = next((c for c in df.columns if "яндекс" in c), None)
            cost_col = next((c for c in df.columns if any(x in c for x in
                             ["себестоимость", "цена", "cost", "price"])), None)

            # Fallback for single-column format
            if ozon_col is None and ym_col is None:
                ozon_col = next((c for c in df.columns if any(x in c for x in
                                 ["sku", "артикул", "id"])), df.columns[0])
            if cost_col is None:
                cost_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

            sku_cols = [c for c in [ozon_col, ym_col] if c is not None]
            db = load_costs()
            count = 0
            for _, row in df.iterrows():
                cost_str = (str(row.get(cost_col, "nan")).strip()
                            .replace("₽", "").replace("\xa0", "")
                            .replace(" ", "").replace(",", "."))
                try:
                    cost_val = float(cost_str)
                except ValueError:
                    continue
                for col in sku_cols:
                    val = row.get(col)
                    if pd.isna(val):
                        continue
                    sku_val = str(val).strip()
                    if not sku_val or sku_val.lower() == "nan":
                        continue
                    db[sku_val] = cost_val
                    count += 1
            save_costs(db)
            self._reload_data()
            messagebox.showinfo("Успех", f"Успешно импортировано артикулов: {count}")
        except Exception as e:
            messagebox.showerror("Ошибка импорта", f"Не удалось прочитать файл:\n{e}")


# ══════════════════════════════════════════════════════════════════════════════
# ВКЛАДКА ЯНДЕКС МАРКЕТА
# ══════════════════════════════════════════════════════════════════════════════

class YandexMarketTab(ttk.Frame):
    """Аналитика Яндекс Маркета — KPI, графики, сводка по SKU, рекомендации."""

    def __init__(self, parent):
        super().__init__(parent)
        self._df_raw:         pd.DataFrame | None = None
        self._last_df:        pd.DataFrame | None = None
        self._top_metric      = "Прибыль"
        self._kpi_val_labels: dict = {}
        self._metric_btns:    dict = {}
        self._chart_main_axes = []
        self._chart_cid       = None
        self._fig             = None
        self._canvas          = None
        self._insights_panel  = None
        self._search_var      = tk.StringVar()
        self._count_var       = tk.StringVar(value="")
        self._tree            = None
        self._sort_col        = None
        self._sort_asc        = True
        self._expanded_skus: set = set()
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main_nb = ttk.Notebook(self)
        main_nb.grid(row=0, column=0, sticky="nsew")

        # ── Вкладка «Сводка» ────────────────────────────────────────────────
        summary_frame = ttk.Frame(main_nb)
        main_nb.add(summary_frame, text="📋  Сводка")
        summary_frame.columnconfigure(0, weight=1)
        summary_frame.rowconfigure(1, weight=1)

        tb = tk.Frame(summary_frame, bg=COLORS["bg"], height=40)
        tb.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        FlatButton(tb, text="📥  Экспорт CSV", command=self._export_csv,
                   bg=COLORS["card"], fg=COLORS["text"], font=("", 9),
                   padx=10, pady=4, cursor="hand2").pack(side="left", padx=4)
        tk.Label(tb, text="🔍", bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=("", 9)).pack(side="left", padx=(12, 2))
        ttk.Entry(tb, textvariable=self._search_var, width=22).pack(side="left")
        self._search_var.trace_add("write", lambda *_: self._render_summary())
        tk.Label(tb, textvariable=self._count_var, bg=COLORS["bg"],
                 fg=COLORS["text_muted"], font=("", 9)).pack(side="right", padx=8)

        tree_f = tk.Frame(summary_frame, bg=COLORS["card"])
        tree_f.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        tree_f.columnconfigure(0, weight=1)
        tree_f.rowconfigure(0, weight=1)

        COLS = ["SKU", "Название товара", "Продано", "Выручка",
                "Расходы ЯМ", "Поступление", "Себестоимость", "Прибыль", "Рентабельность"]
        self._tree = ttk.Treeview(tree_f, columns=COLS, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(tree_f, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_f, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        widths = [140, 260, 70, 110, 110, 110, 110, 100, 110]
        for col, w in zip(COLS, widths):
            self._tree.heading(col, text=col, command=lambda c=col: self._sort(c))
            self._tree.column(col, width=w,
                              anchor="w" if col in ("SKU", "Название товара") else "e",
                              minwidth=60)
        self._tree.tag_configure("pos",       foreground=COLORS["success"])
        self._tree.tag_configure("neg",       foreground=COLORS["danger"])
        self._tree.tag_configure("row_alt",   background=COLORS["row_alt"])
        self._tree.tag_configure("sku_group", font=("", 10, "bold"), background=COLORS["sku_bg"])
        self._tree.tag_configure("sku_neg",   font=("", 10, "bold"), background=COLORS["sku_bg"],
                                              foreground=COLORS["neg"])
        self._tree.tag_configure("child",     foreground=COLORS["text"])
        self._tree.tag_configure("child_neg", foreground=COLORS["neg"])
        self._tree.tag_configure("total",     font=("", 10, "bold"), background=COLORS["total_bg"])
        self._tree.bind("<ButtonRelease-1>", self._on_click)

        # ── Вкладка «Графики» ───────────────────────────────────────────────
        chart_frame = ttk.Frame(main_nb)
        main_nb.add(chart_frame, text="📊  Графики")
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(2, weight=1)

        kpi_frame = tk.Frame(chart_frame, bg=COLORS["bg"])
        kpi_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 0))
        self._build_kpi_cards(kpi_frame)

        btn_bar = tk.Frame(chart_frame, bg=COLORS["bg"])
        btn_bar.grid(row=1, column=0, sticky="w", padx=8, pady=2)
        self._build_metric_buttons(btn_bar)

        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        self._fig = Figure(figsize=(14, 7), dpi=90)
        self._fig.patch.set_facecolor(COLORS["bg"])
        self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
        self._canvas.get_tk_widget().grid(row=2, column=0, sticky="nsew")

        # ── Вкладка «Рекомендации» ───────────────────────────────────────────
        insights_frame = ttk.Frame(main_nb)
        main_nb.add(insights_frame, text="💡  Рекомендации")
        insights_frame.columnconfigure(0, weight=1)
        insights_frame.rowconfigure(0, weight=1)
        self._insights_panel = InsightsPanel(insights_frame)
        self._insights_panel.grid(row=0, column=0, sticky="nsew")

    def load(self, df_raw: pd.DataFrame):
        self._df_raw = df_raw
        self._render_summary()
        self._render_charts(df_raw)

    def _render_summary(self):
        if self._df_raw is None or self._df_raw.empty:
            return
        q = self._search_var.get().strip().lower()
        df = self._df_raw.copy()
        if q:
            mask = df.apply(lambda r: r.astype(str).str.lower().str.contains(q).any(), axis=1)
            df = df[mask]

        grp = df.groupby("SKU", sort=False).agg(
            name  =("Название товара",     "first"),
            qty   =("Количество",          "sum"),
            rev   =("Выручка",             "sum"),
            fees  =("Расходы",             "sum"),
            net   =("Поступление от ОЗОН", "sum"),
            cost  =("Себестоимость",       "sum"),
            profit=("Прибыль",             "sum"),
        ).reset_index()
        grp["margin"] = grp.apply(
            lambda r: (r["net"] / r["cost"] * 100 - 100) if r["cost"] > 0 else 0.0, axis=1
        )

        sort_map = {
            "SKU": "SKU", "Название товара": "name", "Продано": "qty",
            "Выручка": "rev", "Расходы ЯМ": "fees", "Поступление": "net",
            "Себестоимость": "cost", "Прибыль": "profit", "Рентабельность": "margin",
        }
        if self._sort_col and self._sort_col in sort_map:
            key = sort_map[self._sort_col]
            if key in grp.columns:
                try:
                    grp = grp.sort_values(key, ascending=self._sort_asc)
                except TypeError:
                    grp = grp.sort_values(key, ascending=self._sort_asc,
                                          key=lambda x: x.astype(str))

        self._tree.delete(*self._tree.get_children())

        grand_rev = grand_fees = grand_net = grand_cost = grand_profit = 0.0
        grand_qty = 0

        for _, row in grp.iterrows():
            sku    = row["SKU"]
            profit = row["profit"]
            expanded = sku in self._expanded_skus
            prefix   = "▼  " if expanded else "▶  "
            tag      = "sku_neg" if profit < 0 else "sku_group"

            self._tree.insert("", "end", iid=f"group_{sku}", tags=(tag,), values=(
                f"{prefix}{sku}",
                row["name"],
                f"{int(row['qty']):,}".replace(",", " "),
                f"{row['rev']:,.0f} ₽".replace(",", " "),
                f"{row['fees']:,.0f} ₽".replace(",", " "),
                f"{row['net']:,.0f} ₽".replace(",", " "),
                f"{row['cost']:,.0f} ₽".replace(",", " "),
                f"{profit:,.0f} ₽".replace(",", " "),
                f"{row['margin']:.1f}%",
            ))

            grand_qty    += int(row["qty"])
            grand_rev    += row["rev"]
            grand_fees   += row["fees"]
            grand_net    += row["net"]
            grand_cost   += row["cost"]
            grand_profit += profit

            if expanded:
                sku_rows = df[df["SKU"] == sku]
                for _, r in sku_rows.iterrows():
                    r_profit = r["Прибыль"]
                    r_margin = (r["Поступление от ОЗОН"] / r["Себестоимость"] * 100 - 100) \
                               if r["Себестоимость"] > 0 else 0.0
                    date_str = ""
                    if "Дата начисления" in r.index and pd.notna(r["Дата начисления"]):
                        try:
                            date_str = pd.Timestamp(r["Дата начисления"]).strftime("%d.%m.%Y")
                        except Exception:
                            date_str = str(r["Дата начисления"])
                    order_num = str(r.get("Номер заказа", "")).strip() \
                                if "Номер заказа" in r.index else ""
                    label = f"      ↳ {order_num}" if order_num else f"      ↳ {date_str}"
                    c_tag = "child_neg" if r_profit < 0 else "child"
                    self._tree.insert("", "end",
                                      iid=f"order_{sku}_{r.name}",
                                      tags=(c_tag,), values=(
                        label,
                        date_str,
                        "1",
                        f"{r['Выручка']:,.0f} ₽".replace(",", " "),
                        f"{r['Расходы']:,.0f} ₽".replace(",", " "),
                        f"{r['Поступление от ОЗОН']:,.0f} ₽".replace(",", " "),
                        f"{r['Себестоимость']:,.0f} ₽".replace(",", " "),
                        f"{r_profit:,.0f} ₽".replace(",", " "),
                        f"{r_margin:.1f}%",
                    ))

        grand_margin = (grand_net / grand_cost * 100 - 100) if grand_cost > 0 else 0.0
        self._tree.insert("", "end", iid="total_row", tags=("total",), values=(
            "ИТОГО",
            "",
            f"{grand_qty:,}".replace(",", " "),
            f"{grand_rev:,.0f} ₽".replace(",", " "),
            f"{grand_fees:,.0f} ₽".replace(",", " "),
            f"{grand_net:,.0f} ₽".replace(",", " "),
            f"{grand_cost:,.0f} ₽".replace(",", " "),
            f"{grand_profit:,.0f} ₽".replace(",", " "),
            f"{grand_margin:.1f}%",
        ))

        self._count_var.set(f"Товаров: {len(grp)}")

    def _sort(self, col: str):
        self._sort_asc = True if self._sort_col != col else not self._sort_asc
        self._sort_col = col
        self._render_summary()

    def _on_click(self, _event):
        item_id = self._tree.focus()
        if not item_id or item_id in ("total_row",):
            return
        if item_id.startswith("group_"):
            sku = item_id[len("group_"):]
            if sku in self._expanded_skus:
                self._expanded_skus.discard(sku)
            else:
                self._expanded_skus.add(sku)
            self._render_summary()

    def _build_kpi_cards(self, parent: tk.Frame):
        KPI_DEFS = [
            ("Выручка",        "выручка",        "₽",   False),
            ("Чистая прибыль", "прибыль",        "₽",   True),
            ("Рентабельность", "рентабельность", "%",   True),
            ("Заказов, шт.",   "количество",     "шт.", False),
        ]
        for i, (title, key, unit, colored) in enumerate(KPI_DEFS):
            card = tk.Frame(parent, bg=COLORS["card"],
                            highlightbackground=COLORS["border"],
                            highlightthickness=1)
            card.grid(row=0, column=i, padx=4, pady=2, sticky="ew")
            parent.columnconfigure(i, weight=1)
            tk.Label(card, text=title, bg=COLORS["card"],
                     fg=COLORS["text_muted"], font=("", 9)).pack(anchor="w", padx=8, pady=(5, 0))
            var = tk.StringVar(value="—")
            lbl = tk.Label(card, textvariable=var, bg=COLORS["card"],
                           fg=COLORS["text"], font=("", 16, "bold"))
            lbl.pack(anchor="w", padx=8, pady=(0, 5))
            self._kpi_val_labels[key] = (var, lbl, unit, colored)

    def _build_metric_buttons(self, parent: tk.Frame):
        tk.Label(parent, text="Топ товаров:", bg=COLORS["bg"],
                 fg=COLORS["text_muted"], font=("", 8)).pack(side="left", padx=(0, 4))
        for label in ["Прибыль", "Выручка", "Продано"]:
            btn = FlatButton(
                parent, text=label, font=("", 8),
                padx=8, pady=3, cursor="hand2",
                command=lambda l=label: self._set_top_metric(l)
            )
            btn.pack(side="left", padx=1)
            self._metric_btns[label] = btn
        self._update_metric_btn_styles()

    def _update_metric_btn_styles(self):
        for label, btn in self._metric_btns.items():
            if label == self._top_metric:
                btn.configure(bg=COLORS["primary"], fg="white")
            else:
                btn.configure(bg=COLORS["card"], fg=COLORS["text"])

    def _set_top_metric(self, metric: str):
        self._top_metric = metric
        self._update_metric_btn_styles()
        if self._last_df is not None:
            self._render_charts(self._last_df)

    def _update_kpi_cards(self, df: pd.DataFrame):
        total_rev  = float(df["Выручка"].sum())         if "Выручка"        in df.columns else 0.0
        total_prf  = float(df["Прибыль"].sum())         if "Прибыль"        in df.columns else 0.0
        total_qty  = int(df["Количество"].sum())        if "Количество"     in df.columns else 0
        avg_margin = float(df["Рентабельность"].mean()) if "Рентабельность" in df.columns else 0.0

        def _fmt(val, key, unit):
            if key == "количество":
                return f"{int(val):,} {unit}".replace(",", " ")
            if key == "рентабельность":
                return f"{val:.1f}{unit}"
            if abs(val) >= 1_000_000:
                return f"{val/1_000_000:.1f}M {unit}"
            if abs(val) >= 1_000:
                return f"{val/1_000:.0f}k {unit}"
            return f"{val:.0f} {unit}"

        data = {"выручка": total_rev, "прибыль": total_prf,
                "рентабельность": avg_margin, "количество": total_qty}
        for key, (var, lbl, unit, colored) in self._kpi_val_labels.items():
            val = data.get(key, 0.0)
            var.set(_fmt(val, key, unit))
            if colored:
                lbl.configure(fg=COLORS["success"] if float(val) >= 0 else COLORS["danger"])

    def _render_charts(self, df: pd.DataFrame):
        if df is None or df.empty:
            return
        self._last_df = df
        self._update_kpi_cards(df)
        self._fig.clear()
        self._fig.patch.set_facecolor(COLORS["bg"])

        gs  = self._fig.add_gridspec(2, 2, hspace=0.5, wspace=0.35)
        ax1 = self._fig.add_subplot(gs[0, 0])
        ax2 = self._fig.add_subplot(gs[0, 1])
        ax3 = self._fig.add_subplot(gs[1, 0])
        ax4 = self._fig.add_subplot(gs[1, 1])

        _draw_analytics_chart(ax1, 0, df, True, self._top_metric)
        _draw_analytics_chart(ax2, 1, df, True, self._top_metric)
        _draw_analytics_chart(ax3, 2, df, True, self._top_metric)
        _draw_analytics_chart(ax4, 3, df, True, self._top_metric)

        self._chart_main_axes = [ax1, ax2, ax3, ax4]
        if self._chart_cid is not None:
            self._canvas.mpl_disconnect(self._chart_cid)
        self._chart_cid = self._canvas.mpl_connect("button_press_event", self._on_chart_click)
        self._fig.tight_layout(pad=1.5)
        self._canvas.draw()

        if self._insights_panel is not None:
            self._insights_panel.refresh(df)

    def _on_chart_click(self, event):
        if event.inaxes is None or self._last_df is None:
            return
        for i, ax in enumerate(self._chart_main_axes):
            if event.inaxes is ax:
                self._open_chart_fullscreen(i)
                return

    def _open_chart_fullscreen(self, idx: int):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        top = tk.Toplevel(self)
        titles = ["Топ товаров", "Динамика", "Доля в прибыли", "Матрица ассортимента"]
        top.title(titles[idx])
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        top.geometry(f"{sw}x{sh}+0+0")
        try:
            top.state("zoomed")
        except Exception:
            top.attributes("-fullscreen", True)

        top.columnconfigure(0, weight=1)
        top.rowconfigure(1, weight=1)

        bar = tk.Frame(top, bg=COLORS["sidebar"], height=36)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        tk.Label(bar, text=titles[idx], bg=COLORS["sidebar"], fg="white",
                 font=("", 11, "bold")).grid(row=0, column=0, padx=12, pady=6, sticky="w")
        FlatButton(bar, text="✕  Закрыть", command=top.destroy,
                   bg=COLORS["sidebar"], fg="white",
                   font=("", 9), padx=10, pady=2, cursor="hand2").grid(
                       row=0, column=2, padx=8, pady=4, sticky="e")

        dpi   = 96
        fig_w = sw / dpi
        fig_h = (sh - 44) / dpi
        fig_full = Figure(figsize=(fig_w, fig_h), dpi=dpi)
        fig_full.patch.set_facecolor(COLORS["bg"])
        canvas_full = FigureCanvasTkAgg(fig_full, master=top)
        canvas_full.get_tk_widget().grid(row=1, column=0, sticky="nsew")

        ax_full = fig_full.add_subplot(1, 1, 1)
        _draw_analytics_chart(ax_full, idx, self._last_df,
                              compact=False, top_metric=self._top_metric)
        fig_full.tight_layout(pad=2.5)
        canvas_full.draw()
        canvas_full.mpl_connect("button_press_event", lambda *_: top.destroy())

    def _export_csv(self):
        if self._df_raw is None:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv",
                                          filetypes=[("CSV", "*.csv")],
                                          initialfile="yandex_market.csv")
        if p:
            self._df_raw.to_csv(p, index=False, encoding="utf-8-sig")
            messagebox.showinfo("Экспорт", f"Сохранено: {p}")


# ══════════════════════════════════════════════════════════════════════════════
# СТАРТОВЫЙ ЭКРАН
# ══════════════════════════════════════════════════════════════════════════════

class ReportTypeSelector(ttk.Frame):

    def __init__(self, parent, on_select: callable):
        super().__init__(parent)
        self._on_select = on_select
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content = tk.Frame(self, bg=COLORS["bg"])
        content.grid(row=0, column=0, sticky="nsew")
        center = tk.Frame(content, bg=COLORS["bg"])
        center.place(relx=0.5, rely=0.45, anchor="center")

        # Logo above heading
        _logo_path = BASE_DIR / "Основной логотип (пнг).png"
        if _PIL_AVAILABLE and _logo_path.exists():
            _pil = Image.open(_logo_path).convert("RGBA")
            _pil.thumbnail((300, 80), Image.LANCZOS)
            _logo_photo = ImageTk.PhotoImage(_pil)
            _logo_lbl = tk.Label(center, image=_logo_photo,
                                 bg=COLORS["bg"], bd=0, highlightthickness=0)
            _logo_lbl.image = _logo_photo  # prevent GC
            _logo_lbl.pack(pady=(0, 24))
        elif _logo_path.exists():
            _logo_photo = tk.PhotoImage(file=str(_logo_path))
            _logo_lbl = tk.Label(center, image=_logo_photo,
                                 bg=COLORS["bg"], bd=0, highlightthickness=0)
            _logo_lbl.image = _logo_photo
            _logo_lbl.pack(pady=(0, 24))

        tk.Label(center, text="Аналитика маркетплейсов",
                 font=("", 20, "bold"), bg=COLORS["bg"], fg=COLORS["text"]).pack(pady=(0, 6))
        tk.Label(center, text="для продавцов на Ozon и Яндекс Маркете",
                 font=("", 11), bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(pady=(0, 36))

        ym_wrap = tk.Frame(center, bg=COLORS["bg"])
        ym_wrap.pack(pady=(6, 0), fill="x")
        create_button(ym_wrap, text="     Яндекс Маркет  ",
                      command=lambda: self._pick("ym"),
                      width=34, pady=13, font=("", 12, "bold"),
                      bg=COLORS["primary"], fg="white").pack(fill="x")
        tk.Label(ym_wrap,
                 text="Финансы → Финансовые отчёты → О платежах за период",
                 font=("", 9), bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(pady=(3, 0))

        ozon_wrap = tk.Frame(center, bg=COLORS["bg"])
        ozon_wrap.pack(pady=(10, 0), fill="x")
        create_button(ozon_wrap, text="     OZON  ",
                      command=lambda: self._pick("accruals"),
                      width=34, pady=13, font=("", 12, "bold"),
                      bg=COLORS["sidebar"], fg="white").pack(fill="x")
        tk.Label(ozon_wrap,
                 text="Финансы → Экономика магазина → Скачать отчёт по начислениям",
                 font=("", 9), bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(pady=(3, 0))

        tk.Frame(center, bg=COLORS["border"], height=1).pack(fill="x", pady=20)

        create_button(center, text="  ⚙️   Настройка себестоимости  ",
                      command=lambda: self._pick("costs"),
                      width=34, pady=10, font=("", 11),
                      bg=COLORS["border"], fg=COLORS["text"]).pack(pady=4, fill="x")

        if _CALCULATOR_AVAILABLE:
            calc_wrap = tk.Frame(center, bg=COLORS["bg"])
            calc_wrap.pack(pady=(6, 0), fill="x")
            create_button(calc_wrap, text="  💰   Расчет цен ОЗОН  ",
                          command=lambda: self._pick("calculator"),
                          width=34, pady=10, font=("", 11, "bold"),
                          bg="#8B5CF6", fg="white").pack(fill="x")
            tk.Label(calc_wrap,
                     text="Таблица для расчета цен на основе желаемой рентабельности",
                     font=("", 9), bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(pady=(3, 0))

    def _pick(self, report_type: str):
        if report_type in ("costs", "calculator"):
            self._on_select(report_type, "")
            return
        filetypes = [("Excel 2007+", "*.xlsx"), ("Excel 97-2003", "*.xls"), ("Все файлы", "*.*")]
        path = filedialog.askopenfilename(title="Открыть отчёт", filetypes=filetypes)
        if path:
            self._on_select(report_type, path)


# ══════════════════════════════════════════════════════════════════════════════
# ГЛАВНОЕ ОКНО
# ══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Аналитика Ozon")
        self.geometry("1400x800")
        self.minsize(900, 500)
        self.configure(bg=COLORS["bg"])
        setup_styles()
        self._show_selector()

    def _show_selector(self):
        self._clear()
        ReportTypeSelector(self, on_select=self._on_selected).pack(fill="both", expand=True)

    def _on_selected(self, report_type: str, path: str):
        self._clear()

        header = tk.Frame(self, bg=COLORS["sidebar"], height=46)
        header.pack(fill="x")
        header.pack_propagate(False)
        create_button(header, text="← Назад", command=self._show_selector,
                      bg=COLORS["sidebar"], fg="#94a3b8",
                      font=("", 10), pady=0, padx=14).pack(side="left", pady=10)

        if report_type == "costs":
            tk.Label(header, text="Редактирование себестоимости", font=("", 10, "bold"),
                     bg=COLORS["sidebar"], fg="#ffffff").pack(side="left", padx=8, pady=10)
        elif report_type == "calculator":
            tk.Label(header, text="💰 Массовый расчет цен ОЗОН (Дальний кластер)", font=("", 10, "bold"),
                     bg=COLORS["sidebar"], fg="#ffffff").pack(side="left", padx=8, pady=10)
        else:
            label = {"ym": "Яндекс Маркет", "accruals": "По начислениям (ОЗОН)"}.get(
                report_type, report_type)
            fname = path.replace("\\", "/").split("/")[-1]
            tk.Label(header, text=f"{label}  ·  {fname}", font=("", 10),
                     bg=COLORS["sidebar"], fg="#e2e8f0").pack(side="left", padx=8, pady=10)
            self._loading_label = tk.Label(header, text="⏳ Загрузка...",
                                           bg=COLORS["sidebar"], fg="#94a3b8")
            self._loading_label.pack(side="right", padx=12, pady=10)

        self._content_frame = ttk.Frame(self)
        self._content_frame.pack(fill="both", expand=True, padx=6, pady=6)
        self._content_frame.columnconfigure(0, weight=1)
        self._content_frame.rowconfigure(0, weight=1)

        if report_type == "costs":
            CostsTab(self._content_frame).grid(row=0, column=0, sticky="nsew")
        elif report_type == "calculator":
            if _CALCULATOR_AVAILABLE:
                calc = MassCalc(self._content_frame)
                calc.pack(fill="both", expand=True)
            else:
                tk.Label(self._content_frame, text="❌ Калькулятор недоступен",
                         font=("", 12), fg=COLORS["danger"]).pack(expand=True)
        else:
            import threading
            threading.Thread(target=self._load_worker, args=(report_type, path), daemon=True).start()

    def _load_worker(self, report_type: str, path: str):
        try:
            if report_type == "accruals":
                df_raw = parse_accrual_excel(path)
                self.after(0, lambda: self._show_accruals(df_raw))
            elif report_type == "ym":
                df_raw = parse_ym_orders_excel(path)
                df     = build_ym_summary(df_raw)
                self.after(0, lambda: self._show_ym(df))
            else:
                df = parse_goods_excel(path)
                self.after(0, lambda: self._show_goods(df))
        except Exception as e:
            self.after(0, lambda error=e: self._on_load_error(str(error)))

    def _show_accruals(self, df_raw: pd.DataFrame):
        if hasattr(self, "_loading_label") and self._loading_label.winfo_exists():
            self._loading_label.config(text="")
        tab = AccrualTab(self._content_frame)
        tab.grid(row=0, column=0, sticky="nsew")
        tab.load(df_raw)

    def _show_ym(self, df: pd.DataFrame):
        if hasattr(self, "_loading_label") and self._loading_label.winfo_exists():
            self._loading_label.config(text="")
        tab = YandexMarketTab(self._content_frame)
        tab.grid(row=0, column=0, sticky="nsew")
        tab.load(df)

    def _show_goods(self, df: pd.DataFrame):
        if hasattr(self, "_loading_label") and self._loading_label.winfo_exists():
            self._loading_label.config(text="")
        tab = GoodsTab(self._content_frame)
        tab.grid(row=0, column=0, sticky="nsew")
        tab.load(df)

    def _on_load_error(self, msg: str):
        messagebox.showerror("Ошибка загрузки", msg)
        self._show_selector()

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()


if __name__ == "__main__":
    App().mainloop()
