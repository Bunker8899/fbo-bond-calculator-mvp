"""
Kalkulator Obligacji Skarbowych – main.py
Senior-grade NiceGUI dashboard: reactive sidebar + Plotly chart + amortisation table.
"""

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import plotly.graph_objects as go
from nicegui import ui

# ══════════════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════════════
DATA_FILE = Path(__file__).parent / "bonds_data.json"
with DATA_FILE.open(encoding="utf-8") as f:
    raw = json.load(f)

bonds_map: dict[str, dict] = {b["symbol"]: b for b in raw["bonds"]}
bond_symbols: list[str] = list(bonds_map)

# ══════════════════════════════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════════════════════════════
_first = bonds_map[bond_symbols[0]]
state: dict = {
    "amount":   10_000.0,
    "symbol":   bond_symbols[0],
    "horizon":  _first["duration_years"],
    "inflation": 2.0,
}
_syncing = False
refs: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# FINANCIAL MATH
# ══════════════════════════════════════════════════════════════════════════════
def fin_round(v: float) -> float:
    """Polish Ordynacja podatkowa rounding: ≥0.5 gr rounds UP."""
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _get_rate(bond: dict, year: int, inf_pct: float) -> float:
    if year == 1:
        return bond["first_year_rate"]
    if bond["inflation_linked"]:
        return max(0.0, inf_pct / 100.0) + bond["margin"]
    return bond["first_year_rate"]


def calculate_bond_results(
    amount: float, symbol: str, horizon: int, inf_pct: float
) -> tuple[list[dict], float]:
    bond = bonds_map[symbol]
    n_bonds = amount / bond["nominal_value"]
    is_early = horizon < bond["duration_years"]
    rows: list[dict] = []

    if bond["capitalization"]:          # TOS / EDO – compound, Belka at end
        capital = amount
        for yr in range(1, horizon + 1):
            rate = _get_rate(bond, yr, inf_pct)
            interest = fin_round(capital * rate)
            capital = fin_round(capital + interest)
            accrued = fin_round(capital - amount)
            if yr < horizon:
                tax, net = 0.0, capital
            elif is_early:
                fee = fin_round(bond["early_redemption_fee"] * n_bonds)
                tax = fin_round(max(0.0, accrued - fee) * 0.19)
                net = fin_round(amount + accrued - fee - tax)
            else:
                tax = fin_round(accrued * 0.19)
                net = fin_round(capital - tax)
            rows.append({"year": yr, "rate_pct": rate, "gross_capital": capital,
                         "interest": interest, "tax": tax, "net_capital": net})
    else:                               # COI – simple interest, annual Belka
        cum_gross = cum_net = 0.0
        for yr in range(1, horizon + 1):
            rate = _get_rate(bond, yr, inf_pct)
            interest = fin_round(amount * rate)
            cum_gross = fin_round(cum_gross + interest)
            if yr < horizon:
                if is_early:
                    tax = 0.0;  cum_net = fin_round(cum_net + interest)
                else:
                    tax = fin_round(interest * 0.19)
                    cum_net = fin_round(cum_net + interest - tax)
            else:
                if is_early:
                    fee = fin_round(bond["early_redemption_fee"] * n_bonds)
                    tax = fin_round(max(0.0, cum_gross - fee) * 0.19)
                    cum_net = fin_round(cum_gross - fee - tax)
                else:
                    tax = fin_round(interest * 0.19)
                    cum_net = fin_round(cum_net + interest - tax)
            rows.append({"year": yr, "rate_pct": rate,
                         "gross_capital": fin_round(amount + cum_gross),
                         "interest": interest, "tax": tax,
                         "net_capital": fin_round(amount + cum_net)})

    return rows, (rows[-1]["net_capital"] if rows else amount)


# ══════════════════════════════════════════════════════════════════════════════
# CHART BUILDER
# ══════════════════════════════════════════════════════════════════════════════
_LAYOUT_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=48, r=16, t=8, b=40),
    font=dict(family="Inter, sans-serif", size=12, color="#475569"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    yaxis=dict(gridcolor="#f1f5f9", zerolinecolor="#e2e8f0"),
    xaxis=dict(gridcolor="#f1f5f9"),
)


