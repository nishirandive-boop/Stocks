"""
Global markets dashboard — worldwide trends + budget stock picker.

Default view: live world indices, sectors, and regional movers.
Second view: enter your capital and get a sized buy list.

Run:
  pip install -r requirements.txt
  streamlit run dashboard.py
"""

from __future__ import annotations

import json
import math
import os
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import certifi
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

st.set_page_config(
    page_title="Global Markets",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

C = {
    "bg": "#07111f",
    "panel": "#0e1c2f",
    "card": "#132840",
    "border": "#1f3b5a",
    "text": "#f4f8ff",
    "muted": "#c5d4e8",
    "teal": "#00c2a8",
    "gold": "#f0b429",
    "coral": "#ff6b6b",
    "sky": "#3dbbff",
    "violet": "#9b7bff",
    "lime": "#7dffa0",
    "orange": "#ff9f43",
}

PALETTE = [
    C["teal"],
    C["sky"],
    C["violet"],
    C["gold"],
    C["orange"],
    C["lime"],
    C["coral"],
    "#ff7ab6",
    "#5eead4",
    "#a78bfa",
]

TV_COLUMNS = [
    "name",
    "close",
    "change",
    "volume",
    "market_cap_basic",
    "Recommend.All",
    "Perf.W",
    "Perf.1M",
    "Perf.3M",
    "Perf.YTD",
    "Perf.Y",
    "price_earnings_ttm",
    "dividends_yield",
    "Volatility.D",
    "description",
    "exchange",
    "sector",
    "average_volume_10d_calc",
    "Relative Strength Index",
]


WORLD_INDICES = [
    ("SP:SPX", "S&P 500", "USA"),
    ("NASDAQ:NDX", "Nasdaq 100", "USA"),
    ("TVC:DJI", "Dow Jones", "USA"),
    ("TVC:UKX", "FTSE 100", "UK"),
    ("TVC:SX5E", "Euro Stoxx 50", "Europe"),
    ("TVC:NI225", "Nikkei 225", "Japan"),
    ("TVC:HSI", "Hang Seng", "Hong Kong"),
    ("TVC:VIX", "VIX (fear)", "USA"),
]

SECTOR_ETFS = [
    ("AMEX:XLK", "Technology"),
    ("AMEX:XLF", "Financials"),
    ("AMEX:XLE", "Energy"),
    ("AMEX:XLV", "Health Care"),
    ("AMEX:XLI", "Industrials"),
    ("AMEX:XLY", "Cons. Disc."),
    ("AMEX:XLP", "Cons. Staples"),
    ("AMEX:XLU", "Utilities"),
    ("AMEX:XLB", "Materials"),
    ("AMEX:XLRE", "Real Estate"),
    ("AMEX:XLC", "Comm. Services"),
]

QUOTE_COLS = [
    "name",
    "close",
    "change",
    "Perf.W",
    "Perf.1M",
    "Perf.YTD",
    "description",
]


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def tv_quotes(tickers: list[str], columns: list[str] | None = None) -> list[dict]:
    cols = columns or QUOTE_COLS
    payload = {
        "symbols": {"tickers": tickers, "query": {"types": []}},
        "columns": cols,
    }
    req = urllib.request.Request(
        "https://scanner.tradingview.com/global/scan",
        data=json.dumps(payload).encode(),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25, context=_ssl_context()) as resp:
        data = json.load(resp)
    rows = []
    for item in data.get("data", []):
        vals = item.get("d", [])
        row = {"symbol_full": item.get("s")}
        for i, col in enumerate(cols):
            row[col] = vals[i] if i < len(vals) else None
        rows.append(row)
    return rows


@st.cache_data(ttl=45, show_spinner=False)
def fetch_world_indices() -> pd.DataFrame:
    meta = {t: (label, region) for t, label, region in WORLD_INDICES}
    raw = tv_quotes([t for t, _, _ in WORLD_INDICES])
    rows = []
    for r in raw:
        label, region = meta.get(r["symbol_full"], (r.get("description"), "—"))
        rows.append(
            {
                "symbol": r["symbol_full"],
                "index": label,
                "region": region,
                "price": r.get("close"),
                "day_pct": r.get("change"),
                "week_pct": r.get("Perf.W"),
                "month_pct": r.get("Perf.1M"),
                "ytd_pct": r.get("Perf.YTD"),
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=45, show_spinner=False)
def fetch_sector_heat() -> pd.DataFrame:
    meta = {t: name for t, name in SECTOR_ETFS}
    raw = tv_quotes([t for t, _ in SECTOR_ETFS])
    rows = []
    for r in raw:
        rows.append(
            {
                "etf": r.get("name"),
                "sector": meta.get(r["symbol_full"], r.get("description")),
                "price": r.get("close"),
                "day_pct": r.get("change"),
                "week_pct": r.get("Perf.W"),
                "month_pct": r.get("Perf.1M"),
                "ytd_pct": r.get("Perf.YTD"),
            }
        )
    return pd.DataFrame(rows).sort_values("day_pct", ascending=False)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_regional_movers(limit: int = 8) -> dict[str, pd.DataFrame]:
    """Top day gainers per major region from a loose liquidity screen."""
    markets = {
        "USA": "america",
        "Europe": "germany",
        "UK": "uk",
        "Asia": "japan",
    }
    out: dict[str, pd.DataFrame] = {}
    cols = [
        "name",
        "close",
        "change",
        "Perf.1M",
        "Perf.YTD",
        "description",
        "market_cap_basic",
        "volume",
    ]
    for label, market in markets.items():
        payload = {
            "filter": [
                {"left": "type", "operation": "equal", "right": "stock"},
                {"left": "market_cap_basic", "operation": "greater", "right": 5e9},
                {"left": "average_volume_10d_calc", "operation": "greater", "right": 300_000},
                {"left": "close", "operation": "greater", "right": 2},
            ],
            "options": {"lang": "en"},
            "markets": [market],
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": cols,
            "sort": {"sortBy": "change", "sortOrder": "desc"},
            "range": [0, limit],
        }
        try:
            req = urllib.request.Request(
                f"https://scanner.tradingview.com/{market}/scan",
                data=json.dumps(payload).encode(),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=25, context=_ssl_context()) as resp:
                data = json.load(resp)
            rows = []
            for item in data.get("data", []):
                vals = item.get("d", [])
                row = {cols[i]: vals[i] if i < len(vals) else None for i in range(len(cols))}
                row["ticker"] = row.get("name")
                rows.append(row)
            out[label] = pd.DataFrame(rows)
        except Exception:
            out[label] = pd.DataFrame()
    return out


def index_card_html(row: pd.Series) -> str:
    chg = row.get("day_pct")
    cls = "up" if pd.notna(chg) and float(chg) >= 0 else "down"
    accent = C["lime"] if cls == "up" else C["coral"]
    return f"""
    <div class="pick-card" style="--accent:{accent}">
      <div class="pick-rank">{row.get('region')}</div>
      <div class="pick-ticker">{row.get('index')}</div>
      <div class="pick-name">{row.get('symbol')}</div>
      <div class="pick-price">{fmt_num(row.get('price'), 2)}
        <span class="{cls}">{fmt_pct(chg)}</span>
      </div>
      <div class="pick-meta">
        W {fmt_pct(row.get('week_pct'))} ·
        M {fmt_pct(row.get('month_pct'))} ·
        YTD {fmt_pct(row.get('ytd_pct'))}
      </div>
    </div>
    """


def fmt_num(x: Any, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{float(x):,.{digits}f}"


def render_world_trends() -> None:
    st.subheader("Worldwide market pulse")
    st.caption("Live global indices, US sector ETFs, and regional day leaders.")

    try:
        indices = fetch_world_indices()
        sectors = fetch_sector_heat()
        movers = fetch_regional_movers()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ssl.SSLError) as exc:
        st.error(f"Could not load world trends: {exc}")
        return

    if indices.empty:
        st.warning("Index feed returned no rows.")
    else:
        # KPI strip — majors (native metrics = reliable layout)
        majors = ["S&P 500", "Nasdaq 100", "Euro Stoxx 50", "Nikkei 225", "VIX (fear)"]
        kcols = st.columns(5)
        for i, name in enumerate(majors):
            hit = indices[indices["index"] == name]
            with kcols[i]:
                if hit.empty:
                    st.metric(name, "—")
                else:
                    r = hit.iloc[0]
                    delta = float(r["day_pct"]) if pd.notna(r["day_pct"]) else None
                    st.metric(
                        name,
                        fmt_num(r["price"]),
                        None if delta is None else f"{delta:+.2f}%",
                    )

        st.markdown("##### All indices")
        # Two clean rows of 4 metrics — never recreate columns inside a loop body
        rows = list(indices.iterrows())
        for start in range(0, len(rows), 4):
            chunk = rows[start : start + 4]
            cols = st.columns(4)
            for i, (_, row) in enumerate(chunk):
                with cols[i]:
                    delta = float(row["day_pct"]) if pd.notna(row["day_pct"]) else None
                    st.metric(
                        f"{row['index']} · {row['region']}",
                        fmt_num(row["price"]),
                        None if delta is None else f"{delta:+.2f}%",
                        help=(
                            f"{row['symbol']} · "
                            f"W {fmt_pct(row.get('week_pct'))} · "
                            f"M {fmt_pct(row.get('month_pct'))} · "
                            f"YTD {fmt_pct(row.get('ytd_pct'))}"
                        ),
                    )

        idx_table = indices[
            ["index", "region", "price", "day_pct", "week_pct", "month_pct", "ytd_pct", "symbol"]
        ].rename(
            columns={
                "index": "Index",
                "region": "Region",
                "price": "Last",
                "day_pct": "Day %",
                "week_pct": "1W %",
                "month_pct": "1M %",
                "ytd_pct": "YTD %",
                "symbol": "Symbol",
            }
        )
        st.dataframe(
            idx_table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Last": st.column_config.NumberColumn(format="%.2f"),
                "Day %": st.column_config.NumberColumn(format="%+.2f"),
                "1W %": st.column_config.NumberColumn(format="%+.2f"),
                "1M %": st.column_config.NumberColumn(format="%+.2f"),
                "YTD %": st.column_config.NumberColumn(format="%+.2f"),
            },
        )

        c1, c2 = st.columns(2)
        with c1:
            fig = go.Figure(
                go.Bar(
                    x=indices["day_pct"],
                    y=indices["index"],
                    orientation="h",
                    marker_color=[
                        C["lime"] if pd.notna(v) and v >= 0 else C["coral"]
                        for v in indices["day_pct"]
                    ],
                    text=[fmt_pct(v) for v in indices["day_pct"]],
                    textposition="outside",
                    cliponaxis=False,
                )
            )
            fig.update_layout(yaxis=dict(autorange="reversed"), height=420)
            st.plotly_chart(
                plot_layout(fig, "Index day move (%)"),
                use_container_width=True,
            )
        with c2:
            long = indices.melt(
                id_vars=["index"],
                value_vars=["week_pct", "month_pct", "ytd_pct"],
                var_name="Window",
                value_name="Return %",
            )
            long["Window"] = long["Window"].map(
                {"week_pct": "1W", "month_pct": "1M", "ytd_pct": "YTD"}
            )
            fig = px.bar(
                long,
                x="index",
                y="Return %",
                color="Window",
                barmode="group",
                color_discrete_sequence=[C["sky"], C["violet"], C["gold"]],
                height=420,
            )
            fig.update_layout(xaxis_tickangle=-25)
            st.plotly_chart(
                plot_layout(fig, "Index performance by window"),
                use_container_width=True,
            )

    st.subheader("Sector trends (US ETF proxies)")
    if sectors.empty:
        st.warning("Sector feed returned no rows.")
    else:
        h1, h2 = st.columns(2)
        with h1:
            fig = go.Figure(
                go.Bar(
                    x=sectors["day_pct"],
                    y=sectors["sector"],
                    orientation="h",
                    marker_color=[
                        C["teal"] if pd.notna(v) and v >= 0 else C["orange"]
                        for v in sectors["day_pct"]
                    ],
                )
            )
            fig.update_layout(yaxis=dict(autorange="reversed"), height=460)
            st.plotly_chart(plot_layout(fig, "Sector day %"), use_container_width=True)
        with h2:
            heat = sectors.set_index("sector")[["day_pct", "week_pct", "month_pct", "ytd_pct"]]
            heat.columns = ["Day", "1W", "1M", "YTD"]
            fig = px.imshow(
                heat,
                text_auto=".1f",
                color_continuous_scale=["#ff6b6b", "#132840", "#7dffa0"],
                aspect="auto",
                labels=dict(color="%"),
                height=460,
            )
            st.plotly_chart(plot_layout(fig, "Sector heatmap (%)"), use_container_width=True)

        st.dataframe(
            sectors.rename(
                columns={
                    "etf": "ETF",
                    "sector": "Sector",
                    "price": "Price",
                    "day_pct": "Day %",
                    "week_pct": "1W %",
                    "month_pct": "1M %",
                    "ytd_pct": "YTD %",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Day %": st.column_config.NumberColumn(format="%+.2f"),
                "1W %": st.column_config.NumberColumn(format="%+.2f"),
                "1M %": st.column_config.NumberColumn(format="%+.2f"),
                "YTD %": st.column_config.NumberColumn(format="%+.2f"),
                "Price": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    st.subheader("Regional day leaders")
    # 2x2 grid — 4 narrow columns was crushing tables on smaller windows
    regions_list = list(movers.items())
    for start in range(0, len(regions_list), 2):
        pair = regions_list[start : start + 2]
        mcols = st.columns(2)
        for i, (region, df) in enumerate(pair):
            with mcols[i]:
                st.markdown(f"**{region}**")
                if df is None or df.empty:
                    st.caption("No data")
                    continue
                show = df[["ticker", "close", "change", "description"]].rename(
                    columns={
                        "ticker": "Ticker",
                        "close": "Price",
                        "change": "Day %",
                        "description": "Name",
                    }
                )
                st.dataframe(
                    show,
                    use_container_width=True,
                    hide_index=True,
                    height=280,
                    column_config={
                        "Day %": st.column_config.NumberColumn(format="%+.2f"),
                        "Price": st.column_config.NumberColumn(format="%.2f"),
                    },
                )




def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&family=Syne:wght@700;800&display=swap');
        .stApp {{
            background:
              radial-gradient(1100px 520px at 8% -8%, #153a66 0%, transparent 55%),
              radial-gradient(900px 480px at 95% 0%, #1a3d2e 0%, transparent 50%),
              linear-gradient(180deg, {C["bg"]} 0%, #0a1628 100%);
            color: {C["text"]};
            font-family: 'DM Sans', sans-serif;
        }}
        h1, h2, h3 {{ font-family: 'Syne', sans-serif !important; }}
        [data-testid="stSidebar"] {{
            background: {C["panel"]}; border-right: 1px solid {C["border"]};
        }}
        .hero {{
            background: linear-gradient(120deg, #0f2a44 0%, #134e4a 50%, #1e3a5f 100%);
            border: 1px solid {C["border"]}; border-radius: 18px;
            padding: 1.35rem 1.5rem; margin-bottom: 1rem;
        }}
        .hero h1 {{
            margin: 0; font-size: 2rem;
            background: linear-gradient(90deg, {C["gold"]}, {C["teal"]}, {C["sky"]});
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .hero p {{ color: {C["muted"]}; margin: 0.45rem 0 0 0; }}
        .live-pill {{
            display: inline-flex; align-items: center; gap: 8px;
            background: rgba(0,194,168,0.15); color: {C["teal"]};
            border: 1px solid {C["teal"]}; border-radius: 999px;
            padding: 4px 12px; font-size: 0.8rem; font-weight: 700;
        }}
        .dot {{
            width: 8px; height: 8px; border-radius: 50%; background: {C["lime"]};
            box-shadow: 0 0 10px {C["lime"]}; animation: pulse 1.4s infinite;
        }}
        @keyframes pulse {{ 0%{{opacity:1}} 50%{{opacity:.35}} 100%{{opacity:1}} }}
        .pick-card {{
            background: {C["card"]}; border: 1px solid {C["border"]};
            border-radius: 16px; padding: 1rem 1.1rem;
            border-left: 5px solid var(--accent, {C["teal"]});
            min-width: 0; width: 100%;
            box-sizing: border-box;
            white-space: normal; word-break: normal; overflow-wrap: anywhere;
        }}
        .pick-rank {{
            font-size: 0.75rem; font-weight: 800; color: var(--accent, {C["teal"]});
            letter-spacing: 0.04em;
        }}
        .pick-ticker {{
            font-size: 1.25rem; font-weight: 800; color: {C["text"]};
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .pick-name {{ font-size: 0.8rem; color: {C["muted"]}; margin-bottom: 0.35rem; }}
        .pick-price {{ font-size: 1.15rem; font-weight: 700; }}
        .up {{ color: {C["lime"]}; font-weight: 700; }}
        .down {{ color: {C["coral"]}; font-weight: 700; }}
        .pick-meta {{ font-size: 0.78rem; color: {C["muted"]}; margin-top: 0.35rem; line-height: 1.35; }}
        .alloc-box {{
            background: linear-gradient(90deg, rgba(0,194,168,0.16), rgba(240,180,41,0.12));
            border: 1px solid {C["teal"]}; border-radius: 14px;
            padding: 1rem 1.2rem; margin: 0.8rem 0 1rem 0;
        }}
        div[data-testid="column"] {{ min-width: 0; }}
        div[data-testid="stMetric"] {{
            background: {C["card"]}; border: 1px solid {C["border"]};
            border-radius: 14px; padding: 0.75rem 1rem;
            min-width: 0;
        }}
        div[data-testid="stMetricLabel"] p {{
            white-space: normal !important;
            overflow-wrap: anywhere;
            color: {C["muted"]} !important;
            opacity: 1 !important;
        }}
        div[data-testid="stMetricValue"],
        div[data-testid="stMetricValue"] * {{
            color: {C["text"]} !important;
            opacity: 1 !important;
        }}
        /* Brighten Streamlit gray labels / sidebar / captions */
        .stApp p, .stApp span, .stApp label, .stMarkdown {{
            color: {C["text"]};
        }}
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stWidgetLabel"] p,
        [data-testid="stWidgetLabel"] span {{
            color: {C["muted"]} !important;
            opacity: 1 !important;
        }}
        .stRadio label, .stRadio span,
        [role="radiogroup"] label, [role="radiogroup"] p {{
            color: {C["text"]} !important;
            opacity: 1 !important;
        }}
        .stCaption, [data-testid="stCaptionContainer"] p {{
            color: {C["muted"]} !important;
            opacity: 1 !important;
        }}
        h2, h3, h4, .stSubheader {{
            color: {C["text"]} !important;
        }}
        .alloc-box, .alloc-box * {{
            color: {C["text"]} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def screen_filters(style: str, max_price: float | None) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = [
        {"left": "type", "operation": "equal", "right": "stock"},
        {"left": "typespecs", "operation": "has", "right": ["common"]},
        {"left": "is_primary", "operation": "equal", "right": True},
        {"left": "market_cap_basic", "operation": "greater", "right": 2e9},
        {"left": "close", "operation": "greater", "right": 2},
        {"left": "average_volume_10d_calc", "operation": "greater", "right": 200_000},
    ]
    if max_price is not None and max_price > 0:
        filters.append({"left": "close", "operation": "less", "right": float(max_price)})

    if style == "Momentum":
        filters.append({"left": "Perf.1M", "operation": "greater", "right": -5})
        filters.append({"left": "Recommend.All", "operation": "greater", "right": -0.2})
    elif style == "Value / income":
        filters.append({"left": "dividends_yield", "operation": "greater", "right": 1.0})
    elif style == "Growth":
        filters.append({"left": "Perf.YTD", "operation": "greater", "right": -10})
        filters.append({"left": "Recommend.All", "operation": "greater", "right": -0.1})
    else:  # Balanced
        filters.append({"left": "Recommend.All", "operation": "greater", "right": -0.3})
    return filters


def sort_for_style(style: str) -> dict[str, str]:
    if style == "Momentum":
        return {"sortBy": "Perf.1M", "sortOrder": "desc"}
    if style == "Value / income":
        return {"sortBy": "dividends_yield", "sortOrder": "desc"}
    if style == "Growth":
        return {"sortBy": "Perf.YTD", "sortOrder": "desc"}
    return {"sortBy": "Recommend.All", "sortOrder": "desc"}


def _tv_post(market: str, payload: dict[str, Any]) -> list[dict]:
    req = urllib.request.Request(
        f"https://scanner.tradingview.com/{market}/scan",
        data=json.dumps(payload).encode(),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25, context=_ssl_context()) as resp:
        data = json.load(resp)
    rows = []
    for item in data.get("data", []):
        vals = item.get("d", [])
        row = {"symbol_full": item.get("s")}
        for i, col in enumerate(TV_COLUMNS):
            row[col] = vals[i] if i < len(vals) else None
        rows.append(row)
    return rows


def tv_scan(market: str, style: str, max_price: float | None, limit: int = 40) -> list[dict]:
    payload = {
        "filter": screen_filters(style, max_price),
        "options": {"lang": "en"},
        "markets": [market],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": TV_COLUMNS,
        "sort": sort_for_style(style),
        "range": [0, limit],
    }
    try:
        return _tv_post(market, payload)
    except Exception:
        # Fallback: very loose screen so the UI never goes empty on filter quirks
        fallback = {
            "filter": [
                {"left": "type", "operation": "equal", "right": "stock"},
                {"left": "market_cap_basic", "operation": "greater", "right": 1e9},
                {"left": "close", "operation": "greater", "right": 1},
            ],
            "options": {"lang": "en"},
            "markets": [market],
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": TV_COLUMNS,
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "range": [0, limit],
        }
        if max_price is not None and max_price > 0:
            fallback["filter"].append(
                {"left": "close", "operation": "less", "right": float(max_price)}
            )
        return _tv_post(market, fallback)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_universe(regions: tuple[str, ...], style: str, max_price: float | None) -> pd.DataFrame:
    region_map = {
        "USA": "america",
        "Europe": "germany",
        "UK": "uk",
        "Asia": "japan",
    }
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for label in regions:
        market = region_map.get(label)
        if not market:
            continue
        try:
            raw = tv_scan(market, style, max_price, limit=40)
            if raw:
                df = pd.DataFrame(raw)
                df["region"] = label
                frames.append(df)
            else:
                errors.append(f"{label}: 0 rows")
        except Exception as exc:
            errors.append(f"{label}: {exc}")
        if label == "Europe":
            try:
                raw_uk = tv_scan("uk", style, max_price, limit=25)
                if raw_uk:
                    d2 = pd.DataFrame(raw_uk)
                    d2["region"] = "UK"
                    frames.append(d2)
            except Exception as exc:
                errors.append(f"UK: {exc}")

    if not frames:
        # Last resort: USA mega-caps only
        try:
            raw = tv_scan("america", "Balanced", None, limit=40)
            if raw:
                df = pd.DataFrame(raw)
                df["region"] = "USA"
                frames.append(df)
        except Exception as exc:
            errors.append(f"fallback USA: {exc}")

    if not frames:
        raise RuntimeError(
            "Market screen returned no data. "
            + ("; ".join(errors) if errors else "Check network / SSL certs.")
        )

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["name"], keep="first")
    out["ticker"] = out["name"]
    out["price"] = pd.to_numeric(out["close"], errors="coerce")
    out["change_pct"] = pd.to_numeric(out["change"], errors="coerce")
    out["mcap"] = pd.to_numeric(out["market_cap_basic"], errors="coerce")
    out["recommend"] = pd.to_numeric(out["Recommend.All"], errors="coerce")
    out["perf_w"] = pd.to_numeric(out["Perf.W"], errors="coerce")
    out["perf_1m"] = pd.to_numeric(out["Perf.1M"], errors="coerce")
    out["perf_3m"] = pd.to_numeric(out["Perf.3M"], errors="coerce")
    out["perf_ytd"] = pd.to_numeric(out["Perf.YTD"], errors="coerce")
    out["perf_y"] = pd.to_numeric(out["Perf.Y"], errors="coerce")
    out["pe"] = pd.to_numeric(out["price_earnings_ttm"], errors="coerce")
    out["div_yield"] = pd.to_numeric(out["dividends_yield"], errors="coerce")
    out["vol_d"] = pd.to_numeric(out["Volatility.D"], errors="coerce")
    out["rsi"] = pd.to_numeric(out["Relative Strength Index"], errors="coerce")
    out["avg_vol"] = pd.to_numeric(out["average_volume_10d_calc"], errors="coerce")
    out = out.dropna(subset=["price", "ticker"])
    out = out[out["price"] > 0]
    if max_price is not None and max_price > 0:
        affordable = out[out["price"] <= max_price]
        if not affordable.empty:
            out = affordable
    out["score"] = out.apply(score_row, axis=1)
    return out.sort_values("score", ascending=False).reset_index(drop=True)


def score_row(r: pd.Series) -> float:
    """0–100 live composite from technicals + momentum + quality proxies."""
    rec = float(r["recommend"]) if pd.notna(r["recommend"]) else 0.0
    # Recommend.All is roughly -1..+1
    tech = (rec + 1) / 2 * 35  # 0..35

    mom = 0.0
    for col, w in (("perf_w", 0.15), ("perf_1m", 0.35), ("perf_ytd", 0.25), ("perf_y", 0.25)):
        v = r.get(col)
        if pd.notna(v):
            mom += float(v) * w
    mom = max(-20, min(25, mom))  # clamp
    mom_pts = (mom + 20) / 45 * 30  # 0..30

    # Liquidity / size
    mcap = float(r["mcap"]) if pd.notna(r["mcap"]) else 0
    size_pts = min(15, math.log10(max(mcap, 1e9)) * 2.2)  # large caps score higher

    # Prefer not extremely overbought RSI
    rsi = float(r["rsi"]) if pd.notna(r["rsi"]) else 55
    if 40 <= rsi <= 70:
        rsi_pts = 10
    elif 30 <= rsi < 40 or 70 < rsi <= 80:
        rsi_pts = 6
    else:
        rsi_pts = 2

    # Mild dividend bonus
    dy = float(r["div_yield"]) if pd.notna(r["div_yield"]) else 0
    div_pts = min(10, max(0, dy) * 1.5)

    return round(min(100, max(0, tech + mom_pts + size_pts + rsi_pts + div_pts)), 1)


def target_positions(budget: float) -> int:
    if budget < 500:
        return 1
    if budget < 1500:
        return 2
    if budget < 5000:
        return 4
    if budget < 15000:
        return 6
    if budget < 50000:
        return 8
    return 10


def build_allocation(universe: pd.DataFrame, budget: float, n: int, risk: str) -> pd.DataFrame:
    """Greedy whole-share allocator: higher score → larger weight, fit budget."""
    if universe.empty or budget <= 0:
        return pd.DataFrame()

    # Risk: trim high volatility for conservative
    pool = universe.copy()
    if risk == "Conservative":
        pool = pool[pool["vol_d"].fillna(9) <= 4]
        if len(pool) < n:
            pool = universe.copy()
        pool = pool.head(max(n * 3, n))
    elif risk == "Aggressive":
        pool = pool.head(max(n * 4, n))
    else:
        pool = pool.head(max(n * 3, n))

    picks = pool.head(n).copy()
    if picks.empty:
        return pd.DataFrame()

    # Score-weighted target dollars
    scores = picks["score"].clip(lower=1)
    weights = scores / scores.sum()
    if risk == "Conservative":
        # flatten weights toward equal
        weights = 0.55 * weights + 0.45 * (1 / len(picks))
        weights = weights / weights.sum()
    elif risk == "Aggressive":
        weights = weights ** 1.35
        weights = weights / weights.sum()

    picks["target_usd"] = weights * budget
    picks["shares"] = (picks["target_usd"] / picks["price"]).apply(math.floor)
    # Ensure we buy at least 1 share of top pick if affordable
    for i in picks.index:
        price = float(picks.at[i, "price"])
        if picks.at[i, "shares"] == 0 and price <= budget * 0.35:
            picks.at[i, "shares"] = 1

    picks["cost"] = picks["shares"] * picks["price"]
    spent = float(picks["cost"].sum())
    leftover = budget - spent

    # Spend leftover on highest-score names we can still afford
    order = picks.sort_values("score", ascending=False).index.tolist()
    changed = True
    while leftover > 0 and changed:
        changed = False
        for i in order:
            price = float(picks.at[i, "price"])
            if price <= leftover:
                picks.at[i, "shares"] += 1
                picks.at[i, "cost"] = picks.at[i, "shares"] * price
                leftover -= price
                changed = True

    picks = picks[picks["shares"] > 0].copy()
    picks["weight_pct"] = picks["cost"] / picks["cost"].sum() * 100 if picks["cost"].sum() else 0
    picks["leftover_cash"] = leftover
    return picks.reset_index(drop=True)


def fmt_money(x: float, currency: str = "USD") -> str:
    return f"{currency} {x:,.2f}"


def fmt_pct(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{float(x):+.2f}%"


def plot_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(color=C["text"], size=16)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(19,40,64,0.55)",
        font=dict(color=C["muted"], family="DM Sans"),
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(gridcolor=C["border"]),
        yaxis=dict(gridcolor=C["border"]),
    )
    return fig


def pick_card(rank: int, row: pd.Series, accent: str) -> str:
    chg = row.get("change_pct")
    cls = "up" if pd.notna(chg) and chg >= 0 else "down"
    pe = row.get("pe")
    pe_txt = f"{float(pe):.1f}" if pd.notna(pe) else "—"
    return f"""
    <div class="pick-card" style="--accent:{accent}">
      <div class="pick-rank">#{rank} · SCORE {row['score']:.0f}</div>
      <div class="pick-ticker">{row['ticker']}</div>
      <div class="pick-name">{row.get('description') or ''} · {row.get('sector') or row.get('region')}</div>
      <div class="pick-price">{fmt_money(float(row['price']))}
        <span class="{cls}">{fmt_pct(chg)}</span>
      </div>
      <div class="pick-meta">
        Buy <b style="color:{accent}">{int(row['shares'])}</b> shares ·
        Cost <b>{fmt_money(float(row['cost']))}</b> ·
        {float(row['weight_pct']):.1f}% of portfolio
      </div>
      <div class="pick-meta">
        1M {fmt_pct(row.get('perf_1m'))} · YTD {fmt_pct(row.get('perf_ytd'))} ·
        Div {fmt_pct(row.get('div_yield'))} · P/E {pe_txt}
      </div>
    </div>
    """


def main() -> None:
    inject_css()

    with st.sidebar:
        st.markdown("### Navigation")
        page = st.radio(
            "View",
            ["World trends", "Invest my money"],
            index=0,
            help="Start with the global market pulse, then size a portfolio to your budget.",
        )
        st.divider()
        if st.button("Refresh market data", use_container_width=True):
            fetch_universe.clear()
            fetch_world_indices.clear()
            fetch_sector_heat.clear()
            fetch_regional_movers.clear()
            st.rerun()

        currency = "USD"
        budget = 5000.0
        risk = "Balanced"
        style = "Balanced"
        regions = ["USA", "Europe"]
        max_price = 0.0
        n_stocks = 4

        if page == "Invest my money":
            st.markdown("### Your capital")
            currency = st.selectbox("Currency label", ["USD", "AED", "EUR", "GBP"], index=0)
            budget = st.number_input(
                "How much can you invest?",
                min_value=50.0,
                max_value=5_000_000.0,
                value=5_000.0,
                step=100.0,
                help="Used to size whole-share purchases from live prices.",
            )
            risk = st.radio("Risk", ["Conservative", "Balanced", "Aggressive"], index=1)
            style = st.selectbox(
                "Market style",
                ["Balanced", "Momentum", "Growth", "Value / income"],
                index=0,
            )
            regions = st.multiselect(
                "Regions",
                ["USA", "Europe", "UK", "Asia"],
                default=["USA", "Europe"],
            )
            max_price = st.number_input(
                "Max price per share (0 = no limit)",
                min_value=0.0,
                value=0.0,
                step=10.0,
                help="Useful for small budgets so you can buy whole shares.",
            )
            auto_n = target_positions(budget)
            n_stocks = st.slider("Number of stocks", 1, 12, auto_n)
        st.caption("Live data via TradingView · delayed quotes · not advice")

    now = datetime.now().strftime("%H:%M:%S")

    if page == "World trends":
        st.markdown(
            f"""
            <div class="hero">
              <div class="live-pill"><span class="dot"></span> LIVE WORLD MARKETS · {now}</div>
              <h1>Worldwide stock trends</h1>
              <p>Global indices, sector rotation, and regional day leaders — updated from live market data.
              Switch to <b>Invest my money</b> in the sidebar when you want a budgeted buy list.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.spinner("Loading worldwide trends…"):
            render_world_trends()
        st.divider()
        st.caption(
            "Educational tool only — not investment advice. Index/sector quotes are delayed "
            "exchange data from TradingView’s public scanner."
        )
    else:
        st.markdown(
            f"""
            <div class="hero">
              <div class="live-pill"><span class="dot"></span> LIVE STOCK PICKER · {now}</div>
              <h1>Best stocks for your money</h1>
              <p>Enter your budget — we rank liquid global names from live market data and
              build a whole-share buy list that fits {fmt_money(budget, currency)}.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_invest_page(currency, budget, risk, style, regions, max_price, n_stocks)

    try:
        from streamlit_autorefresh import st_autorefresh

        st_autorefresh(interval=60_000, key="global_refresh")
    except ImportError:
        if hasattr(st, "fragment"):

            @st.fragment(run_every=timedelta(seconds=60))
            def _tick() -> None:
                st.caption(f"UI tick {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")

            _tick()


def render_invest_page(
    currency: str,
    budget: float,
    risk: str,
    style: str,
    regions: list[str],
    max_price: float,
    n_stocks: int,
) -> None:
    if not regions:
        st.warning("Pick at least one region in the sidebar.")
        return

    effective_max = max_price if max_price > 0 else None
    soft_cap = None
    if budget < 2000 and effective_max is None:
        soft_cap = max(budget * 0.5, 30)

    with st.spinner("Screening live global markets…"):
        try:
            universe = fetch_universe(tuple(regions), style, effective_max)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ssl.SSLError, RuntimeError) as exc:
            st.error(f"Could not reach live market data: {exc}")
            st.info("On Mac SSL errors: `pip install -U certifi` or run Install Certificates.command")
            return

    if universe.empty:
        st.error("No stocks matched this screen. Widen regions or raise max price / budget.")
        return

    if soft_cap is not None:
        affordable = universe[universe["price"] <= soft_cap]
        if len(affordable) >= max(3, n_stocks):
            universe = affordable.reset_index(drop=True)

    alloc = build_allocation(universe, budget, n_stocks, risk)
    if alloc.empty:
        cheapest = universe.nsmallest(5, "price")[["ticker", "price", "description", "score"]]
        st.warning(
            f"With {fmt_money(budget, currency)} you cannot buy a diversified whole-share basket "
            f"from this screen (prices may be too high). Try a higher budget, or set a max share price."
        )
        st.dataframe(cheapest, use_container_width=True, hide_index=True)
        return

    spent = float(alloc["cost"].sum())
    cash = float(alloc["leftover_cash"].iloc[0]) if "leftover_cash" in alloc else budget - spent
    top = alloc.iloc[0]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Your budget", fmt_money(budget, currency))
    k2.metric("Deployed", fmt_money(spent, currency), f"{spent / budget * 100:.0f}% invested")
    k3.metric("Cash left", fmt_money(cash, currency))
    k4.metric("Top pick", str(top["ticker"]), f"score {top['score']:.0f}")

    st.markdown(
        f"""
        <div class="alloc-box">
          <b style="color:{C['gold']}">Plan for {fmt_money(budget, currency)} · {risk} · {style}</b><br/>
          Buy <b>{len(alloc)}</b> stocks. Largest sleeve:
          <b style="color:{C['teal']}">{top['ticker']}</b>
          ({int(top['shares'])} shares ≈ {fmt_money(float(top['cost']), currency)}).
          Ranked from live technicals, momentum, size, RSI, and dividend quality.
          Whole shares only — leftover stays as cash.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Your buy list")
    cols = st.columns(min(3, len(alloc)))
    for i, (_, row) in enumerate(alloc.iterrows()):
        with cols[i % len(cols)]:
            st.markdown(
                pick_card(i + 1, row, PALETTE[i % len(PALETTE)]).replace("USD", currency),
                unsafe_allow_html=True,
            )
            st.write("")

    table = alloc[
        [
            "ticker",
            "description",
            "region",
            "sector",
            "price",
            "shares",
            "cost",
            "weight_pct",
            "score",
            "change_pct",
            "perf_1m",
            "perf_ytd",
            "div_yield",
            "pe",
            "recommend",
        ]
    ].rename(
        columns={
            "ticker": "Ticker",
            "description": "Company",
            "region": "Region",
            "sector": "Sector",
            "price": f"Price ({currency})",
            "shares": "Shares",
            "cost": f"Cost ({currency})",
            "weight_pct": "Weight %",
            "score": "Score",
            "change_pct": "Day %",
            "perf_1m": "1M %",
            "perf_ytd": "YTD %",
            "div_yield": "Div %",
            "pe": "P/E",
            "recommend": "Tech rating",
        }
    )
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            f"Price ({currency})": st.column_config.NumberColumn(format="%.2f"),
            f"Cost ({currency})": st.column_config.NumberColumn(format="%.2f"),
            "Weight %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "Day %": st.column_config.NumberColumn(format="%+.2f"),
            "1M %": st.column_config.NumberColumn(format="%+.2f"),
            "YTD %": st.column_config.NumberColumn(format="%+.2f"),
            "Div %": st.column_config.NumberColumn(format="%.2f"),
            "P/E": st.column_config.NumberColumn(format="%.1f"),
            "Tech rating": st.column_config.NumberColumn(format="%+.2f"),
        },
    )

    c1, c2 = st.columns(2)
    with c1:
        fig = px.pie(
            alloc,
            names="ticker",
            values="cost",
            hole=0.45,
            color_discrete_sequence=PALETTE,
        )
        st.plotly_chart(plot_layout(fig, "Capital allocation"), use_container_width=True)
    with c2:
        fig = go.Figure(
            go.Bar(
                x=alloc["ticker"],
                y=alloc["score"],
                marker_color=[PALETTE[i % len(PALETTE)] for i in range(len(alloc))],
                text=alloc["score"].round(0),
                textposition="outside",
            )
        )
        fig.update_yaxes(range=[0, 105], title="Score")
        st.plotly_chart(plot_layout(fig, "Live score of selected names"), use_container_width=True)

    st.subheader("Full market shortlist (before sizing)")
    st.caption("Top names from the live screen — your buy list is cut from these by budget & risk.")
    short = universe.head(25)[
        ["ticker", "description", "region", "sector", "price", "score", "change_pct", "perf_1m", "perf_ytd", "div_yield", "pe", "mcap"]
    ].rename(
        columns={
            "ticker": "Ticker",
            "description": "Company",
            "region": "Region",
            "sector": "Sector",
            "price": "Price",
            "score": "Score",
            "change_pct": "Day %",
            "perf_1m": "1M %",
            "perf_ytd": "YTD %",
            "div_yield": "Div %",
            "pe": "P/E",
            "mcap": "Market cap",
        }
    )
    st.dataframe(short, use_container_width=True, hide_index=True)

    st.divider()
    st.caption(
        "Educational tool only — not investment advice. Quotes are delayed exchange data from "
        "TradingView’s public scanner. Scores blend technical rating, momentum, market cap, RSI, "
        "and dividend yield. Always verify prices with your broker before trading."
    )


if __name__ == "__main__":
    main()
