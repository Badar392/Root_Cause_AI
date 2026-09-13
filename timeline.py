"""
utils/timeline.py

Builds a unified chronological timeline from any mix of evidence sources
(parsed logs, complaint entries, dated CSV rows, AI-flagged events) and
renders it as an interactive Plotly milestone/scatter chart.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

TIMELINE_COLUMNS = ["timestamp", "label", "category", "source"]

SEVERITY_COLORS = {
    "CRITICAL": "#FF4B4B",
    "FATAL": "#FF4B4B",
    "ERROR": "#FF6B6B",
    "HIGH": "#FF9F43",
    "WARN": "#FFD43B",
    "WARNING": "#FFD43B",
    "MEDIUM": "#FFD43B",
    "LOW": "#20C997",
    "INFO": "#4DABF7",
    "DEBUG": "#8899A6",
    "COMPLAINT": "#C77DFF",
    "UNKNOWN": "#8899A6",
}
DEFAULT_PALETTE = px.colors.qualitative.Bold


def _empty_timeline() -> pd.DataFrame:
    return pd.DataFrame(columns=TIMELINE_COLUMNS)


def _try_parse_date(value):
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value
    s = str(value).strip()
    if not s or s.lower() in ("none", "nan", "nat", "unknown"):
        return None
    parsed = pd.to_datetime(s, errors="coerce", utc=False)
    if pd.isna(parsed):
        return None
    # Drop timezone info so mixed-source timelines compare cleanly.
    if getattr(parsed, "tzinfo", None) is not None:
        parsed = parsed.tz_localize(None)
    return parsed


# =============================================================================
# Builders — one per evidence source
# =============================================================================

def build_timeline_from_logs(log_events: list) -> pd.DataFrame:
    """log_events: list of {"timestamp", "level", "message", ...} from parsers.parse_log_lines."""
    rows = []
    for e in log_events or []:
        ts = _try_parse_date(e.get("timestamp"))
        if ts is None:
            continue
        rows.append({
            "timestamp": ts,
            "label": (e.get("message") or "").strip()[:140] or "(empty log line)",
            "category": (e.get("level") or "UNKNOWN").upper(),
            "source": "log",
        })
    return pd.DataFrame(rows, columns=TIMELINE_COLUMNS) if rows else _empty_timeline()


def build_timeline_from_complaints(complaint_entries: list) -> pd.DataFrame:
    """complaint_entries: list of {"date", "text"} from parsers.parse_complaints_text."""
    rows = []
    for e in complaint_entries or []:
        ts = _try_parse_date(e.get("date"))
        if ts is None:
            continue
        rows.append({
            "timestamp": ts,
            "label": (e.get("text") or "").strip()[:140],
            "category": "COMPLAINT",
            "source": "complaint",
        })
    return pd.DataFrame(rows, columns=TIMELINE_COLUMNS) if rows else _empty_timeline()


def build_timeline_from_dataframe(df: pd.DataFrame, date_col: str, label_cols=None,
                                   category: str = "Data point") -> pd.DataFrame:
    """Turn dated rows of an uploaded CSV into timeline points."""
    if df is None or date_col not in df.columns:
        return _empty_timeline()

    label_cols = label_cols or [c for c in df.columns if c != date_col][:3]
    rows = []
    for _, row in df.iterrows():
        ts = _try_parse_date(row[date_col])
        if ts is None:
            continue
        label_bits = [f"{c}: {row[c]}" for c in label_cols if c in df.columns]
        rows.append({
            "timestamp": ts,
            "label": " | ".join(label_bits)[:140],
            "category": category,
            "source": "dataframe",
        })
    return pd.DataFrame(rows, columns=TIMELINE_COLUMNS) if rows else _empty_timeline()


def build_timeline_from_ai_events(ai_timeline_events: list) -> pd.DataFrame:
    """ai_timeline_events: the `timeline_events` list from the Groq root-cause response."""
    rows = []
    for e in ai_timeline_events or []:
        ts = _try_parse_date(e.get("timestamp"))
        if ts is None:
            continue
        rows.append({
            "timestamp": ts,
            "label": (e.get("label") or "").strip()[:140],
            "category": (e.get("category") or "AI-flagged").upper(),
            "source": "ai",
        })
    return pd.DataFrame(rows, columns=TIMELINE_COLUMNS) if rows else _empty_timeline()


def merge_timelines(*frames) -> pd.DataFrame:
    """Combine any number of timeline dataframes into one, sorted chronologically."""
    valid = [d for d in frames if d is not None and not d.empty]
    if not valid:
        return _empty_timeline()
    merged = pd.concat(valid, ignore_index=True)
    merged = merged.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return merged


# =============================================================================
# Rendering
# =============================================================================

def render_timeline_chart(timeline_df: pd.DataFrame, title: str = "Incident Timeline") -> go.Figure:
    """Render the merged timeline as an interactive Plotly scatter/milestone chart."""
    if timeline_df is None or timeline_df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{title} — no dated events were found in the uploaded evidence",
            template="plotly_dark",
            height=280,
            plot_bgcolor="#12121e",
            paper_bgcolor="#12121e",
            font=dict(color="#E6E6E6"),
        )
        return fig

    categories = list(pd.unique(timeline_df["category"]))
    color_map = {}
    for i, cat in enumerate(categories):
        color_map[cat] = SEVERITY_COLORS.get(cat, DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)])

    fig = go.Figure()
    for cat in categories:
        subset = timeline_df[timeline_df["category"] == cat]
        fig.add_trace(go.Scatter(
            x=subset["timestamp"],
            y=[cat] * len(subset),
            mode="markers",
            name=str(cat),
            marker=dict(size=15, color=color_map[cat], line=dict(width=1.5, color="#0d0d17"),
                        symbol="circle"),
            text=subset["label"],
            customdata=subset["source"],
            hovertemplate="<b>%{text}</b><br>%{x}<br>Source: %{customdata}<extra>%{fullData.name}</extra>",
        ))

    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=max(360, 70 * len(categories) + 180),
        xaxis_title="Time",
        yaxis_title="Category",
        showlegend=True,
        plot_bgcolor="#12121e",
        paper_bgcolor="#12121e",
        font=dict(color="#E6E6E6"),
        margin=dict(l=40, r=30, t=60, b=40),
        hoverlabel=dict(bgcolor="#1a1a2e", font_size=12),
    )
    fig.update_xaxes(gridcolor="#2a2a3d", zerolinecolor="#2a2a3d")
    fig.update_yaxes(gridcolor="#2a2a3d")
    return fig


def guess_date_column(df: pd.DataFrame):
    """Best-effort guess at which column in an uploaded CSV holds dates."""
    if df is None:
        return None
    candidates = [c for c in df.columns if any(k in c.lower() for k in ("date", "time", "timestamp"))]
    for c in candidates:
        parsed = pd.to_datetime(df[c], errors="coerce")
        if parsed.notna().mean() > 0.7:
            return c
    return None