def _make_chart(rows: list[dict], bond: dict, amount: float) -> go.Figure:
    years = [r["year"] for r in rows]

    if bond["capitalization"]:
        # ── Stacked Bar: base | net gain | tax cut ────────────────────────────
        base_v   = [amount] * len(rows)
        net_v    = [r["net_capital"] - amount for r in rows]
        tax_v    = [r["tax"] for r in rows]
        hover    = "<b>Rok %{x}</b><br>%{y:,.2f} PLN<extra></extra>"
        fig = go.Figure([
            go.Bar(name="Kapitał bazowy",  x=years, y=base_v,
                   marker_color="#334155", hovertemplate=hover),
            go.Bar(name="Zysk netto",      x=years, y=net_v,
                   marker_color="#22c55e", hovertemplate=hover),
            go.Bar(name="Podatek / Opłata", x=years, y=tax_v,
                   marker_color="#ef4444", hovertemplate=hover),
        ])
        fig.update_layout(barmode="stack", xaxis_title="Rok", yaxis_title="PLN",
                          xaxis=dict(tickmode="array", tickvals=years, gridcolor="#f1f5f9"),
                          **{k: v for k, v in _LAYOUT_BASE.items() if k != "xaxis"})
    else:
        # ── Waterfall: zasilenie + roczne przepływy netto ─────────────────────
        prev = amount
        measures = ["absolute"]
        x_lab    = ["Zasilenie"]
        y_val    = [amount]
        for r in rows:
            delta = fin_round(r["net_capital"] - prev)
            measures.append("relative");  x_lab.append(f"Rok {r['year']}")
            y_val.append(delta);          prev = r["net_capital"]
        measures.append("total");  x_lab.append("Do wypłaty");  y_val.append(0)

        fig = go.Figure(go.Waterfall(
            measure=measures, x=x_lab, y=y_val,
            texttemplate="%{y:,.0f}", textposition="outside",
            connector={"line": {"color": "#cbd5e1", "width": 1, "dash": "dot"}},
            increasing={"marker": {"color": "#22c55e"}},
            decreasing={"marker": {"color": "#ef4444"}},
            totals={"marker": {"color": "#6366f1"}},
            hovertemplate="<b>%{x}</b><br>%{y:,.2f} PLN<extra></extra>",
        ))
        fig.update_layout(showlegend=False, xaxis_title="Okres",
                          yaxis_title="PLN", **_LAYOUT_BASE)

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _pln(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "\u00A0").replace(".", ",")
    return f"{'-' if v < 0 else ''}{s}"

def _horizon_text(n: int) -> str:
    return "1 rok" if n == 1 else (f"{n} lata" if n <= 4 else f"{n} lat")

def _clamp_amount(v) -> int:
    try: v = float(v)
    except (TypeError, ValueError): return int(state["amount"])
    return max(100, min(100_000, round(v / 100) * 100))


# ══════════════════════════════════════════════════════════════════════════════
# REFRESH  (called on every state change)
# ══════════════════════════════════════════════════════════════════════════════
def _refresh() -> None:
    bond = bonds_map[state["symbol"]]
    rows, final_net = calculate_bond_results(
        state["amount"], state["symbol"], state["horizon"], state["inflation"]
    )
    n_bonds   = state["amount"] / bond["nominal_value"]
    is_early  = state["horizon"] < bond["duration_years"]
    gross_cap = rows[-1]["gross_capital"] if rows else state["amount"]
    total_tax = sum(r["tax"] for r in rows)
    fee       = fin_round(bond["early_redemption_fee"] * n_bonds) if is_early else 0.0
    deductions = fin_round(total_tax + fee)
    net_gain  = fin_round(final_net - state["amount"])

    # Annualised real return
    h = max(1, state["horizon"])
    nom_ann = (final_net / state["amount"]) ** (1 / h) - 1
    if bond["inflation_linked"] and state["inflation"] > 0:
        real_ann = (1 + nom_ann) / (1 + state["inflation"] / 100) - 1
        rate_label = f"Real {real_ann * 100:+.2f}% p.a."
    else:
        rate_label = f"Nom. {nom_ann * 100:.2f}% p.a."

    # ── Hero metrics ──────────────────────────────────────────────────────────
    refs["m_gross"].set_text(f"{_pln(gross_cap)} PLN")
    refs["m_deduct"].set_text(f"{_pln(deductions)} PLN")
    refs["m_net"].set_text(f"{_pln(final_net)} PLN")
    refs["m_rate"].set_text(rate_label)

    # ── Chart ─────────────────────────────────────────────────────────────────
    refs["chart"].figure = _make_chart(rows, bond, state["amount"])
    refs["chart"].update()

    # ── Amortization table ────────────────────────────────────────────────────
    refs["result_table"].rows = [
        {"year": r["year"], "rate": f"{r['rate_pct']*100:.2f}%",
         "gross_capital": _pln(r["gross_capital"]), "interest": _pln(r["interest"]),
         "tax": _pln(r["tax"]), "net_capital": _pln(r["net_capital"])}
        for r in rows
    ]
    refs["result_table"].update()


