"""
Root Cause AI — main Streamlit application.

Pipeline: Upload evidence (CSV/PDF/DOCX/TXT/logs/.eml) -> parse into
structured/aggregated findings -> hand a bounded JSON payload to Groq for
root-cause interpretation -> visualize on an interactive timeline -> export
a Markdown or PDF report.

The AI is only ever shown pre-aggregated evidence, never raw uploaded files
in full, and its system prompt explicitly forbids invented facts and bare
causal claims — see groq_client.py.
"""

import os
from datetime import datetime

import pandas as pd
import streamlit as st

import parsers
import timeline
import report
import alerts
import connectors
import benchmarks
import incident_store
import quality
from groq_client import GroqClientError, get_client, analyze_root_cause, get_ai_config

incident_store.init_db()


APP_DIR = os.path.dirname(os.path.abspath(__file__))
# FIX #1: sales.csv, ad_spend.csv, ga_export.csv, complaints.txt, and
# error_logs.txt live at the repo root next to app.py (confirmed from the
# GitHub file listing) — there is no "sample_data" subfolder. Pointing
# SAMPLE_DIR at APP_DIR itself resolves the "Sample file missing" errors.
# If you later move the sample files into an actual sample_data/ folder,
# revert this to: os.path.join(APP_DIR, "sample_data")
SAMPLE_DIR = APP_DIR
SAMPLE_FILES = ["sales.csv", "ad_spend.csv", "ga_export.csv", "complaints.txt", "error_logs.txt"]

ACCEPTED_TYPES = ["csv", "pdf", "docx", "txt", "eml"]

BUSINESS_MODEL_FRAMEWORKS = [
    "Generic Financial",
    "E-commerce Funnel",
    "SaaS / Subscription (MRR/Churn)",
    "B2B Marketing Funnel",
]


# =============================================================================
# Local-file wrapper (so sample data can reuse the exact same parser path
# as a real Streamlit upload — both just need .name and .read())
# =============================================================================

class LocalFileWrapper:
    def __init__(self, path):
        self.name = os.path.basename(path)
        self._path = path

    def read(self):
        with open(self._path, "rb") as f:
            return f.read()


# =============================================================================
# Page config + theme
# =============================================================================


st.set_page_config(
    page_title="Root Cause AI",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
:root {
    --rc-bg: #0b0b14;
    --rc-panel: #12121e;
    --rc-panel-alt: #171728;
    --rc-border: #30304a;
    --rc-emerald: #00d9a3;
    --rc-cyan: #00e5ff;
    --rc-indigo: #7c74ff;
    --rc-text: #f3f5fb;
    --rc-text-dim: #b9bfd0;
    --rc-text-muted: #a7aec2;
    --rc-critical: #ff6262;
    --rc-high: #ffab55;
    --rc-medium: #ffe06a;
    --rc-low: #39d6a8;
}

/* ---------- Base application ---------- */
.stApp {
    background: radial-gradient(circle at 10% 0%, #14142a 0%, #0b0b14 55%) fixed;
    color: var(--rc-text) !important;
}

[data-testid="stAppViewContainer"],
[data-testid="stMainBlockContainer"] {
    color: var(--rc-text) !important;
}

/* Make Streamlit's default text readable on the dark theme. */
.stApp p,
.stApp li,
.stApp label,
.stApp small,
.stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stCaptionContainer"] p,
.stApp .stMarkdown,
.stApp .stMarkdown p,
.stApp .stMarkdown span {
    color: var(--rc-text-dim);
}

.stApp strong,
.stApp b,
.stApp [data-testid="stWidgetLabel"] p,
.stApp [data-testid="stWidgetLabel"] label {
    color: var(--rc-text) !important;
}

h1, h2, h3, h4, h5, h6 {
    color: var(--rc-text) !important;
    letter-spacing: -0.01em;
}

/* ---------- Sidebar: narrower, denser, higher contrast ---------- */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #10101c 0%, #0c0c16 100%) !important;
    border-right: 1px solid var(--rc-border) !important;
    width: 270px !important;
}

section[data-testid="stSidebar"] > div {
    width: 270px !important;
}

section[data-testid="stSidebar"] .block-container {
    padding: 1rem 0.85rem 1.35rem 0.85rem !important;
}

section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] small {
    color: var(--rc-text-dim) !important;
}

section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] label,
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4 {
    color: var(--rc-text) !important;
}

section[data-testid="stSidebar"] hr {
    border-color: var(--rc-border) !important;
}

/* Selectbox: white field + readable label/help text. */
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #f7f8fc !important;
    border-color: #d7dbea !important;
    color: #202536 !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] div,
section[data-testid="stSidebar"] [data-baseweb="select"] span {
    color: #202536 !important;
}
section[data-testid="stSidebar"] [data-testid="InputInstructions"],
section[data-testid="stSidebar"] [data-testid="stHelpTooltip"] {
    color: var(--rc-text-muted) !important;
}

/* File uploader text was almost invisible in the screenshot. */
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"],
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] * {
    color: var(--rc-text-dim) !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
    color: #202536 !important;
}

/* ---------- User question ---------- */
.rc-question-card {
    width: 100%;
    box-sizing: border-box;
    padding: 14px 18px;
    margin: 0 0 18px 0;
    border: 1px solid var(--rc-border);
    border-left: 4px solid var(--rc-cyan);
    border-radius: 12px;
    background: rgba(0,229,255,0.06);
    color: var(--rc-text) !important;
    line-height: 1.55;
}
.rc-question-card strong { color: var(--rc-cyan) !important; }

/* ---------- Main content ---------- */
[data-testid="stAppViewContainer"] {
    overflow-x: hidden;
}

[data-testid="stMainBlockContainer"] {
    max-width: 1600px;
    padding-left: clamp(1.1rem, 2vw, 2rem);
    padding-right: clamp(1.1rem, 2vw, 2rem);
    padding-top: 1.25rem;
}

.rc-hero {
    width: 100%;
    box-sizing: border-box;
    padding: 28px 32px;
    border-radius: 18px;
    background: linear-gradient(120deg, rgba(0,217,163,0.10), rgba(108,99,255,0.10));
    border: 1px solid var(--rc-border);
    margin-bottom: 22px;
}
.rc-hero h1 {
    font-size: 2.1rem;
    margin: 0 0 6px 0;
    background: linear-gradient(90deg, var(--rc-emerald), var(--rc-cyan));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.rc-hero p { color: var(--rc-text-dim) !important; margin: 0; font-size: 1.02rem; }

.rc-metric-row { display: flex; gap: 16px; flex-wrap: wrap; margin: 6px 0 18px 0; }
.rc-metric-card {
    flex: 1 1 200px;
    min-width: 0;
    box-sizing: border-box;
    background: linear-gradient(145deg, var(--rc-panel), var(--rc-panel-alt));
    border: 1px solid var(--rc-border);
    border-radius: 14px;
    padding: 18px 20px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.02) inset;
}
.rc-metric-card::before {
    content: "";
    position: absolute; top: -30%; right: -20%;
    width: 140px; height: 140px; border-radius: 50%;
    background: radial-gradient(circle, var(--accent, var(--rc-cyan)) 0%, transparent 70%);
    opacity: 0.18;
}
.rc-metric-icon { font-size: 1.5rem; margin-bottom: 6px; }
.rc-metric-value { font-size: 1.7rem; font-weight: 700; color: var(--rc-text) !important; line-height: 1.1; }
.rc-metric-label { font-size: 0.82rem; color: var(--rc-text-dim) !important; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }

.rc-card {
    background: linear-gradient(160deg, var(--rc-panel), var(--rc-panel-alt));
    border: 1px solid var(--rc-border);
    border-radius: 14px;
    padding: 16px 20px;
    margin-bottom: 14px;
}
.rc-card h4 { margin: 0 0 8px 0; font-size: 1.02rem; color: var(--rc-text) !important; }
.rc-card p { margin: 4px 0; color: var(--rc-text-dim) !important; font-size: 0.93rem; }
.rc-card .rc-evidence { color: #c5c9d8 !important; font-size: 0.88rem; font-style: italic; margin-top: 6px; }

.rc-badge {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 0.75rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;
}

/* Buttons: explicit high-contrast styling.  Streamlit renders the visible
   label inside nested elements, so style both the button and its children. */
.stButton > button,
.stDownloadButton > button {
    background: linear-gradient(90deg, var(--rc-emerald), var(--rc-cyan)) !important;
    color: #071014 !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 800 !important;
    min-height: 42px !important;
    padding: 0.55rem 0.8rem !important;
    text-shadow: none !important;
    opacity: 1 !important;
    transition: transform 0.08s ease, box-shadow 0.15s ease !important;
}

.stButton > button *,
.stDownloadButton > button * {
    color: #071014 !important;
    opacity: 1 !important;
    visibility: visible !important;
    text-shadow: none !important;
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    background: linear-gradient(90deg, var(--rc-cyan), var(--rc-emerald)) !important;
    color: #071014 !important;
    box-shadow: 0 0 18px rgba(0, 229, 255, 0.35) !important;
    transform: translateY(-1px);
}

/* Sidebar buttons get an explicit rule so global Streamlit/theme styles
   cannot wash out the label. */
section[data-testid="stSidebar"] .stButton > button,
section[data-testid="stSidebar"] .stDownloadButton > button {
    color: #071014 !important;
    opacity: 1 !important;
}

section[data-testid="stSidebar"] .stButton > button *,
section[data-testid="stSidebar"] .stDownloadButton > button * {
    color: #071014 !important;
    opacity: 1 !important;
    visibility: visible !important;
}

/* Primary Run Root Cause Analysis button */
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: linear-gradient(90deg, #7168ff, #00e5ff) !important;
    color: #ffffff !important;
}

section[data-testid="stSidebar"] .stButton > button[kind="primary"] * {
    color: #ffffff !important;
}

[data-testid="stFileUploaderDropzone"] {
    background: rgba(108, 99, 255, 0.05) !important;
    border: 1.5px dashed var(--rc-indigo) !important;
    border-radius: 14px !important;
}

hr { border-color: var(--rc-border) !important; }

.rc-config-alert {
    display: flex; align-items: center; gap: 14px;
    margin: 0 0 18px 0; padding: 14px 18px;
    border: 1px solid rgba(255, 212, 59, 0.35);
    border-radius: 12px; background: rgba(255, 212, 59, 0.08);
}
.rc-config-alert-icon { font-size: 1.35rem; }
.rc-config-alert-title { font-weight: 700; color: var(--rc-text) !important; margin-bottom: 2px; }
.rc-config-alert-text { color: var(--rc-text-dim) !important; font-size: .9rem; }

[data-testid="stHorizontalBlock"] { gap: 0.8rem; }
[data-testid="stMetric"] { min-width: 0 !important; }
[data-testid="stTabs"] { width: 100%; }
[data-baseweb="tab-list"] { gap: 0.25rem; overflow-x: auto; scrollbar-width: thin; }
[data-baseweb="tab"] { white-space: nowrap; padding-left: 0.7rem; padding-right: 0.7rem; color: var(--rc-text-dim) !important; }
[data-baseweb="tab"] p, [data-baseweb="tab"] span { color: inherit !important; }
[data-baseweb="tab"][aria-selected="true"] { color: var(--rc-text) !important; }
[data-testid="stDataFrame"], [data-testid="stPlotlyChart"] { max-width: 100%; overflow-x: auto; }

.rc-file-chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--rc-panel-alt); border: 1px solid var(--rc-border);
    border-radius: 999px; padding: 4px 12px; margin: 3px 6px 3px 0;
    font-size: 0.82rem; color: var(--rc-text-dim) !important;
}
.rc-footer-note { color: var(--rc-text-muted) !important; font-size: 0.8rem; margin-top: 24px; }

