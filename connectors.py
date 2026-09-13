"""
connectors.py

Pull evidence directly from external sources instead of requiring a manual
CSV export/upload every time. Every connector returns the exact same dict
shape parsers.parse_uploaded_file() produces:

    {"kind": "csv", "filename": str, "dataframe": pd.DataFrame,
     "raw_text": str, "structured": None}

...so a connector-fetched dataset can be dropped straight into
parsed_files and flows through the rest of the app (driver tree, timeline,
AI payload, exports) completely unchanged.

Four sources are supported:
  - Google Sheets  (public/"anyone with the link" sheet, via CSV export — no OAuth)
  - SQL database   (sqlite natively; Postgres/MySQL/etc. via optional SQLAlchemy)
  - Stripe         (REST API, aggregates charges into daily revenue/orders)
  - GA4            (Data API, aggregates into daily sessions/conversion rate;
                     optional dependency, degrades to a clear message if missing)

Every function raises ValueError with a human-readable message on failure,
matching parsers.py's error-handling contract, so the caller can surface it
the same way it already surfaces upload parsing errors.
"""

import io
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


def _setting(name: str, default=None):
    """Resolve configuration with st.secrets taking priority over environment
    (mirrors groq_client._setting/alerts._setting). Connector *credentials*
    (DB connection string, Stripe key, GA4 property/creds) are infra and are
    never typed into the UI — only resolved here, same as GROQ_API_KEY."""
    if st is not None:
        try:
            value = st.secrets.get(name, None)
            if value is not None and str(value).strip():
                return str(value).strip()
        except Exception:
            pass
    env_value = os.environ.get(name)
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()
    return default


@dataclass(frozen=True)
class ConnectorConfig:
    database_url: str | None
    stripe_api_key: str | None
    ga4_property_id: str | None
    ga4_credentials_path: str | None

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_api_key)

    @property
    def ga4_configured(self) -> bool:
        return bool(self.ga4_property_id and self.ga4_credentials_path)


def get_connector_config() -> ConnectorConfig:
    return ConnectorConfig(
        database_url=_setting("DATABASE_URL"),
        stripe_api_key=_setting("STRIPE_API_KEY"),
        ga4_property_id=_setting("GA4_PROPERTY_ID"),
        ga4_credentials_path=_setting("GA4_CREDENTIALS_PATH"),
    )


def _wrap_dataframe(df: pd.DataFrame, filename: str) -> dict:
    if df is None or df.empty:
        raise ValueError(f"'{filename}' returned no rows.")
    return {
        "kind": "csv",
        "filename": filename,
        "dataframe": df,
        "raw_text": df.head(50).to_csv(index=False),
        "structured": None,
    }


# =============================================================================
# Google Sheets (public link, no OAuth)
# =============================================================================

_SHEET_ID_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_GID_PATTERN = re.compile(r"[?&#]gid=(\d+)")


def _extract_sheet_id(sheet_url_or_id: str) -> tuple:
    """Accept either a raw Sheet ID or a full Google Sheets URL and return
    (sheet_id, gid). gid defaults to '0' (the first tab) when not present."""
    sheet_url_or_id = sheet_url_or_id.strip()
    match = _SHEET_ID_PATTERN.search(sheet_url_or_id)
    sheet_id = match.group(1) if match else sheet_url_or_id
    gid_match = _GID_PATTERN.search(sheet_url_or_id)
    gid = gid_match.group(1) if gid_match else "0"
    if not sheet_id or "/" in sheet_id:
        raise ValueError("Could not find a Google Sheet ID in that URL. Paste the full sheet link, or just the ID.")
    return sheet_id, gid


def fetch_google_sheet(sheet_url_or_id: str, filename: str = None) -> dict:
    """
    Fetch a Google Sheet as CSV via its public export endpoint.

    The sheet must be shared as "Anyone with the link can view" — this uses
    no OAuth/service account, matching the no-setup spirit of a CSV upload.
    """
    if requests is None:
        raise ValueError("The 'requests' package is required for the Google Sheets connector.")
    sheet_id, gid = _extract_sheet_id(sheet_url_or_id)
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    try:
        resp = requests.get(export_url, timeout=20)
    except Exception as e:
        raise ValueError(f"Could not reach Google Sheets: {e}")
    if resp.status_code == 404:
        raise ValueError("Sheet not found. Check the URL and that it's shared as 'Anyone with the link'.")
    if resp.status_code != 200:
        raise ValueError(f"Google Sheets returned HTTP {resp.status_code}. Is the sheet shared publicly?")
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        raise ValueError(
            "Google returned a login/permission page instead of CSV data. "
            "Make sure the sheet's sharing setting is 'Anyone with the link can view'."
        )
    try:
        df = pd.read_csv(io.BytesIO(resp.content))
    except Exception as e:
        raise ValueError(f"Could not parse the sheet as CSV: {e}")
    return _wrap_dataframe(df, filename or f"google_sheet_{sheet_id[:8]}.csv")


# =============================================================================
# SQL database (sqlite built-in; other engines via optional SQLAlchemy)
# =============================================================================