# ══════════════════════════════════════════════════════════════════════════════
# EVENT HANDLERS
# ══════════════════════════════════════════════════════════════════════════════
def _on_amount_number(e) -> None:
    global _syncing
    if _syncing: return
    v = _clamp_amount(e.value);  state["amount"] = v
    _syncing = True
    refs["amount_slider"].value = v;  refs["amount_slider"].update()
    _syncing = False;  _refresh()

def _on_amount_slider(e) -> None:
    global _syncing
    if _syncing: return
    v = _clamp_amount(e.value);  state["amount"] = v
    _syncing = True
    refs["amount_number"].value = v;  refs["amount_number"].update()
    _syncing = False;  _refresh()

def _on_symbol(e) -> None:
    sym = e.value;  state["symbol"] = sym
    bond = bonds_map[sym];  max_h = bond["duration_years"]
    state["horizon"] = max_h
    refs["horizon_slider"].max = max_h
    refs["horizon_slider"].value = max_h;  refs["horizon_slider"].update()
    refs["horizon_label"].set_text(f"Wartość: {_horizon_text(max_h)}")
    refs["inflation_row"].set_visibility(bond["inflation_linked"])
    _refresh()

def _on_horizon(e) -> None:
    v = int(e.value);  state["horizon"] = v
    refs["horizon_label"].set_text(f"Wartość: {_horizon_text(v)}")
    _refresh()