/* Streamlit info/caption/help text: force readable contrast without making the UI noisy. */
[data-testid="stAlert"] p,
[data-testid="stAlert"] span,
[data-testid="stAlert"] div,
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span {
    color: var(--rc-text-dim) !important;
}

@media (max-width: 1100px) {
    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] > div { width: 255px !important; }
    [data-testid="stMainBlockContainer"] { padding-left: 1rem; padding-right: 1rem; }
    .rc-hero { padding: 22px 24px; }
    .rc-hero h1 { font-size: 1.8rem; }
}

@media (max-width: 850px) {
    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] > div { width: 240px !important; }
    .rc-hero { padding: 18px; border-radius: 14px; }
    .rc-hero h1 { font-size: 1.55rem; }
    .rc-hero p { font-size: 0.9rem; }
    .rc-metric-card { padding: 14px; }
    .rc-metric-value { font-size: 1.35rem; }
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

SEVERITY_COLOR_HEX = {
    "Critical": "#ff4b4b", "High": "#ff9f43", "Medium": "#ffd43b", "Low": "#20c997",
    "Unknown": "#8899a6",
}


# =============================================================================
# Small render helpers (HTML "components" styled via the CSS above)
# =============================================================================

def badge_html(label: str) -> str:
    color = SEVERITY_COLOR_HEX.get(label, "#8899a6")
    return f'<span class="rc-badge" style="background:{color}22;color:{color};border:1px solid {color}66;">{label}</span>'


def render_metric_card(col, label, value, icon="📊", accent="#00e5ff"):
    with col:
        st.markdown(f"""
        <div class="rc-metric-card" style="--accent:{accent}">
            <div class="rc-metric-icon">{icon}</div>
            <div class="rc-metric-value">{value}</div>
            <div class="rc-metric-label">{label}</div>
        </div>
        """, unsafe_allow_html=True)