def fetch_database_query(connection_string: str, query: str, filename: str = None) -> dict:
    """
    Run a read query against a database and return the result as evidence.

    - `sqlite:///path/to/file.db` (or a bare local .db/.sqlite path) uses the
      standard-library sqlite3 module directly, no extra dependency.
    - Any other SQLAlchemy-style connection string (postgresql://, mysql://,
      etc.) requires the optional `sqlalchemy` package (plus the matching
      DBAPI driver) to be installed.
    """
    if not query or not query.strip():
        raise ValueError("A SQL query is required.")
    if not re.match(r"^\s*(select|with)\b", query.strip(), re.IGNORECASE):
        raise ValueError("Only read-only SELECT/WITH queries are allowed for the database connector.")

    connection_string = (connection_string or "").strip()
    is_sqlite = connection_string.startswith("sqlite:///") or connection_string.endswith((".db", ".sqlite", ".sqlite3"))

    try:
        if is_sqlite:
            path = connection_string.replace("sqlite:///", "", 1) if connection_string.startswith("sqlite:///") else connection_string
            conn = sqlite3.connect(path)
            try:
                df = pd.read_sql_query(query, conn)
            finally:
                conn.close()
        else:
            try:
                from sqlalchemy import create_engine
            except ImportError:
                raise ValueError(
                    "Connecting to non-SQLite databases requires the optional 'sqlalchemy' package "
                    "(plus the matching driver, e.g. psycopg2 for Postgres). Add it to requirements.txt."
                )
            engine = create_engine(connection_string)
            df = pd.read_sql_query(query, engine)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Database query failed: {e}")

    return _wrap_dataframe(df, filename or "database_query_result.csv")


# =============================================================================
# Stripe (REST API, API-key auth)
# =============================================================================

def fetch_stripe_revenue(api_key: str, lookback_days: int = 90, filename: str = None) -> dict:
    """
    Pull recent successful charges from Stripe and aggregate into a daily
    revenue/orders table shaped like the sample sales.csv (date, revenue,
    orders), so it plugs straight into the existing driver tree.
    """
    if requests is None:
        raise ValueError("The 'requests' package is required for the Stripe connector.")
    if not api_key or not api_key.strip():
        raise ValueError("A Stripe API key is required.")

    since = datetime.utcnow() - timedelta(days=max(1, lookback_days))
    since_ts = int(since.timestamp())

    all_charges = []
    url = "https://api.stripe.com/v1/charges"
    params = {"limit": 100, "created[gte]": since_ts}
    headers = {"Authorization": f"Bearer {api_key.strip()}"}

    for _ in range(50):  # hard cap: up to 5,000 charges per fetch
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=20)
        except Exception as e:
            raise ValueError(f"Could not reach Stripe: {e}")
        if resp.status_code == 401:
            raise ValueError("Stripe rejected the API key (401 Unauthorized).")
        if resp.status_code != 200:
            raise ValueError(f"Stripe returned HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()
        all_charges.extend(payload.get("data", []))
        if not payload.get("has_more"):
            break
        params["starting_after"] = payload["data"][-1]["id"]

    if not all_charges:
        raise ValueError(f"No Stripe charges found in the last {lookback_days} days.")

    rows = []
    for c in all_charges:
        if not c.get("paid") or c.get("status") != "succeeded":
            continue
        date = datetime.utcfromtimestamp(c["created"]).date().isoformat()
        rows.append({"date": date, "amount": c["amount"] / 100.0, "currency": c.get("currency", "usd")})

    if not rows:
        raise ValueError("No successful Stripe charges found in the selected window.")

    df = pd.DataFrame(rows)
    daily = df.groupby("date").agg(revenue=("amount", "sum"), orders=("amount", "count")).reset_index()
    daily = daily.sort_values("date")
    return _wrap_dataframe(daily, filename or "stripe_revenue.csv")


# =============================================================================
# GA4 (Data API; optional heavy dependency, lazy-imported)
# =============================================================================

def fetch_ga4_traffic(property_id: str, credentials_json_path: str, lookback_days: int = 90,
                       filename: str = None) -> dict:
    """
    Pull daily sessions + conversion rate from the GA4 Data API and return a
    table shaped like the sample ga_export.csv (date, sessions,
    conversion_rate), so it plugs straight into the existing driver tree.

    Requires a GA4 service-account JSON key file with Viewer access on the
    property, and the optional `google-analytics-data` package.
    """
    if not property_id or not property_id.strip():
        raise ValueError("A GA4 property ID is required.")
    if not credentials_json_path or not credentials_json_path.strip():
        raise ValueError("A path to a GA4 service-account credentials JSON file is required.")

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
        from google.oauth2 import service_account
    except ImportError:
        raise ValueError(
            "The GA4 connector requires the optional 'google-analytics-data' and 'google-auth' "
            "packages. Add them to requirements.txt to enable this connector."
        )

    try:
        credentials = service_account.Credentials.from_service_account_file(credentials_json_path)
        client = BetaAnalyticsDataClient(credentials=credentials)
        request = RunReportRequest(
            property=f"properties/{property_id.strip()}",
            dimensions=[Dimension(name="date")],
            metrics=[Metric(name="sessions"), Metric(name="sessionConversionRate")],
            date_ranges=[DateRange(start_date=f"{max(1, lookback_days)}daysAgo", end_date="today")],
        )
        response = client.run_report(request)
    except Exception as e:
        raise ValueError(f"GA4 Data API request failed: {e}")

    rows = []
    for r in response.rows:
        raw_date = r.dimension_values[0].value  # YYYYMMDD
        date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        sessions = float(r.metric_values[0].value or 0)
        conv_rate = float(r.metric_values[1].value or 0) * 100.0  # GA4 returns a fraction
        rows.append({"date": date, "sessions": sessions, "conversion_rate": conv_rate})

    if not rows:
        raise ValueError(f"GA4 returned no rows for the last {lookback_days} days.")

    df = pd.DataFrame(rows).sort_values("date")
    return _wrap_dataframe(df, filename or "ga4_traffic.csv")