def _on_inflation(e) -> None:
    if e.value is not None: state["inflation"] = float(e.value)
    _refresh()


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ══════════════════════════════════════════════════════════════════════════════
ui.add_head_html("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  body, .nicegui-content { font-family: 'Inter', sans-serif !important; }
  .sb-label { color:#94a3b8; font-size:.68rem; text-transform:uppercase;
              letter-spacing:.09em; margin-bottom:4px; display:block; }
</style>
""")

# ── Header ────────────────────────────────────────────────────────────────────
with ui.header(elevated=True).classes("bg-slate-900 text-white px-6 items-center gap-3"):
    ui.icon("trending_up").classes("text-2xl text-blue-400")
    ui.label("Kalkulator Obligacji Skarbowych").classes("text-lg font-semibold tracking-tight")
    ui.space()
    ui.chip(raw["metadata"]["issue_month"], color="blue-grey-9").classes("text-xs font-mono")

# ── Left Sidebar ──────────────────────────────────────────────────────────────
with ui.left_drawer(fixed=True, elevated=True, bordered=True).style(
    "background:#0f172a; width:272px; padding:20px 16px;"
):
    ui.label("Parametry inwestycji").classes("text-slate-100 text-sm font-semibold tracking-wide mb-5")

    ui.element("span").classes("sb-label").text = "Zasilenie inwestycyjne (PLN)"
    refs["amount_number"] = (
        ui.number(value=10_000, min=100, max=100_000, step=100, format="%.0f",
                  on_change=_on_amount_number)
        .classes("w-full").props("outlined dense dark color=blue-3")
    )
    refs["amount_slider"] = (
        ui.slider(min=100, max=100_000, step=100, value=10_000, on_change=_on_amount_slider)
        .classes("w-full mt-1").props("dark color=blue-4 label")
    )

    ui.separator().style("border-color:#1e293b; margin:14px 0;")

    ui.element("span").classes("sb-label").text = "Instrument"
    refs["symbol_select"] = (
        ui.select(options=bond_symbols, value=bond_symbols[0], on_change=_on_symbol)
        .classes("w-full").props("outlined dense dark color=indigo-3")
    )

    ui.separator().style("border-color:#1e293b; margin:14px 0;")

    ui.element("span").classes("sb-label").text = "Horyzont inwestycji"
    refs["horizon_label"] = ui.label(
        f"Wartość: {_horizon_text(_first['duration_years'])}"
    ).classes("text-slate-300 text-xs font-mono mb-1")
    refs["horizon_slider"] = (
        ui.slider(min=1, max=_first["duration_years"], step=1,
                  value=_first["duration_years"], on_change=_on_horizon)
        .classes("w-full").props("dark color=green-4 label")
    )

    ui.separator().style("border-color:#1e293b; margin:14px 0;")

    inflation_row = ui.column().classes("w-full gap-1")
    with inflation_row:
        ui.element("span").classes("sb-label").text = "Predykcja inflacji (%)"
        refs["inflation_number"] = (
            ui.number(value=2.0, min=0.0, max=20.0, step=0.1, format="%.1f",
                      on_change=_on_inflation)
            .classes("w-full").props("outlined dense dark color=amber-3")
        )
    refs["inflation_row"] = inflation_row
    inflation_row.set_visibility(_first["inflation_linked"])

# ══════════════════════════════════════════════════════════════════════════════
# MAIN WORKSPACE
# ══════════════════════════════════════════════════════════════════════════════
TABLE_COLUMNS = [
    {"name": "year",          "label": "Rok",                  "field": "year",          "align": "center"},
    {"name": "rate",          "label": "Stopa",                "field": "rate",          "align": "center"},
    {"name": "gross_capital", "label": "Kapitał Brutto (PLN)", "field": "gross_capital", "align": "right"},
    {"name": "interest",      "label": "Odsetki (PLN)",        "field": "interest",      "align": "right"},
    {"name": "tax",           "label": "Podatek / Opłata (PLN)", "field": "tax",         "align": "right"},
    {"name": "net_capital",   "label": "Saldo Netto (PLN)",    "field": "net_capital",   "align": "right"},
]

with ui.column().classes("p-6 gap-5 w-full"):

    # ── 1. Hero Metrics ───────────────────────────────────────────────────────
    with ui.row().classes("w-full gap-4 flex-nowrap items-stretch"):

        with ui.card().classes("flex-1 shadow-sm").style(
            "border-left:4px solid #64748b; padding:16px 20px;"
        ):
            ui.label("Łączny Kapitał Brutto").classes(
                "text-xs text-slate-400 uppercase tracking-widest"
            )
            refs["m_gross"] = ui.label("…").classes(
                "text-2xl font-bold font-mono text-slate-700 mt-2"
            )

        with ui.card().classes("flex-1 shadow-sm").style(
            "border-left:4px solid #ef4444; padding:16px 20px;"
        ):
            ui.label("Całkowite Odpisy Rządowe").classes(
                "text-xs text-slate-400 uppercase tracking-widest"
            )
            ui.label("Podatek Belki + kara").classes("text-xs text-slate-300 mt-0.5")
            refs["m_deduct"] = ui.label("…").classes(
                "text-2xl font-bold font-mono text-red-500 mt-1"
            )

        with ui.card().classes("flex-1 shadow-sm").style(
            "border-left:4px solid #22c55e; background:#f0fdf4; padding:20px 24px;"
        ):
            ui.label("Docelowy Przepływ Netto").classes(
                "text-xs text-slate-500 uppercase tracking-widest"
            )
            ui.label("Kwota do wypłaty").classes("text-xs text-slate-400 mt-0.5")
            refs["m_net"] = ui.label("…").classes(
                "text-3xl font-bold font-mono text-green-600 mt-2"
            )

        with ui.card().classes("flex-1 shadow-sm").style(
            "border-left:4px solid #6366f1; padding:16px 20px;"
        ):
            ui.label("Urealniona Stopa Zwrotu").classes(
                "text-xs text-slate-400 uppercase tracking-widest"
            )
            ui.label("Annualizowana, po inflacji").classes("text-xs text-slate-300 mt-0.5")
            refs["m_rate"] = ui.label("…").classes(
                "text-2xl font-bold font-mono text-indigo-600 mt-1"
            )

    # ── 2. Plotly Chart ───────────────────────────────────────────────────────
    with ui.card().classes("w-full shadow-sm").style("padding:16px;"):
        with ui.row().classes("items-center gap-2 mb-3"):
            ui.icon("bar_chart").classes("text-slate-400 text-xl")
            ui.label("Eksplorator Wizualny").classes("text-sm font-semibold text-slate-600")
        refs["chart"] = ui.plotly(go.Figure()).classes("w-full").style("height:360px;")

    # ── 3. Amortization Table (accordion) ─────────────────────────────────────
    with ui.expansion(
        "Rozłóż Tabelę Obliczeniową Krok po Kroku", icon="table_chart"
    ).classes("w-full shadow-sm bg-white rounded-lg").style(
        "border:1px solid #e2e8f0;"
    ):
        refs["result_table"] = (
            ui.table(columns=TABLE_COLUMNS, rows=[], row_key="year")
            .classes("w-full text-sm")
            .props("dense flat")
        )

# ── Prime all outputs ─────────────────────────────────────────────────────────
_refresh()

ui.run(title="Kalkulator Obligacji Skarbowych", port=8080, reload=False)