def render_finding_card(title, body_lines, badge_label=None):
    badge = badge_html(badge_label) if badge_label else ""
    body_html = "".join(f"<p>{line}</p>" for line in body_lines if line)
    st.markdown(f"""
    <div class="rc-card">
        <h4>{title} {badge}</h4>
        {body_html}
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
# Evidence aggregation (what actually gets sent to the AI — bounded + structured)
# =============================================================================

def _find_column(df: pd.DataFrame, candidates: list[str]):
    """Return the first matching column using normalized names."""
    normalized = {str(c).strip().lower().replace(" ", "_").replace("-", "_"): c for c in df.columns}
    for candidate in candidates:
        key = candidate.strip().lower().replace(" ", "_").replace("-", "_")
        if key in normalized:
            return normalized[key]
    return None



def _framework_key(framework: str) -> str:
    return (framework or "Generic Financial").strip().lower()


def _normalization_key(value) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def _find_any_column(df: pd.DataFrame, candidates: list[str]):
    """Flexible column matcher used by framework-specific heuristics."""
    normalized = {_normalization_key(c): c for c in df.columns}
    for candidate in candidates:
        key = _normalization_key(candidate)
        if key in normalized:
            return normalized[key]
    # Also allow columns whose normalized name contains a candidate token.
    for candidate in candidates:
        token = _normalization_key(candidate)
        for key, original in normalized.items():
            if token in key:
                return original
    return None


def compute_ecommerce_funnel(parsed_files: list) -> dict:
    """Strictly detect Traffic -> Add-to-Cart -> Checkout -> Purchase steps.

    Drop-off is measured as 1 - next_step/current_step. A finding is emitted
    only when adjacent-step drop-off is strictly greater than 15%.
    """
    steps = [
        ("traffic", ["traffic", "sessions", "visits", "site_visits", "visitors"]),
        ("add_to_cart", ["add_to_cart", "add_to_carts", "add_to_cart_count", "cart_adds", "atc"]),
        ("checkout", ["checkout", "checkouts", "checkout_started", "checkout_starts"]),
        ("purchase", ["purchase", "purchases", "orders", "transactions", "completed_orders"]),
    ]

    totals = {key: 0.0 for key, _ in steps}
    matched_sources = {}
    for pf in parsed_files:
        df = pf.get("dataframe") if pf.get("kind") == "csv" else None
        if df is None or df.empty:
            continue
        for key, candidates in steps:
            col = _find_any_column(df, candidates)
            if col is not None:
                values = pd.to_numeric(df[col], errors="coerce").dropna()
                if not values.empty:
                    totals[key] += float(values.sum())
                    matched_sources.setdefault(key, []).append({
                        "filename": pf.get("filename"),
                        "column": str(col),
                    })

    missing = [key for key in totals if totals[key] <= 0]
    if missing:
        return {
            "applicable": False,
            "framework": "E-commerce Funnel",
            "reason": "Strict funnel scan requires Traffic, Add-to-Cart, Checkout, and Purchase metrics.",
            "missing_steps": missing,
            "matched_sources": matched_sources,
        }

    ordered = [key for key, _ in steps]
    dropoffs = []
    for current, nxt in zip(ordered, ordered[1:]):
        current_value, next_value = totals[current], totals[nxt]
        dropoff = max(0.0, 1.0 - next_value / current_value) if current_value else 0.0
        dropoffs.append({
            "from": current,
            "to": nxt,
            "from_count": current_value,
            "to_count": next_value,
            "dropoff_rate": dropoff,
            "dropoff_pct": dropoff * 100.0,
            "exceeds_15_pct": dropoff > 0.15,
        })

    return {
        "applicable": True,
        "framework": "E-commerce Funnel",
        "steps": [{"step": key, "count": totals[key], "sources": matched_sources.get(key, [])}
                  for key in ordered],
        "adjacent_step_dropoffs": dropoffs,
        "threshold_pct": 15.0,
        "high_dropoff_steps": [d for d in dropoffs if d["exceeds_15_pct"]],
        "strict_scan": "Traffic -> Add-to-Cart -> Checkout -> Purchase",
    }


def compute_saas_subscription_metrics(parsed_files: list) -> dict:
    """Detect recurring vs transactional revenue and build identifier/date churn proxies."""
    frames = []
    for pf in parsed_files:
        df = pf.get("dataframe") if pf.get("kind") == "csv" else None
        if df is None or df.empty:
            continue
        user_col = _find_any_column(df, ["user_id", "customer_id", "subscriber_id", "account_id", "user", "customer"])
        date_col = _find_any_column(df, ["date", "datetime", "timestamp", "transaction_date", "period"])
        revenue_col = _find_any_column(df, ["revenue", "amount", "charge", "total", "mrr", "arr"])
        charge_type_col = _find_any_column(df, ["charge_type", "billing_type", "revenue_type", "transaction_type", "type"])
        mrr_col = _find_any_column(df, ["mrr", "monthly_recurring_revenue", "recurring_revenue"])
        if user_col and date_col:
            frames.append((pf.get("filename"), df.copy(), user_col, date_col, revenue_col, charge_type_col, mrr_col))

    if not frames:
        return {
            "applicable": False,
            "framework": "SaaS / Subscription (MRR/Churn)",
            "reason": "Need at least one CSV with a user/customer identifier and date field.",
        }

    recurring_terms = {"mrr", "arr", "recurring", "subscription", "renewal", "monthly", "annual"}
    transactional_terms = {"transactional", "transaction", "one_time", "one-time", "purchase", "charge"}

    recurring_total = transactional_total = 0.0
    classification = []
    cohort_rows = []

    for filename, df, user_col, date_col, revenue_col, charge_type_col, mrr_col in frames:
        dates = pd.to_datetime(df[date_col], errors="coerce")
        valid = df.loc[dates.notna()].copy()
        valid["__date"] = dates.loc[valid.index]
        amount_col = mrr_col or revenue_col

        if amount_col:
            amounts = pd.to_numeric(valid[amount_col], errors="coerce").fillna(0.0)
            label_series = valid[charge_type_col].astype(str).str.lower() if charge_type_col else pd.Series("", index=valid.index)
            recurring_mask = label_series.apply(lambda x: any(term in x for term in recurring_terms))
            transactional_mask = label_series.apply(lambda x: any(term in x for term in transactional_terms))
            if mrr_col:
                recurring_mask = pd.Series(True, index=valid.index)
            recurring_total += float(amounts[recurring_mask].sum())
            transactional_total += float(amounts[transactional_mask & ~recurring_mask].sum())
            classification.append({
                "filename": filename, "amount_column": str(amount_col),
                "recurring_revenue": float(amounts[recurring_mask].sum()),
                "transactional_revenue": float(amounts[transactional_mask & ~recurring_mask].sum()),
            })

        ids = valid[user_col].astype(str).str.strip()
        valid = valid.loc[ids != ""].copy()
        valid["__user"] = ids.loc[valid.index]
        if not valid.empty:
            valid["__period"] = valid["__date"].dt.to_period("M").astype(str)
            activity = valid.groupby(["__user", "__period"]).size().reset_index(name="activity")
            cohort_rows.append(activity)

    churn_proxies = []
    if cohort_rows:
        activity = pd.concat(cohort_rows, ignore_index=True).drop_duplicates(["__user", "__period"])
        periods = sorted(activity["__period"].unique())
        for prev, curr in zip(periods, periods[1:]):
            prev_users = set(activity.loc[activity["__period"] == prev, "__user"])
            curr_users = set(activity.loc[activity["__period"] == curr, "__user"])
            if prev_users:
                retained = prev_users & curr_users
                churned = prev_users - curr_users
                churn_proxies.append({
                    "from_period": prev,
                    "to_period": curr,
                    "starting_users": len(prev_users),
                    "retained_users": len(retained),
                    "churned_users": len(churned),
                    "churn_proxy_rate": len(churned) / len(prev_users),
                    "churn_proxy_pct": len(churned) / len(prev_users) * 100.0,
                })

    return {
        "applicable": True,
        "framework": "SaaS / Subscription (MRR/Churn)",
        "revenue_mix": {
            "recurring_revenue_detected": recurring_total,
            "transactional_revenue_detected": transactional_total,
            "classification": classification,
            "note": "Classification is heuristic and depends on available charge/revenue labels."
        },
        "cohort_churn_proxies": churn_proxies,
        "identifier_date_basis": "user/customer identifier + date grouped into monthly activity cohorts",
    }


def compute_framework_heuristics(parsed_files: list, framework: str) -> dict:
    key = _framework_key(framework)
    if key == "e-commerce funnel":
        return compute_ecommerce_funnel(parsed_files)
    if key == "saas / subscription (mrr/churn)":
        return compute_saas_subscription_metrics(parsed_files)
    if key == "b2b marketing funnel":
        return {
            "applicable": True,
            "framework": "B2B Marketing Funnel",
            "recommended_scan": ["lead", "MQL", "SQL", "opportunity", "closed_won"],
            "note": "Use available lead-stage columns and dates; no generic e-commerce assumptions are applied.",
        }
    return {
        "applicable": True,
        "framework": "Generic Financial",
        "note": "Use financial trends, variance, anomalies, and evidence-linked drivers without imposing a domain-specific funnel.",
    }


def _global_date_bounds(parsed_files: list):
    """Scan every CSV's date-like column and return the overall (min, max) date.

    Used only to set sensible bounds/defaults on the Comparison Mode date
    pickers — it does not affect the driver-tree math itself.
    """
    all_dates = []
    for pf in parsed_files or []:
        df = pf.get("dataframe") if pf.get("kind") == "csv" else None
        if df is None or df.empty:
            continue
        date_col = _find_column(df, ["date", "datetime", "timestamp", "day"])
        if not date_col:
            continue
        parsed_dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if not parsed_dates.empty:
            all_dates.append(parsed_dates.min())
            all_dates.append(parsed_dates.max())
    if not all_dates:
        return None, None
    return min(all_dates).date(), max(all_dates).date()


def _resolve_comparison_ranges():
    """Read the sidebar's Comparison Mode widgets from session_state and return
    (baseline_range, current_range) as (start, end) tuples, or (None, None)
    when Comparison Mode is off or not fully specified (falls back to the
    automatic chronological 50/50 split)."""
    if not st.session_state.get("comparison_mode_enabled"):
        return None, None
    b_start = st.session_state.get("comparison_baseline_start")
    b_end = st.session_state.get("comparison_baseline_end")
    c_start = st.session_state.get("comparison_current_start")
    c_end = st.session_state.get("comparison_current_end")
    if not (b_start and b_end and c_start and c_end):
        return None, None
    return (b_start, b_end), (c_start, c_end)


def compute_driver_tree_attribution(
    parsed_files: list,
    framework: str = "Generic Financial",
    baseline_range: tuple = None,
    current_range: tuple = None,
) -> dict:
    """
    Detect a standard Traffic -> Conversion -> Orders -> Revenue funnel and
    mathematically decompose the revenue change between two comparable periods.

    Revenue is structurally represented as:
        Revenue = Traffic × Conversion Rate × Average Order Value

    A Shapley allocation is used for the final impact shares so the three
    driver contributions reconcile exactly to the modeled revenue change,
    including interaction effects. The requested first-order approximation is
    also returned for auditability.

    By default (baseline_range/current_range both None) the two comparison
    periods are an automatic chronological 50/50 split of every dated
    observation found ("Comparison Mode" off). When both ranges are supplied
    (each an inclusive (start, end) pair of dates/timestamps), those exact
    date windows are used instead — "Comparison Mode" on — for a
    user-controlled "this period vs. that period" comparison.
    """
    if _framework_key(framework) != "generic financial":
        return {
            "applicable": False,
            "framework": framework,
            "reason": "The generic Traffic × Conversion Rate × AOV driver tree is only enabled for Generic Financial.",
        }

    csv_frames = [
        pf["dataframe"].copy()
        for pf in parsed_files
        if pf.get("kind") == "csv" and pf.get("dataframe") is not None and not pf["dataframe"].empty
    ]
    if not csv_frames:
        return {"applicable": False, "reason": "No CSV evidence was provided."}

    # Collect complementary funnel metrics from different CSVs by date.
    # Example: sales.csv supplies Revenue/Orders while ga_export.csv supplies Traffic.
    combined = None
    for df in csv_frames:
        date_col = _find_column(df, ["date", "datetime", "timestamp", "day"])
        revenue_col = _find_column(df, ["revenue", "sales", "total_revenue", "revenue_amount"])
        traffic_col = _find_column(df, ["traffic", "sessions", "visits", "users", "site_visits"])
        orders_col = _find_column(df, ["orders", "order_count", "purchases", "transactions"])
        cvr_col = _find_column(df, ["conversion_rate", "conversion", "cvr"])

        if not date_col or not any([revenue_col, traffic_col, orders_col, cvr_col]):
            continue

        part = pd.DataFrame({"__date": pd.to_datetime(df[date_col], errors="coerce")})
        if revenue_col:
            part["__revenue"] = pd.to_numeric(df[revenue_col], errors="coerce")
        if traffic_col:
            part["__traffic"] = pd.to_numeric(df[traffic_col], errors="coerce")
        if orders_col:
            part["__orders"] = pd.to_numeric(df[orders_col], errors="coerce")
        if cvr_col:
            cvr = pd.to_numeric(df[cvr_col], errors="coerce")
            if cvr.dropna().median() <= 1:
                cvr = cvr * 100
            part["__cvr_source"] = cvr

        part = part.dropna(subset=["__date"])
        numeric_cols = [c for c in part.columns if c != "__date"]
        if not numeric_cols:
            continue
        # Aggregate repeated dates within a source.
        part = part.groupby("__date", as_index=False).agg({c: "sum" for c in numeric_cols})

        if combined is None:
            combined = part
            continue

        combined = combined.merge(part, on="__date", how="outer", suffixes=("", "__new"))
        for base in ["__revenue", "__traffic", "__orders", "__cvr_source"]:
            new_col = base + "__new"
            if new_col in combined.columns:
                if base not in combined.columns:
                    combined[base] = combined[new_col]
                else:
                    # Prefer the first source when both provide the same metric;
                    # fill missing dates from the later source.
                    combined[base] = combined[base].combine_first(combined[new_col])
                combined.drop(columns=[new_col], inplace=True)

    if combined is None:
        return {"applicable": False, "reason": "No dated funnel metrics were found."}

    combined = combined.sort_values("__date")
    if "__orders" not in combined.columns and "__cvr_source" in combined.columns and "__traffic" in combined.columns:
        combined["__orders"] = combined["__traffic"] * combined["__cvr_source"] / 100.0

    required = ["__date", "__revenue", "__traffic", "__orders"]
    if not all(c in combined.columns for c in required):
        return {
            "applicable": False,
            "reason": "Need dated Revenue + Traffic + Orders (or Conversion Rate) across the evidence."
        }

    combined = combined.dropna(subset=["__revenue", "__traffic", "__orders"])
    combined = combined[(combined["__traffic"] > 0) & (combined["__orders"] > 0)]

    use_manual_periods = bool(baseline_range and current_range)

    if use_manual_periods:
        comparison_mode = "manual"
        b_start, b_end = pd.Timestamp(baseline_range[0]), pd.Timestamp(baseline_range[1])
        c_start, c_end = pd.Timestamp(current_range[0]), pd.Timestamp(current_range[1])
        old = combined[(combined["__date"] >= b_start) & (combined["__date"] <= b_end)]
        new = combined[(combined["__date"] >= c_start) & (combined["__date"] <= c_end)]
        if old.empty or new.empty:
            return {
                "applicable": False,
                "comparison_mode": comparison_mode,
                "reason": "No valid dated observations (Revenue + Traffic + Orders) were found in one or "
                          "both of the selected comparison periods. Try widening the date ranges.",
            }
    else:
        comparison_mode = "auto_chronological_split"
        if len(combined) < 4:
            return {"applicable": False, "comparison_mode": comparison_mode,
                     "reason": "At least four valid dated observations are required for a period comparison."}
        # Split chronologically into two comparable periods.
        split = len(combined) // 2
        old = combined.iloc[:split]
        new = combined.iloc[split:]

    def period_metrics(frame):
        traffic = float(frame["__traffic"].sum())
        orders = float(frame["__orders"].sum())
        revenue = float(frame["__revenue"].sum())
        cvr = orders / traffic if traffic else 0.0
        aov = revenue / orders if orders else 0.0
        return {"traffic": traffic, "cvr": cvr, "orders": orders, "aov": aov, "revenue": revenue}

    old_m = period_metrics(old)
    new_m = period_metrics(new)

    def model_revenue(m):
        return m["traffic"] * m["cvr"] * m["aov"]

    old_model = model_revenue(old_m)
    new_model = model_revenue(new_m)
    delta_model = new_model - old_model

    # Exact additive allocation of a multiplicative change across Traffic, CVR and AOV.
    import itertools
    import math
    driver_names = ["traffic", "conversion_rate", "aov"]
    old_values = [old_m["traffic"], old_m["cvr"], old_m["aov"]]
    new_values = [new_m["traffic"], new_m["cvr"], new_m["aov"]]
    shapley = {name: 0.0 for name in driver_names}

    def value(values):
        return values[0] * values[1] * values[2]

    for i, name in enumerate(driver_names):
        others = [j for j in range(3) if j != i]
        for r in range(3):
            for subset in itertools.combinations(others, r):
                values = old_values.copy()
                for j in subset:
                    values[j] = new_values[j]
                before = value(values)
                values[i] = new_values[i]
                after = value(values)
                weight = math.factorial(r) * math.factorial(2 - r) / math.factorial(3)
                shapley[name] += weight * (after - before)

    # The requested first-order rule (with the interaction residual kept separately).
    first_order = {
        "traffic": (new_m["traffic"] - old_m["traffic"]) * old_m["cvr"] * old_m["aov"],
        "conversion_rate": old_m["traffic"] * (new_m["cvr"] - old_m["cvr"]) * old_m["aov"],
        "aov": old_m["traffic"] * old_m["cvr"] * (new_m["aov"] - old_m["aov"]),
    }
    first_order_sum = sum(first_order.values())
    interaction_residual = delta_model - first_order_sum

    def impact_pct(amount):
        return (amount / abs(delta_model) * 100.0) if delta_model else 0.0

    labels = {
        "traffic": "Traffic (Volume)",
        "conversion_rate": "Conversion Rate (Efficiency)",
        "aov": "Average Order Value (Unit Value)",
    }
    attribution = []
    for name in driver_names:
        idx = driver_names.index(name)
        multiplier = 100 if name == "conversion_rate" else 1
        contribution = shapley[name]
        attribution.append({
            "driver": labels[name],
            "key": name,
            "old_value": old_values[idx] * multiplier,
            "new_value": new_values[idx] * multiplier,
            "change": (new_values[idx] - old_values[idx]) * multiplier,
            "exact_revenue_contribution": contribution,
            "impact_share_pct": impact_pct(contribution),
            "first_order_contribution": first_order[name],
            "direction": "negative" if contribution < 0 else ("positive" if contribution > 0 else "neutral"),
        })

    negative = sorted(
        [a for a in attribution if a["exact_revenue_contribution"] < 0],
        key=lambda x: x["exact_revenue_contribution"],
    )
    primary = negative[0] if negative else max(attribution, key=lambda x: x["exact_revenue_contribution"])

    return {
        "applicable": True,
        "method": "Exact Shapley allocation for Traffic × Conversion Rate × AOV",
        "comparison_mode": comparison_mode,
        "periods": {
            "baseline": {"start": old["__date"].min().date().isoformat(), "end": old["__date"].max().date().isoformat()},
            "current": {"start": new["__date"].min().date().isoformat(), "end": new["__date"].max().date().isoformat()},
        },
        "relationship": "Revenue = Traffic × Conversion Rate × Average Order Value",
        "baseline_metrics": {**old_m, "cvr": old_m["cvr"] * 100},
        "current_metrics": {**new_m, "cvr": new_m["cvr"] * 100},
        "actual_revenue_change": new_m["revenue"] - old_m["revenue"],
        "modeled_revenue_change": delta_model,
        "impact_share_basis": "exact driver contribution / absolute modeled revenue change × 100",
        "attributions": attribution,
        "primary_driver": primary,
        "first_order_approximation": first_order,
        "interaction_residual": interaction_residual,
        "reconciliation": sum(shapley.values()),
        # Historical bounds are used exclusively by the local counterfactual
        # simulation sliders. They are derived from the profiled observations,
        # not from arbitrary UI limits.
        "historical_ranges": {
            "traffic": {
                "min": float(combined["__traffic"].min()),
                "max": float(combined["__traffic"].max()),
                "unit": "sessions"
            },
            "conversion_rate": {
                "min": float((combined["__orders"] / combined["__traffic"] * 100.0).min()),
                "max": float((combined["__orders"] / combined["__traffic"] * 100.0).max()),
                "unit": "%"
            },
            "aov": {
                "min": float((combined["__revenue"] / combined["__orders"]).min()),
                "max": float((combined["__revenue"] / combined["__orders"]).max()),
                "unit": "currency/order"
            },
        },
    }



def _high_severity_confirmed(ai_result: dict) -> bool:
    """Return True when the system has confirmed at least one High/Critical problem."""
    if not ai_result:
        return False

    high = {"high", "critical"}

    for item in ai_result.get("anomalies") or []:
        if str(item.get("severity", "")).strip().lower() in high:
            return True

    impact = ai_result.get("impact_assessment") or {}
    if str(impact.get("severity", "")).strip().lower() in high:
        return True

    # Some model responses may use findings/problems instead of anomalies.
    for key in ("findings", "problems", "confirmed_problems"):
        for item in ai_result.get(key) or []:
            if isinstance(item, dict) and str(item.get("severity", "")).strip().lower() in high:
                return True

    return False


_VAGUE_EVIDENCE_PHRASES = {
    "n/a", "na", "none", "unknown", "not specified", "not available", "tbd",
    "insufficient evidence", "see above", "various", "not provided", "no evidence",
    "no evidence provided", "no specific evidence",
}


def _is_evidence_specific(text) -> bool:
    """Heuristic: does this evidence/rationale string look like a concrete
    citation (references a file, number, date, or specific detail) rather
    than a vague placeholder? Pure text heuristic — no AI call involved."""
    if not text:
        return False
    cleaned = str(text).strip()
    if not cleaned or cleaned.lower() in _VAGUE_EVIDENCE_PHRASES:
        return False
    # Very short strings rarely carry a real citation.
    return len(cleaned) >= 12


def compute_evidence_coverage(ai_result: dict) -> dict:
    """
    Scan the AI's own JSON output (anomalies/trigger_events/recommended_actions/
    impact_assessment) and report what fraction of findings cite concrete,
    specific evidence vs. a vague/empty justification. Zero additional AI
    calls — this is a static pass over data already returned by the model.
    """
    if not ai_result or ai_result.get("_parse_failed"):
        return {"applicable": False}

    categories = []

    def _tally(label, items, field):
        items = items or []
        total = len(items)
        cited = sum(1 for it in items if isinstance(it, dict) and _is_evidence_specific(it.get(field)))
        categories.append({"label": label, "total": total, "cited": cited, "vague": total - cited})

    _tally("Anomalies", ai_result.get("anomalies"), "evidence")
    _tally("Trigger Events", ai_result.get("trigger_events"), "evidence")
    _tally("Recommended Actions", ai_result.get("recommended_actions"), "rationale")

    impact = ai_result.get("impact_assessment") or {}
    if impact:
        ok = _is_evidence_specific(impact.get("justification"))
        categories.append({"label": "Impact Assessment", "total": 1, "cited": 1 if ok else 0, "vague": 0 if ok else 1})

    grand_total = sum(c["total"] for c in categories)
    grand_cited = sum(c["cited"] for c in categories)
    coverage_pct = (grand_cited / grand_total * 100.0) if grand_total else 0.0

    return {
        "applicable": grand_total > 0,
        "categories": categories,
        "total": grand_total,
        "cited": grand_cited,
        "vague": grand_total - grand_cited,
        "coverage_pct": coverage_pct,
    }


def render_evidence_coverage(ai_result: dict) -> None:
    """Metric-card summary of the evidence coverage score, plus a per-category breakdown."""
    coverage = compute_evidence_coverage(ai_result)
    if not coverage.get("applicable"):
        return

    st.markdown("### 📐 Evidence Coverage")
    pct = coverage["coverage_pct"]
    accent = "#39d6a8" if pct >= 75 else ("#ffe06a" if pct >= 45 else "#ff6262")

    cols = st.columns(4)
    render_metric_card(cols[0], "Evidence Coverage", f"{pct:.0f}%", "📐", accent)
    for col, cat in zip(cols[1:], coverage["categories"][:3]):
        note = f"{cat['cited']}/{cat['total']} cited"
        render_metric_card(col, cat["label"], note, "🔎", accent)

    if coverage["vague"] > 0:
        st.caption(
            f"{coverage['vague']} of {coverage['total']} findings ({100 - pct:.0f}%) cite vague or missing "
            "evidence rather than a specific, concrete reference. This is a text heuristic over the "
            "model's existing JSON output — no extra AI calls are made."
        )
    else:
        st.caption(
            f"All {coverage['total']} findings cite specific, concrete evidence. "
            "This is a text heuristic over the model's existing JSON output — no extra AI calls are made."
        )


def render_benchmark_check(framework: str, heuristics: dict, driver_tree: dict) -> None:
    """Compare a few concrete computed numbers against this framework's
    benchmark library and flag anything that exceeds the reference threshold."""
    flags = benchmarks.evaluate_against_benchmarks(framework, heuristics, driver_tree)
    if not flags:
        return
    st.markdown("### 📚 Benchmark Check")
    st.caption("Computed figures compared against general industry-typical reference points — "
               "not a verdict, just a quick gut-check.")
    for f in flags:
        icon = "⚠️" if f["flagged"] else "✅"
        st.write(f"{icon} **{f['metric']}**: {f['observed']} (reference: {f['threshold']})")


def render_counter_hypotheses(ai_result: dict) -> None:
    """Render the AI's Devil's Advocate matrix so blind-spot checks are auditable."""
    rows = ai_result.get("counter_hypotheses") if ai_result else None
    if not rows:
        return

    st.markdown("### 🧪 Devil's Advocate — Counter-Hypothesis Verification")
    st.caption(
        "The AI was required to stress-test its top hypotheses against data-supported alternative explanations "
        "before producing the final recommendation."
    )
    for idx, item in enumerate(rows[:3], start=1):
        risk = item.get("falsification_risk_score", "Unknown")
        st.markdown(
            f"**Hypothesis {idx}:** {item.get('original_hypothesis', '')}  \n"
            f"**Alternative explanation:** {item.get('alternative_explanation', '')}  \n"
            f"**Falsification risk:** `{risk}`"
        )
        if idx < len(rows):
            st.divider()


def render_whatif_calculator_body(driver_tree: dict, key_prefix: str = "cf", show_intro: bool = True) -> None:
    """
    Render the local 'What-If' revenue calculator UI.

    The sliders are bounded by historical observations from the profiling phase.
    Revenue is deterministically recomputed as:
        Traffic × Conversion Rate × AOV

    No LLM/API call occurs when a slider moves. `key_prefix` keeps widget keys
    unique when this is rendered in more than one place in the same run
    (e.g. the gated in-analysis simulation and the standalone calculator tab).
    """
    if not driver_tree or not driver_tree.get("applicable"):
        st.info(
            "The Traffic × Conversion Rate × AOV driver tree isn't available for the current "
            "evidence. Upload dated Revenue, Traffic, and Orders (or Conversion Rate) data under "
            "the **Generic Financial** framework to unlock the calculator."
        )
        if driver_tree and driver_tree.get("reason"):
            st.caption(f"Reason: {driver_tree['reason']}")
        return

    baseline = driver_tree["baseline_metrics"]
    current = driver_tree["current_metrics"]
    ranges = driver_tree.get("historical_ranges") or {}

    def bounds(key, current_value):
        r = ranges.get(key) or {}
        lo = float(r.get("min", current_value))
        hi = float(r.get("max", current_value))
        if hi < lo:
            lo, hi = hi, lo
        # Streamlit sliders need a non-zero range for some numeric types.
        if abs(hi - lo) < 1e-12:
            pad = max(abs(lo) * 0.01, 0.01)
            lo, hi = lo - pad, hi + pad
        return lo, hi

    t_lo, t_hi = bounds("traffic", current["traffic"])
    c_lo, c_hi = bounds("conversion_rate", current["cvr"])
    a_lo, a_hi = bounds("aov", current["aov"])

    if show_intro:
        st.markdown("### 🧮 Sales / Revenue Impact Calculator")
    st.caption(
        "What-if analysis you can run anytime — before, during, or after a confirmed problem. "
        "All calculations run locally from the mathematical driver tree; "
        "moving a slider does not call the AI."
    )
    mode_label = "explicit period comparison" if driver_tree.get("comparison_mode") == "manual" else "automatic chronological split"
    st.caption(
        f"Baseline {driver_tree['periods']['baseline']['start']} to {driver_tree['periods']['baseline']['end']} "
        f"vs current {driver_tree['periods']['current']['start']} to {driver_tree['periods']['current']['end']} "
        f"({mode_label})."
    )

    primary = driver_tree.get("primary_driver") or {}
    if primary:
        st.info(
            f"Primary driver: **{primary.get('driver', 'Unknown')}**. "
            "Use the sliders to test how returning a driver toward its historical range "
            "would change projected revenue."
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        sim_traffic = st.slider(
            "Traffic / Volume",
            min_value=float(t_lo),
            max_value=float(t_hi),
            value=float(current["traffic"]),
            key=f"{key_prefix}_traffic",
            help="Historical minimum and maximum observed traffic."
        )
    with c2:
        sim_cvr = st.slider(
            "Conversion Rate (%)",
            min_value=float(c_lo),
            max_value=float(c_hi),
            value=float(current["cvr"]),
            key=f"{key_prefix}_cvr",
            format="%.2f%%",
            help="Historical minimum and maximum observed conversion rate."
        )
    with c3:
        sim_aov = st.slider(
            "Average Order Value",
            min_value=float(a_lo),
            max_value=float(a_hi),
            value=float(current["aov"]),
            key=f"{key_prefix}_aov",
            format="%.2f",
            help="Historical minimum and maximum observed AOV."
        )

    # Deterministic local model. No API, LLM, randomness, or external state.
    simulated_revenue = sim_traffic * (sim_cvr / 100.0) * sim_aov
    current_revenue = float(current["revenue"])
    baseline_revenue = float(baseline["revenue"])
    simulated_delta = simulated_revenue - current_revenue
    vs_baseline_delta = simulated_revenue - baseline_revenue

    st.markdown("---")
    r1, r2, r3 = st.columns(3)
    with r1:
        st.metric("Projected Revenue", f"${simulated_revenue:,.0f}")
    with r2:
        st.metric(
            "Simulated Lift",
            f"${simulated_delta:+,.0f}",
            delta_color="normal"
        )
    with r3:
        st.metric(
            "vs. Historical Baseline",
            f"${vs_baseline_delta:+,.0f}",
            delta_color="normal"
        )

    st.caption(
        f"Formula: {sim_traffic:,.0f} × {sim_cvr:.2f}% × ${sim_aov:,.2f} "
        f"= ${simulated_revenue:,.0f} projected revenue. "
        "The result updates instantly in Python."
    )


def render_counterfactual_simulation(driver_tree: dict, ai_result: dict) -> None:
    """
    Render the What-If calculator inline in the Analysis tab, but only once a
    High/Critical problem has been confirmed by the AI — i.e. "we found a
    real problem, now let's model fixing it". The unrestricted, always-on
    version of the same calculator lives in the standalone "What-If
    Calculator" tab (render_whatif_calculator_body), which needs no
    confirmed finding to use.
    """
    if not driver_tree or not driver_tree.get("applicable"):
        return
    if not _high_severity_confirmed(ai_result):
        return
    st.markdown("### 🎛️ Counterfactual Simulation")
    st.caption("A confirmed High/Critical problem was found — model correcting it below.")
    render_whatif_calculator_body(driver_tree, key_prefix="cf_gated", show_intro=False)


def build_evidence_payload(
    parsed_files: list,
    framework: str = "Generic Financial",
    user_question: str = "",
    driver_tree: dict = None,
) -> dict:
    if driver_tree is None:
        driver_tree = compute_driver_tree_attribution(parsed_files, framework)
    payload = {
        "business_model_framework": framework,
        "user_question": (user_question or "").strip(),
        "framework_heuristics": compute_framework_heuristics(parsed_files, framework),
        "driver_tree_attribution": driver_tree,
        "industry_benchmarks": benchmarks.get_benchmarks_for_framework(framework),
        "files": [],
    }
    for pf in parsed_files:
        entry = {"filename": pf["filename"], "kind": pf["kind"]}

        if pf["kind"] == "csv" and pf["dataframe"] is not None:
            df = pf["dataframe"]
            entry["row_count"] = len(df)
            entry["columns"] = list(df.columns)
            numeric_cols = df.select_dtypes(include="number").columns.tolist()
            if numeric_cols:
                try:
                    entry["numeric_summary"] = df[numeric_cols].describe().round(2).to_dict()
                except Exception:
                    pass
            entry["sample_rows"] = df.head(5).to_dict(orient="records")

        elif pf["kind"] == "eml" and pf.get("structured"):
            entry["email"] = pf["structured"]

        elif pf["kind"] == "log" and pf.get("structured"):
            levels = {}
            for e in pf["structured"]:
                levels[e["level"]] = levels.get(e["level"], 0) + 1
            entry["log_level_counts"] = levels
            entry["total_log_lines"] = len(pf["structured"])
            entry["sample_log_lines"] = pf["structured"][:25]

        elif pf["kind"] == "txt" and pf.get("structured"):
            entry["complaint_entry_count"] = len(pf["structured"])
            entry["sample_entries"] = pf["structured"][:10]

        elif pf.get("raw_text"):
            entry["text_excerpt"] = pf["raw_text"][:3000]

        payload["files"].append(entry)

    return payload


def build_full_timeline(parsed_files: list, ai_result: dict) -> pd.DataFrame:
    frames = []
    for pf in parsed_files:
        if pf["kind"] == "log" and pf.get("structured"):
            frames.append(timeline.build_timeline_from_logs(pf["structured"]))
        elif pf["kind"] == "txt" and pf.get("structured"):
            frames.append(timeline.build_timeline_from_complaints(pf["structured"]))
        elif pf["kind"] == "csv" and pf.get("dataframe") is not None:
            date_col = timeline.guess_date_column(pf["dataframe"])
            if date_col:
                frames.append(timeline.build_timeline_from_dataframe(
                    pf["dataframe"], date_col, category=f"{pf['filename']}"))
    if ai_result and not ai_result.get("_parse_failed"):
        frames.append(timeline.build_timeline_from_ai_events(ai_result.get("timeline_events")))
    return timeline.merge_timelines(*frames)


# =============================================================================
# Session state
# =============================================================================

for key, default in [
    ("business_model_framework", "Generic Financial"),
    ("user_question", ""),
    ("parsed_files", []), ("ai_result", None), ("timeline_df", None),
    ("driver_tree", None), ("last_run_at", None), ("parse_errors", []),
    ("ai_config_error", False), ("last_run_error", None),
    ("alert_results", []), ("connector_error", None),
    ("current_incident_id", None), ("severity_info", None), ("confidence_info", None),
    ("evidence_source_coverage", None), ("data_quality", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# =============================================================================
# Sidebar
# =============================================================================

with st.sidebar:
    st.markdown("### 🧬 Root Cause AI")
    st.caption("Evidence in. Root cause out.")
    st.divider()

    st.divider()

    st.markdown("#### 🧭 Business Model Framework")
    business_model_framework = st.selectbox(
        "Business Model Framework",
        options=BUSINESS_MODEL_FRAMEWORKS,
        index=BUSINESS_MODEL_FRAMEWORKS.index(st.session_state.business_model_framework),
        key="business_model_framework",
        help="Mandatory: selects the domain-specific heuristic engine and consulting persona.",
    )
    st.caption("📚 See the **Investigation** tab for this framework's benchmark reference thresholds.")

    st.markdown("#### 📊 Comparison Mode")
    comparison_mode_enabled = st.checkbox(
        "Compare two explicit periods",
        value=st.session_state.get("comparison_mode_enabled", False),
        key="comparison_mode_enabled",
        help="Off: the driver tree auto-splits your dated evidence 50/50 (oldest half vs. newest half). "
             "On: pick exact 'this period vs. that period' date ranges yourself — "
             "e.g. this month vs. last month.",
    )
    if comparison_mode_enabled:
        bounds_lo, bounds_hi = _global_date_bounds(st.session_state.get("parsed_files", []))
        default_lo = bounds_lo or datetime(2024, 1, 1).date()
        default_hi = bounds_hi or datetime(2024, 1, 31).date()
        default_mid = default_lo + (default_hi - default_lo) / 2

        st.caption("Baseline period (e.g. last month)")
        bcol1, bcol2 = st.columns(2)
        with bcol1:
            st.date_input(
                "Baseline start", key="comparison_baseline_start",
                value=st.session_state.get("comparison_baseline_start", default_lo),
                min_value=bounds_lo, max_value=bounds_hi,
                label_visibility="collapsed",
            )
        with bcol2:
            st.date_input(
                "Baseline end", key="comparison_baseline_end",
                value=st.session_state.get("comparison_baseline_end", default_mid),
                min_value=bounds_lo, max_value=bounds_hi,
                label_visibility="collapsed",
            )
        st.caption("Comparison period (e.g. this month)")
        ccol1, ccol2 = st.columns(2)
        with ccol1:
            st.date_input(
                "Current start", key="comparison_current_start",
                value=st.session_state.get("comparison_current_start", default_mid),
                min_value=bounds_lo, max_value=bounds_hi,
                label_visibility="collapsed",
            )
        with ccol2:
            st.date_input(
                "Current end", key="comparison_current_end",
                value=st.session_state.get("comparison_current_end", default_hi),
                min_value=bounds_lo, max_value=bounds_hi,
                label_visibility="collapsed",
            )
        if bounds_lo is None:
            st.caption("Load or upload dated evidence to see available date bounds here.")

    st.markdown("#### ❓ Ask a Question About Your Data")
    st.caption("Optional: ask anything about the uploaded evidence before running the analysis.")
    user_question = st.text_area(
        "Your data question",
        value=st.session_state.user_question,
        key="user_question",
        height=130,
        label_visibility="visible",
        placeholder=(
            "Example: Why did revenue drop on 2026-09-04?\n"
            "Which factor had the biggest impact?\n"
            "What should we investigate first?"
        ),
        help="Optional. Your question is sent to Groq together with the evidence so the analysis directly answers it.",
    )

    st.markdown("#### 📁 Upload Evidence")
    uploaded_files = st.file_uploader(
        "CSV, PDF, DOCX, TXT, or .eml files",
        type=ACCEPTED_TYPES,
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    st.caption("Accepted: .csv .pdf .docx .txt .eml — multiple files at once.")

    st.markdown("#### 🔌 Or Pull From a Connected Source")
    connector_config = connectors.get_connector_config()
    connector_choice = st.selectbox(
        "Data connector",
        options=["None", "Google Sheet", "Database Query", "Stripe", "Google Analytics 4"],
        key="connector_choice",
        label_visibility="collapsed",
    )
    connector_fetch_clicked = False
    connector_fetch_fn = None

    if connector_choice == "Google Sheet":
        st.caption("Sheet must be shared as 'Anyone with the link can view'. No credentials needed.")
        sheet_url = st.text_input("Google Sheet URL or ID", key="connector_sheet_url",
                                   placeholder="https://docs.google.com/spreadsheets/d/...")
        connector_fetch_clicked = st.button("📥 Fetch Sheet", use_container_width=True, key="fetch_sheet_btn")
        connector_fetch_fn = lambda: connectors.fetch_google_sheet(sheet_url)

    elif connector_choice == "Database Query":
        if connector_config.database_configured:
            st.caption("✅ Database connection configured.")
        else:
            st.caption("⚠️ No database connection configured. Set `DATABASE_URL` in your environment or Streamlit secrets.")
        db_query = st.text_area("SQL query (SELECT/WITH only)", key="connector_db_query", height=90,
                                 placeholder="SELECT date, revenue, orders FROM sales ORDER BY date")
        connector_fetch_clicked = st.button("📥 Run Query", use_container_width=True, key="fetch_db_btn",
                                             disabled=not connector_config.database_configured)
        connector_fetch_fn = lambda: connectors.fetch_database_query(connector_config.database_url, db_query)

    elif connector_choice == "Stripe":
        if connector_config.stripe_configured:
            st.caption("✅ Stripe connection configured.")
        else:
            st.caption("⚠️ No Stripe key configured. Set `STRIPE_API_KEY` in your environment or Streamlit secrets.")
        stripe_lookback = st.slider("Lookback (days)", 7, 365, 90, key="connector_stripe_lookback")
        connector_fetch_clicked = st.button("📥 Fetch Stripe Revenue", use_container_width=True, key="fetch_stripe_btn",
                                             disabled=not connector_config.stripe_configured)
        connector_fetch_fn = lambda: connectors.fetch_stripe_revenue(connector_config.stripe_api_key, stripe_lookback)

    elif connector_choice == "Google Analytics 4":
        if connector_config.ga4_configured:
            st.caption("✅ GA4 connection configured.")
        else:
            st.caption("⚠️ No GA4 connection configured. Set `GA4_PROPERTY_ID` / `GA4_CREDENTIALS_PATH` in your environment or Streamlit secrets.")
        ga4_lookback = st.slider("Lookback (days)", 7, 365, 90, key="connector_ga4_lookback")
        connector_fetch_clicked = st.button("📥 Fetch GA4 Traffic", use_container_width=True, key="fetch_ga4_btn",
                                             disabled=not connector_config.ga4_configured)
        connector_fetch_fn = lambda: connectors.fetch_ga4_traffic(
            connector_config.ga4_property_id, connector_config.ga4_credentials_path, ga4_lookback)

    if st.session_state.get("connector_error"):
        st.error(st.session_state["connector_error"])

    load_sample = st.button("🎬 Load Sample Incident Bundle", use_container_width=True)

    st.divider()
    run_clicked = st.button("🚀 Run Root Cause Analysis", type="primary", use_container_width=True)
    reset_clicked = st.button("🗑️ Clear Session", use_container_width=True)




# =============================================================================
# Sidebar button handling
# =============================================================================

if reset_clicked:
    st.session_state.parsed_files = []
    # FIX #2: assigning to st.session_state.user_question here raises
    # StreamlitAPIException, because the st.text_area(key="user_question")
    # widget above has already been instantiated earlier in this same script
    # run. Deleting the key is allowed post-instantiation; on st.rerun() the
    # widget reinitializes to its default value ("").
    if "user_question" in st.session_state:
        del st.session_state["user_question"]
    st.session_state.ai_result = None
    st.session_state.ai_config_error = False
    st.session_state.timeline_df = None
    st.session_state.driver_tree = None
    st.session_state.last_run_at = None
    st.session_state.parse_errors = []
    st.session_state.last_run_error = None  # also clear any stale error banner
    st.session_state.connector_error = None
    st.session_state.alert_results = []
    st.session_state.current_incident_id = None
    st.session_state.severity_info = None
    st.session_state.confidence_info = None
    st.session_state.evidence_source_coverage = None
    st.session_state.data_quality = None
    st.rerun()

if connector_fetch_clicked and connector_fetch_fn is not None:
    try:
        fetched = connector_fetch_fn()
        st.session_state.parsed_files = st.session_state.parsed_files + [fetched]
        st.session_state.connector_error = None
        st.session_state.ai_result = None
        st.session_state.timeline_df = None
        st.session_state.ai_config_error = False
        st.session_state.current_incident_id = None
    except ValueError as e:
        st.session_state.connector_error = str(e)
    except Exception as e:
        st.session_state.connector_error = f"{type(e).__name__}: {e}"
    st.rerun()

if load_sample:
    parsed, errors = [], []
    for fname in SAMPLE_FILES:
        path = os.path.join(SAMPLE_DIR, fname)
        if not os.path.exists(path):
            errors.append(f"Sample file missing: {fname}")
            continue
        try:
            parsed.append(parsers.parse_uploaded_file(LocalFileWrapper(path)))
        except ValueError as e:
            errors.append(str(e))
    st.session_state.parsed_files = parsed
    st.session_state.parse_errors = errors
    st.session_state.ai_result = None
    st.session_state.timeline_df = None
    st.session_state.ai_config_error = False
    st.session_state.current_incident_id = None
    st.rerun()

if run_clicked:
    files_to_parse = uploaded_files or []
    parsed, errors = [], []

    # Reuse already-loaded sample files if the user hasn't uploaded anything new.
    if not files_to_parse and st.session_state.parsed_files:
        parsed = st.session_state.parsed_files
    elif not files_to_parse:
        st.sidebar.error("Please upload at least one file, or load the sample bundle, first.")
    else:
        for f in files_to_parse:
            try:
                parsed.append(parsers.parse_uploaded_file(f))
            except ValueError as e:
                errors.append(str(e))

    st.session_state.parsed_files = parsed
    st.session_state.parse_errors = errors

    if parsed:
        try:
            with st.spinner("Parsing evidence and consulting Root Cause AI..."):
                client = get_client()
                baseline_range, current_range = _resolve_comparison_ranges()
                driver_tree = compute_driver_tree_attribution(
                    parsed, st.session_state.business_model_framework,
                    baseline_range, current_range,
                )
                payload = build_evidence_payload(
                    parsed,
                    st.session_state.business_model_framework,
                    st.session_state.user_question,
                    driver_tree=driver_tree,
                )
                st.session_state.driver_tree = driver_tree
                ai_result = analyze_root_cause(client, payload)
            st.session_state.ai_result = ai_result
            st.session_state.timeline_df = build_full_timeline(parsed, ai_result)
            st.session_state.last_run_at = datetime.now()
            st.session_state.ai_config_error = False
            st.session_state.last_run_error = None
            st.sidebar.success("Analysis complete — see the results in the tabs below.")

            # Deterministic post-processing: severity, confidence, and evidence
            # coverage are all calculated here in Python — never asked of the
            # LLM directly — then persisted as a new incident so status and
            # remediation actions can be tracked over time (Overview/Actions tabs).
            data_quality = quality.assess_data_quality(parsed)
            evidence_source_coverage = quality.compute_evidence_source_coverage(parsed)
            severity_info = quality.compute_deterministic_severity(
                driver_tree, compute_framework_heuristics(parsed, st.session_state.business_model_framework),
            )
            citation_coverage = compute_evidence_coverage(ai_result)
            confidence_info = quality.compute_root_cause_confidence(
                ai_result, driver_tree,
                citation_coverage.get("coverage_pct", 0.0) if citation_coverage.get("applicable") else 0.0,
            )
            st.session_state.data_quality = data_quality
            st.session_state.evidence_source_coverage = evidence_source_coverage
            st.session_state.severity_info = severity_info
            st.session_state.confidence_info = confidence_info

            primary_root_cause = None
            if driver_tree and driver_tree.get("applicable"):
                primary_root_cause = driver_tree["primary_driver"]["driver"]
            elif ai_result.get("trigger_events"):
                primary_root_cause = ai_result["trigger_events"][0].get("event")

            revenue_impact = driver_tree.get("actual_revenue_change") if (driver_tree and driver_tree.get("applicable")) else None

            st.session_state.current_incident_id = incident_store.save_incident(
                framework=st.session_state.business_model_framework,
                severity=severity_info["level"],
                severity_reason=severity_info["reason"],
                confidence=confidence_info["overall"],
                revenue_impact=revenue_impact,
                primary_root_cause=primary_root_cause or "Undetermined",
                summary=ai_result.get("summary", ""),
                source_files=[pf["filename"] for pf in parsed],
            )

            # Alerting/webhooks: auto-notify configured Slack/email sinks the
            # moment a run confirms a High/Critical finding. Best-effort —
            # a failed webhook/SMTP call never breaks the analysis itself.
            confirmed = _high_severity_confirmed(ai_result)
            alert_results = alerts.maybe_send_alerts(
                ai_result, [pf["filename"] for pf in parsed], confirmed,
            )
            st.session_state.alert_results = alert_results
            if confirmed and alert_results:
                for r in alert_results:
                    if r.sent:
                        st.sidebar.info(f"🔔 Alert sent via {r.sink}.")
                    else:
                        st.sidebar.warning(f"🔔 {r.sink} alert not sent: {r.detail}")
        except GroqClientError as e:
            # The end-user banner stays generic on purpose, but we keep the real
            # message so it's visible right where the click happened, and so it
            # can be diagnosed instead of silently vanishing.
            st.session_state.ai_result = None
            st.session_state.ai_config_error = True
            st.session_state.last_run_error = str(e)
            st.sidebar.error(f"Analysis failed: {e}")
        except Exception as e:
            # Anything unexpected (bad data, a code bug, etc.) used to crash
            # silently or produce no visible feedback at all. Surface it instead.
            st.session_state.ai_result = None
            st.session_state.ai_config_error = False
            st.session_state.last_run_error = f"{type(e).__name__}: {e}"
            st.sidebar.error(f"Analysis failed unexpectedly: {type(e).__name__}: {e}")


# =============================================================================
# Header
# =============================================================================

st.markdown("""
<div class="rc-hero">
    <h1>🧬 Root Cause AI</h1>
    <p>Upload the evidence. Let AI trace the trigger event, assess impact, and hand you an action plan — grounded only in what you gave it.</p>
</div>
""", unsafe_allow_html=True)

if st.session_state.parse_errors:
    for err in st.session_state.parse_errors:
        st.error(err)

parsed_files = st.session_state.parsed_files
ai_result = st.session_state.ai_result
selected_framework = st.session_state.business_model_framework
st.caption(f"Business Model Framework: **{selected_framework}**")
if st.session_state.user_question.strip():
    st.markdown(
        f"<div class=\"rc-question-card\"><strong>❓ Your question</strong><br>{st.session_state.user_question.strip()}</div>",
        unsafe_allow_html=True,
    )
timeline_df = st.session_state.timeline_df

# The driver tree (and therefore the What-If Calculator) is recomputed live
# from whatever evidence + comparison settings are currently loaded, so it's
# available to explore any time — not only after a confirmed AI finding.
if parsed_files:
    _baseline_range, _current_range = _resolve_comparison_ranges()
    driver_tree = compute_driver_tree_attribution(
        parsed_files, selected_framework, _baseline_range, _current_range,
    )
    st.session_state.driver_tree = driver_tree
else:
    driver_tree = None

ai_config = get_ai_config()

if (not ai_config.configured) or st.session_state.get("ai_config_error", False):
    st.markdown("""
    <div class="rc-config-alert">
        <div class="rc-config-alert-icon">⚙️</div>
        <div>
            <div class="rc-config-alert-title">System configuration in progress. Configure the analysis engine with `GROQ_API_KEY` in your environment or Streamlit secrets.</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if not ai_config.configured:
        st.caption(
            "Add `GROQ_API_KEY` to Streamlit secrets or your environment variables, "
            "then restart the app."
        )
    if st.session_state.get("last_run_error"):
        with st.expander("Technical details"):
            st.code(st.session_state["last_run_error"])

# =============================================================================
# Metrics row
# =============================================================================

total_files = len(parsed_files)
total_rows = sum(len(pf["dataframe"]) for pf in parsed_files if pf.get("dataframe") is not None)
total_events = 0
for pf in parsed_files:
    if pf.get("structured") and isinstance(pf["structured"], list):
        total_events += len(pf["structured"])
analysis_status = "Complete" if (ai_result and not ai_result.get("_parse_failed")) else (
    "Needs review" if ai_result else "Not run"
)

m1, m2, m3, m4 = st.columns(4)
render_metric_card(m1, "Files Loaded", total_files, "📁", "#00e5ff")
render_metric_card(m2, "Data Rows", f"{total_rows:,}", "📊", "#00d9a3")
render_metric_card(m3, "Parsed Events", f"{total_events:,}", "🧾", "#6c63ff")
render_metric_card(m4, "Analysis Status", analysis_status, "🩺", "#ff9f43")

if parsed_files:
    chips = " ".join(f'<span class="rc-file-chip">📄 {pf["filename"]}</span>' for pf in parsed_files)
    st.markdown(chips, unsafe_allow_html=True)

st.write("")


# =============================================================================
# Tabs
# =============================================================================

tab_overview, tab_investigation, tab_evidence, tab_impact, tab_timeline, tab_actions, tab_reports = st.tabs(
    ["🧭 Overview", "🔍 Investigation", "📁 Evidence", "🧮 Impact & Simulation",
     "📈 Timeline", "✅ Actions", "📤 Reports"]
)


# --- Tab: Overview -----------------------------------------------------------
with tab_overview:
    if not parsed_files:
        st.info("Upload evidence (or load the sample bundle) in the sidebar, then run the analysis to see the executive overview here.")
    elif ai_result is None:
        st.info("Evidence is loaded. Click **🚀 Run Root Cause Analysis** in the sidebar to populate this dashboard.")
    elif ai_result.get("_parse_failed"):
        st.warning("The AI response couldn't be parsed as valid JSON. See the Investigation tab for raw output.")
    else:
        severity_info = st.session_state.get("severity_info") or {"level": "LOW", "reason": "Not computed."}
        confidence_info = st.session_state.get("confidence_info") or {"overall": 0, "components": {}}
        evidence_src = st.session_state.get("evidence_source_coverage") or {}
        incident_id = st.session_state.get("current_incident_id")

        sev_level = severity_info["level"]
        sev_icon = quality.SEVERITY_ICON.get(sev_level, "⚪")
        sev_color = quality.SEVERITY_COLOR.get(sev_level, "#888")

        top1, top2 = st.columns([2, 1])
        with top1:
            st.markdown(
                f"<div style='padding:14px 18px;border-radius:10px;background:rgba(255,255,255,0.03);"
                f"border-left:5px solid {sev_color};'>"
                f"<div style='font-size:0.85rem;opacity:0.7;'>🧮 Deterministic — computed from evidence, not the AI's opinion</div>"
                f"<div style='font-size:1.4rem;font-weight:700;'>{sev_icon} Severity: {sev_level}</div>"
                f"<div style='opacity:0.85;margin-top:4px;'>{severity_info['reason']}</div>"
                f"</div>", unsafe_allow_html=True,
            )
        with top2:
            if incident_id:
                current_incident = incident_store.get_incident(incident_id)
                current_status = current_incident["status"] if current_incident else incident_store.STATUS_WORKFLOW[0]
                new_status = st.selectbox(
                    "Incident Status",
                    options=incident_store.STATUS_WORKFLOW,
                    index=incident_store.STATUS_WORKFLOW.index(current_status),
                    key=f"status_select_{incident_id}",
                )
                if new_status != current_status:
                    incident_store.update_incident_status(incident_id, new_status)
                    st.rerun()
            else:
                st.caption("Status tracking unavailable — no persisted incident yet.")

        st.write("")
        oc1, oc2, oc3 = st.columns(3)
        revenue_impact = driver_tree.get("actual_revenue_change") if (driver_tree and driver_tree.get("applicable")) else None
        render_metric_card(
            oc1, "Revenue Impact",
            f"${revenue_impact:,.0f}" if revenue_impact is not None else "N/A",
            "💰", sev_color,
        )
        render_metric_card(oc2, "Root Cause Confidence", f"{confidence_info['overall']:.0f}%", "🧮", "#6c63ff")
        render_metric_card(oc3, "Evidence Coverage", f"{evidence_src.get('score', 0):.0f}% · {evidence_src.get('label', 'N/A')}", "📐", "#00d9a3")

        st.markdown("### Root Cause Confidence — component breakdown")
        st.caption("🧮 Deterministic components below; the AI is used only to *explain* this score afterward, never to set it.")
        comp_labels = {
            "evidence_support": "Evidence Support",
            "driver_contribution": "Driver Contribution",
            "alternative_risk": "Alternative-Hypothesis Risk (inverted)",
            "temporal_alignment": "Temporal Alignment",
        }
        for key, label in comp_labels.items():
            val = confidence_info["components"].get(key)
            if val is None:
                st.progress(0, text=f"{label}: not available from current evidence")
            else:
                st.progress(min(1.0, val / 100.0), text=f"{label}: {val:.0f}%")

        st.markdown("### Primary Root Cause")
        primary_label = "Undetermined"
        if driver_tree and driver_tree.get("applicable"):
            primary_label = driver_tree["primary_driver"]["driver"]
        elif ai_result.get("trigger_events"):
            primary_label = ai_result["trigger_events"][0].get("event", "Undetermined")
        st.markdown(f"**{primary_label}**")

        why_bullets = []
        if driver_tree and driver_tree.get("applicable"):
            p = driver_tree["primary_driver"]
            why_bullets.append(f"Mathematically the largest driver of the revenue change ({p['impact_share_pct']:+.1f}% impact share).")
        if ai_result.get("anomalies"):
            top_a = ai_result["anomalies"][0]
            why_bullets.append(f"Anomaly detected: {top_a.get('description', '')}")
        if ai_result.get("trigger_events"):
            top_t = ai_result["trigger_events"][0]
            why_bullets.append(f"Trigger event: {top_t.get('event', '')} (confidence: {top_t.get('confidence', 'Unknown')})")
        counter = ai_result.get("counter_hypotheses") or []
        if counter:
            top_c = counter[0]
            risk = str(top_c.get("falsification_risk_score", "")).strip().lower()
            if risk == "low":
                why_bullets.append("Alternative explanations were stress-tested and did not hold up (falsification risk: Low).")
            else:
                why_bullets.append(f"An alternative explanation exists with {top_c.get('falsification_risk_score', 'Unknown')} falsification risk — see Investigation tab.")
        if not why_bullets:
            why_bullets.append("Insufficient evidence to explain this ranking — see the Investigation tab for details.")
        st.markdown("**Why?**")
        for b in why_bullets:
            st.markdown(f"✓ {b}")

        if driver_tree and driver_tree.get("applicable"):
            st.markdown("### Top Contributing Factors")
            ranked = sorted(driver_tree["attributions"], key=lambda x: abs(x["impact_share_pct"]), reverse=True)
            for item in ranked:
                st.write(f"**{item['driver']}** — {item['impact_share_pct']:+.1f}% impact share (${item['exact_revenue_contribution']:,.0f})")

        st.markdown("### Recommended Actions")
        if ai_result.get("recommended_actions"):
            for r in ai_result["recommended_actions"][:3]:
                icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(str(r.get("priority", "")).lower(), "⚪")
                st.write(f"{icon} {r.get('action', '')}")
            st.caption("Full list with rationale is in the Investigation tab; track these in the Actions tab.")
        else:
            st.caption("No recommended actions were generated.")

        if incident_id:
            similar = incident_store.find_similar_incidents(selected_framework, primary_label, exclude_id=incident_id)
            if similar:
                with st.expander(f"🕓 {len(similar)} similar previous incident(s) found"):
                    for s in similar:
                        st.write(f"**#{s['id']}** · {s['created_at']} · {s['severity']} · {s['primary_root_cause']} · status: {s['status']}")


# --- Tab: Evidence -----------------------------------------------------------
with tab_evidence:
    if not parsed_files:
        st.info("Upload evidence in the sidebar (or load the sample bundle) to see a preview here.")
    else:
        st.markdown("### 🧪 Data Quality")
        st.caption("🧮 Deterministic checks — missing values, duplicates, invalid dates, type mismatches, outliers. Never blocks analysis, informational only.")
        dq = quality.assess_data_quality(parsed_files)
        if dq["applicable"]:
            st.metric("Overall Data Quality", f"{dq['overall_score']:.0f}%")
            for f in dq["files"]:
                with st.expander(f"{f['filename']} — {f['rows']:,} rows × {f['columns']} cols · quality {f['score']:.0f}%"):
                    for finding in f["findings"]:
                        icon = {"ERROR": "❌", "WARNING": "⚠️", "INFO": "✓"}.get(finding["level"], "•")
                        st.write(f"{icon} {finding['message']}")
        else:
            st.caption("No CSV evidence to run data-quality checks against.")

        st.markdown("### 📐 Evidence Source Coverage")
        st.caption("🧮 Deterministic — which categories of evidence are present at all (not whether the AI cited them well).")
        esc = quality.compute_evidence_source_coverage(parsed_files)
        st.metric("Evidence Coverage", f"{esc['score']:.0f}% — {esc['label']}")
        for item in esc["checklist"]:
            st.write(f"{'✓' if item['present'] else '⚠'} {item['label']}")
        if esc.get("note"):
            st.caption(esc["note"])

        st.markdown("### 📄 Uploaded / Connected Files")
        for pf in parsed_files:
            with st.expander(f"📄 {pf['filename']}  ·  {pf['kind'].upper()}", expanded=False):
                if pf["kind"] == "csv" and pf["dataframe"] is not None:
                    df = pf["dataframe"]
                    st.caption(f"{len(df):,} rows × {len(df.columns)} columns")
                    st.dataframe(df.head(25), use_container_width=True)
                elif pf["kind"] == "eml" and pf.get("structured"):
                    s = pf["structured"]
                    st.markdown(f"**From:** {s['from']}  \n**To:** {s['to']}  \n"
                               f"**Subject:** {s['subject']}  \n**Date:** {s['date']}")
                    st.text_area("Body", s["body"], height=180, key=f"eml_{pf['filename']}")
                elif pf["kind"] == "log" and pf.get("structured"):
                    log_df = pd.DataFrame(pf["structured"])
                    st.caption(f"{len(log_df):,} log lines parsed")
                    st.dataframe(log_df.head(50), use_container_width=True)
                elif pf["kind"] == "txt" and pf.get("structured"):
                    st.caption(f"{len(pf['structured']):,} entries detected")
                    st.dataframe(pd.DataFrame(pf["structured"]).head(50), use_container_width=True)
                elif pf.get("raw_text"):
                    st.text_area("Extracted text", pf["raw_text"][:5000], height=220, key=f"txt_{pf['filename']}")


# --- Tab: Investigation -------------------------------------------------------
with tab_investigation:
    if not parsed_files:
        st.info("Upload evidence and click **Run Root Cause Analysis** in the sidebar to begin.")
    elif ai_result is None:
        st.info("Files are loaded. Click **🚀 Run Root Cause Analysis** in the sidebar to analyze them.")
    elif ai_result.get("_parse_failed"):
        st.warning("The AI response couldn't be parsed as valid JSON. Raw output below.")
        st.code(ai_result.get("_raw_text", ""))
    else:
        st.markdown("### ❓ Answer to Your Data Question")
        if st.session_state.user_question.strip():
            st.info(ai_result.get("question_answer", "No direct answer was returned by the analysis engine."))
        else:
            st.caption("No question was entered. The AI performed a general root-cause review.")

        st.markdown("### Summary")
        st.write(ai_result.get("summary", ""))

        if st.session_state.get("alert_results"):
            sent = [r for r in st.session_state["alert_results"] if r.sent]
            failed = [r for r in st.session_state["alert_results"] if not r.sent]
            if sent:
                st.caption("🔔 " + "; ".join(f"Alert sent via {r.sink}" for r in sent))
            if failed:
                st.caption("⚠️ " + "; ".join(f"{r.sink} alert failed: {r.detail}" for r in failed))

        render_evidence_coverage(ai_result)

        render_benchmark_check(
            selected_framework,
            compute_framework_heuristics(parsed_files, selected_framework),
            driver_tree,
        )

        if driver_tree and driver_tree.get("applicable"):
            st.markdown("### 🌳 Mathematical Driver Tree")
            mode_note = "explicit period comparison" if driver_tree.get("comparison_mode") == "manual" else "automatic chronological split"
            st.caption(
                f"{driver_tree['relationship']} · "
                f"Baseline {driver_tree['periods']['baseline']['start']} to {driver_tree['periods']['baseline']['end']} "
                f"vs current {driver_tree['periods']['current']['start']} to {driver_tree['periods']['current']['end']} "
                f"({mode_note})"
            )
            dt_cols = st.columns(3)
            for col, item in zip(dt_cols, driver_tree["attributions"]):
                with col:
                    sign = "+" if item["exact_revenue_contribution"] >= 0 else ""
                    st.metric(
                        item["driver"],
                        f"{item['impact_share_pct']:+.1f}%",
                        f"${sign}{item['exact_revenue_contribution']:,.0f} revenue impact",
                        delta_color="normal",
                    )
            primary = driver_tree["primary_driver"]
            st.warning(
                f"Primary mathematical driver: **{primary['driver']}** "
                f"({primary['impact_share_pct']:+.1f}% impact share). "
                "The AI analysis is instructed to prioritize this branch when interpreting root cause evidence."
            )
            with st.expander("Driver Tree calculation details", expanded=False):
                st.json({
                    "baseline_metrics": driver_tree["baseline_metrics"],
                    "current_metrics": driver_tree["current_metrics"],
                    "actual_revenue_change": driver_tree["actual_revenue_change"],
                    "modeled_revenue_change": driver_tree["modeled_revenue_change"],
                    "interaction_residual": driver_tree["interaction_residual"],
                    "reconciliation": driver_tree["reconciliation"],
                    "historical_ranges": driver_tree.get("historical_ranges", {}),
                })

            render_counter_hypotheses(ai_result)
            render_counterfactual_simulation(driver_tree, ai_result)

        st.markdown("### 🚨 Anomalies Detected")
        if ai_result.get("anomalies"):
            for a in ai_result["anomalies"]:
                render_finding_card(
                    a.get("description", "Anomaly"),
                    [f'<span class="rc-evidence">Evidence: {a.get("evidence", "")}</span>'],
                    badge_label=a.get("severity", "Unknown"),
                )
        else:
            st.caption("No anomalies were surfaced from the evidence provided.")

        st.markdown("### 🎯 Trigger Events")
        if ai_result.get("trigger_events"):
            for t in ai_result["trigger_events"]:
                render_finding_card(
                    t.get("event", "Trigger event"),
                    [f"Time: {t.get('timestamp_or_period', 'unknown')}",
                     f'<span class="rc-evidence">Evidence: {t.get("evidence", "")}</span>'],
                    badge_label=t.get("confidence", "Unknown"),
                )
        else:
            st.caption("No specific trigger event could be isolated from the evidence provided.")

        st.markdown("### 📊 Impact Assessment")
        ia = ai_result.get("impact_assessment") or {}
        if ia:
            render_finding_card(
                ia.get("category", "Impact"),
                [ia.get("justification", "")],
                badge_label=ia.get("severity", "Unknown"),
            )

        st.markdown("### ✅ Recommended Actions")
        if ai_result.get("recommended_actions"):
            for r in ai_result["recommended_actions"]:
                render_finding_card(
                    r.get("action", "Action"),
                    [f'<span class="rc-evidence">Rationale: {r.get("rationale", "")}</span>'],
                    badge_label=r.get("priority", "Unknown"),
                )
        else:
            st.caption("No recommended actions were generated.")

        st.divider()
        st.markdown("### 📚 Benchmark Library")
        st.caption(
            f"📊 Industry-typical reference thresholds for the **{selected_framework}** framework. "
            "General rules of thumb, not a guarantee for any specific business — the AI "
            "uses them only to calibrate severity language, never as a substitute for your actual evidence."
        )
        benchmark_rows = benchmarks.get_benchmarks_for_framework(selected_framework)
        if benchmark_rows:
            st.dataframe(pd.DataFrame(benchmark_rows), hide_index=True, use_container_width=True)
        else:
            st.info("No benchmark reference points are defined for this framework yet.")

        st.markdown("#### ⚠️ Your Evidence vs. Benchmark")
        heuristics_for_flags = compute_framework_heuristics(parsed_files, selected_framework)
        flags = benchmarks.evaluate_against_benchmarks(selected_framework, heuristics_for_flags, driver_tree)
        if flags:
            flag_df = pd.DataFrame(flags)
            flag_df["flagged"] = flag_df["flagged"].map(lambda v: "⚠️ Exceeds benchmark" if v else "✅ Within range")
            flag_df = flag_df.rename(columns={
                "metric": "Metric", "observed": "Observed", "threshold": "Benchmark", "flagged": "Status",
            })
            st.dataframe(flag_df, hide_index=True, use_container_width=True)
        else:
            st.caption(
                "No concrete numbers could be compared yet — check that your evidence includes "
                "the fields this framework's heuristics need."
            )


# --- Tab: Impact & Simulation -------------------------------------------------
with tab_impact:
    st.markdown("### 🧮 Sales / Revenue Impact Calculator")
    st.caption(
        "Explore Traffic × Conversion Rate × AOV scenarios any time — you don't need to run a full "
        "root-cause analysis or have a confirmed High/Critical finding first."
    )
    if not parsed_files:
        st.info("Upload evidence in the sidebar (or load the sample bundle) to use the calculator.")
    elif selected_framework != "Generic Financial":
        st.warning(
            "The Traffic × Conversion Rate × AOV driver tree is only computed for the "
            "**Generic Financial** framework. Switch frameworks in the sidebar to use this calculator."
        )
    else:
        render_whatif_calculator_body(driver_tree, key_prefix="whatif_tab", show_intro=False)

        if driver_tree and driver_tree.get("applicable"):
            st.divider()
            st.markdown("### 📉 Before vs. After")
            st.caption("🧮 Deterministic — the same baseline/current figures behind the driver tree, side by side.")

            def _safe_pct(before, after):
                if before in (0, None) or after is None:
                    return None
                return (after - before) / abs(before) * 100.0

            b = driver_tree["baseline_metrics"]
            c = driver_tree["current_metrics"]
            rows = [
                ("Revenue", b.get("revenue"), c.get("revenue"), "$"),
                ("Conversion Rate", b.get("cvr"), c.get("cvr"), "%"),
                ("Orders", b.get("orders"), c.get("orders"), ""),
                ("Traffic", b.get("traffic"), c.get("traffic"), ""),
                ("AOV", b.get("aov"), c.get("aov"), "$"),
            ]
            table_rows = []
            for label, before, after, unit in rows:
                pct = _safe_pct(before, after)
                if pct is None:
                    pct_str = "N/A (baseline is zero)"
                else:
                    arrow = "↓" if pct < 0 else "↑"
                    pct_str = f"{arrow} {abs(pct):.1f}%"
                fmt = (lambda v: f"${v:,.0f}") if unit == "$" else ((lambda v: f"{v:.2f}%") if unit == "%" else (lambda v: f"{v:,.0f}"))
                table_rows.append({
                    "Metric": label,
                    "Before": fmt(before) if before is not None else "N/A",
                    "After": fmt(after) if after is not None else "N/A",
                    "Change": pct_str,
                })
            st.dataframe(pd.DataFrame(table_rows), hide_index=True, use_container_width=True)


# --- Tab: Timeline --------------------------------------------
with tab_timeline:
    if not parsed_files:
        st.info("Upload evidence to build a timeline.")
    else:
        fig = timeline.render_timeline_chart(
            timeline_df if timeline_df is not None else pd.DataFrame(),
            title="Incident Timeline — All Evidence Sources",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Colors reflect severity/category where known. Hover a point for details.")
        if timeline_df is not None and not timeline_df.empty:
            with st.expander("View timeline as a table"):
                st.dataframe(timeline_df, use_container_width=True)


# --- Tab: Actions -------------------------------------------------------------
with tab_actions:
    incident_id = st.session_state.get("current_incident_id")
    if not incident_id:
        st.info("Run an analysis first — recommended actions will be seeded here for tracking once an incident is recorded.")
    else:
        incident = incident_store.get_incident(incident_id)
        st.markdown(f"### Actions for Incident #{incident_id}")
        st.caption(f"Status: **{incident['status']}** · Severity: **{incident['severity']}** · Root cause: {incident['primary_root_cause']}")

        existing_actions = incident_store.list_actions(incident_id)
        existing_texts = {a["action_text"] for a in existing_actions}

        if ai_result and ai_result.get("recommended_actions"):
            seedable = [r for r in ai_result["recommended_actions"] if r.get("action") not in existing_texts]
            if seedable:
                st.markdown("#### Seed from AI recommendations")
                for r in seedable:
                    scol1, scol2 = st.columns([4, 1])
                    with scol1:
                        st.write(f"**{r.get('action', '')}** — {r.get('rationale', '')}")
                    with scol2:
                        if st.button("➕ Track", key=f"seed_{incident_id}_{hash(r.get('action',''))}"):
                            incident_store.add_action(incident_id, r.get("action", ""), r.get("priority", "Medium"))
                            st.rerun()

        st.markdown("#### Tracked Actions")
        existing_actions = incident_store.list_actions(incident_id)
        if not existing_actions:
            st.caption("No actions tracked yet for this incident.")
        else:
            for a in existing_actions:
                acol1, acol2, acol3 = st.columns([3, 1, 1])
                with acol1:
                    st.write(f"**{a['action_text']}**")
                    st.caption(f"Priority: {a['priority']} · Created: {a['created_at']}")
                with acol2:
                    new_status = st.selectbox(
                        "Status", options=incident_store.ACTION_STATUSES,
                        index=incident_store.ACTION_STATUSES.index(a["status"]),
                        key=f"action_status_{a['id']}", label_visibility="collapsed",
                    )
                    if new_status != a["status"]:
                        incident_store.update_action_status(a["id"], new_status)
                        st.rerun()

        st.markdown("#### Add a custom action")
        with st.form(key=f"custom_action_form_{incident_id}", clear_on_submit=True):
            custom_text = st.text_input("Action")
            custom_priority = st.selectbox("Priority", options=["High", "Medium", "Low"])
            if st.form_submit_button("Add") and custom_text.strip():
                incident_store.add_action(incident_id, custom_text.strip(), custom_priority)
                st.rerun()

    st.divider()
    st.markdown("### 🕓 Incident History")
    history = incident_store.list_incidents()
    if history:
        hist_df = pd.DataFrame(history)[["id", "created_at", "framework", "severity", "confidence", "status", "primary_root_cause"]]
        st.dataframe(hist_df, hide_index=True, use_container_width=True)
    else:
        st.caption("No incidents recorded yet.")


# --- Tab: Reports ---------------------------------------------------
with tab_reports:
    if not parsed_files:
        st.info("Run an analysis first, then export the report here.")
    else:
        filenames = [pf["filename"] for pf in parsed_files]
        generated_at = st.session_state.last_run_at or datetime.now()

        st.markdown("#### Branding")
        brand_col1, brand_col2 = st.columns([2, 1])
        with brand_col1:
            company_name = st.text_input(
                "Company name (optional)",
                key="report_company_name",
                placeholder="e.g. Acme Retail Inc.",
                help="Shown on the report cover page / summary header.",
            )
        with brand_col2:
            logo_file = st.file_uploader(
                "Logo (optional)", type=["png", "jpg", "jpeg"], key="report_logo_upload",
                help="Shown on the report cover page / summary header.",
            )
        logo_bytes = logo_file.read() if logo_file is not None else None

        st.markdown("#### Report Type")
        report_mode_label = st.radio(
            "Report Type",
            options=["Full Report", "Executive Summary (One-Pager)"],
            key="report_mode_choice",
            horizontal=True,
            label_visibility="collapsed",
        )
        report_mode = "executive" if report_mode_label.startswith("Executive") else "full"
        if report_mode == "executive":
            st.caption(
                "Best-effort single page: summary, impact assessment, top anomaly, primary trigger "
                "event, and the top 3 recommended actions — no cover page, no full tables."
            )
        else:
            st.caption("Full report with a dedicated cover page and every section/table.")

        md_report = report.generate_markdown_report(
            ai_result, filenames, generated_at, company_name=company_name or None, mode=report_mode,
        )

        st.divider()
        st.markdown("### Report Preview")
        st.markdown(md_report)

        st.divider()
        file_suffix = "executive_summary" if report_mode == "executive" else "report"
        col_a, col_b = st.columns(2)
        with col_a:
            st.download_button(
                "⬇️ Download Markdown",
                data=md_report,
                file_name=f"root_cause_ai_{file_suffix}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_b:
            try:
                pdf_bytes = report.generate_pdf_report(
                    ai_result, filenames, generated_at,
                    logo_bytes=logo_bytes, company_name=company_name or None, mode=report_mode,
                )
                st.download_button(
                    "⬇️ Download PDF",
                    data=pdf_bytes,
                    file_name=f"root_cause_ai_{file_suffix}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Could not generate the PDF report: {e}")

st.markdown(
    '<p class="rc-footer-note">Root Cause AI reasons only over evidence you provide. '
    'It flags when evidence is insufficient rather than guessing.</p>',
    unsafe_allow_html=True,
)
