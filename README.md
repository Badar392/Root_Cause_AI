# 🧬 Root Cause AI

Root Cause AI turns messy, scattered evidence — sales CSVs, ad spend exports,
analytics dumps, customer complaint logs, server error logs, even `.eml`
emails — into a structured root-cause analysis: **anomalies → trigger
event(s) → impact assessment → recommended actions**, backed by an
interactive timeline and one-click Markdown/PDF export.

The AI never sees your raw files. Every upload is parsed and aggregated into
a bounded, structured evidence payload first; the model is instructed to
reason only over that payload, to separate correlation from causation, and
to say "insufficient evidence" rather than invent a cause.

---

## Directory structure

```
root-cause-ai/
├── requirements.txt
├── .env.example
├── README.md
├── app.py                  # Main Streamlit UI & layout
├── utils/
│   ├── __init__.py
│   ├── parsers.py          # CSV, PDF, DOCX, TXT/log, .eml parsing
│   ├── groq_client.py      # Groq API wrapper + analysis prompts
│   ├── timeline.py         # Timeline construction + interactive Plotly chart
│   └── report.py           # Markdown + PDF report export
└── sample_data/
    ├── sales.csv
    ├── ad_spend.csv
    ├── ga_export.csv
    ├── complaints.txt
    └── error_logs.txt
```

The five sample files tell one coherent story out of the box: a payment
database connection-pool misconfiguration on **2024-03-15** causes a
checkout outage — visible as a revenue drop in `sales.csv`, wasted ad spend
in `ad_spend.csv`, a bounce-rate spike in `ga_export.csv`, a surge of
tickets in `complaints.txt`, and the actual `ERROR`/`CRITICAL` log lines in
`error_logs.txt`. Click **"Load Sample Incident Bundle"** in the sidebar to
try the whole pipeline immediately.

---

## Setup

1. **Clone and enter the project**
   ```bash
   cd root-cause-ai
   ```

2. **Create a virtual environment (recommended)**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Get a Groq API key**
   - Sign up at [console.groq.com](https://console.groq.com/keys)
   - Create a new API key (Groq's free tier is generous and fast)

5. **Configure your API key**
   ```bash
   cp .env.example .env
   ```
   Then edit `.env`:
   ```
   GROQ_API_KEY=your_actual_key_here
   GROQ_MODEL=openai/gpt-oss-120b
   ```
   You can also paste a key directly into the sidebar at runtime — it's only
   held in that session and never written to disk.

6. **Run the app**
   ```bash
   streamlit run app.py
   ```
   Streamlit will open the app at `http://localhost:8501`.

---

## Using the app

1. **Upload evidence** in the sidebar — any mix of `.csv`, `.pdf`, `.docx`,
   `.txt`, `.eml` — or click **Load Sample Incident Bundle** to try the
   included demo data.
2. Click **🚀 Run Root Cause Analysis**. Root Cause AI parses every file,
   builds a compact structured evidence summary, and sends only that
   summary to Groq for interpretation.
3. Explore the four tabs:
   - **📄 Data Preview** — see exactly what was extracted from each file
   - **🔍 Root Cause Analysis** — summary, anomalies, trigger events, impact
     assessment, and recommended actions, each with its supporting evidence
   - **📈 Interactive Timeline** — every dated event from every source,
     plotted together so you can visually trace how the incident unfolded
   - **📤 Export Reports** — preview and download the full report as
     Markdown or PDF

---

## Supported file types

| Type | Extension | What's extracted |
|---|---|---|
| Spreadsheet | `.csv` | Full dataframe, numeric summary stats, 5-row sample |
| PDF | `.pdf` | Page-by-page text (via `pdfplumber`) |
| Word document | `.docx` | Paragraph and table text (via `python-docx`) |
| Log dump | `.txt` (with "log"/"error" in the filename) | Timestamped `{timestamp, level, message}` events |
| Freeform text | `.txt` | Date-prefixed entries, or blank-line-separated blocks |
| Email | `.eml` | From/To/Subject/Date headers + plain-text body |

---


## Business Model Frameworks

The sidebar contains a mandatory **Business Model Framework** selector. The selected framework is
included in the evidence payload and controls both the deterministic heuristic engine and the AI
consulting persona:

- **Generic Financial** — financial variance and the existing Traffic × Conversion Rate × AOV
  driver tree when applicable.
- **E-commerce Funnel** — strictly scans `Traffic -> Add-to-Cart -> Checkout -> Purchase` and
  flags adjacent-step drop-offs **greater than 15%**.
- **SaaS / Subscription (MRR/Churn)** — prioritizes recurring versus transactional revenue and
  computes monthly cohort churn proxies from a user/customer identifier plus date field.
- **B2B Marketing Funnel** — uses B2B demand-generation stages such as Lead/MQL/SQL/Opportunity/
  Closed-Won when those fields are available.

The selected framework is also injected into the LLM system instruction so the model adopts the
corresponding domain consulting persona. Framework-specific calculations are supplied as
precomputed evidence; the model is instructed not to replace their thresholds or calculations.

## Notes on the AI layer

- Model calls go through `utils/groq_client.py`, which wraps the official
  `groq` Python SDK.
- The system prompt (`ROOT_CAUSE_SYSTEM_PROMPT`) explicitly forbids
  inventing numbers, dates, or causal claims not supported by the evidence,
  and requires the model to flag insufficient evidence rather than guess.
- Responses are requested as JSON only; `analyze_root_cause()` defensively
  parses that JSON and falls back to a raw-text view in the UI if parsing
  fails or required keys are missing, so a malformed model response never
  crashes the app.

---

## Troubleshooting

- **"No Groq API key found"** — set `GROQ_API_KEY` in `.env` or paste one
  into the sidebar, then re-run the analysis.
- **PDF/DOCX parsing errors** — scanned/image-only PDFs have no extractable
  text; OCR is out of scope for this app. Try a text-based PDF instead.
- **AI response couldn't be parsed** — occasionally a model returns
  malformed JSON. Re-running the analysis usually resolves it; the raw
  output is always shown as a fallback so nothing is silently lost.


## Production-safe AI configuration

The dashboard intentionally hides API keys, provider selectors, and model selectors from end users. Configure the backend through Streamlit secrets or environment variables. The AI provider is fixed to Groq; only the Groq API key is read from `st.secrets` first and then `os.environ`.

Supported configuration:

```toml
GROQ_API_KEY = "..."
GROQ_MODEL = "openai/gpt-oss-120b"
```

For Streamlit Cloud, add these under the app's Secrets settings. For local development, `.streamlit/secrets.toml` can be used. The app never renders these values. If configuration is missing or an API call cannot operate, the UI shows only the administrator-facing configuration message.

---

## Professional features

### 🔔 Alerting / webhooks (`alerts.py`)
When a run confirms a **High or Critical** severity finding, the app can auto-notify configured sinks — best-effort, never blocking or crashing the run itself:
- **Slack** — set `SLACK_WEBHOOK_URL` to an Incoming Webhook URL.
- **Email** — set `ALERT_SMTP_HOST` / `_PORT` / `_USERNAME` / `_PASSWORD` / `_FROM` / `_TO` (`_USE_TLS` optional, defaults to `true`).

Either, both, or neither can be configured. Admin mode shows which sinks are active under **⚙️ Admin Controls → 🔔 Alerting Status**.

### 🔌 Direct data connectors (`connectors.py`)
Pull evidence straight into the app instead of exporting a CSV every time, from the sidebar's **"Or Pull From a Connected Source"** section:
- **Google Sheets** — any sheet shared as "Anyone with the link can view," no credentials needed.
- **SQL database** — SQLite works out of the box; Postgres/MySQL/etc. via `DATABASE_URL` plus the optional `sqlalchemy` package. Only read-only `SELECT`/`WITH` queries are allowed.
- **Stripe** — aggregates recent successful charges into a daily revenue/orders table via `STRIPE_API_KEY`.
- **GA4** — aggregates daily sessions/conversion rate via `GA4_PROPERTY_ID` + `GA4_CREDENTIALS_PATH` (service-account JSON), using the optional `google-analytics-data` package.

Every connector returns the same shape a CSV upload does, so fetched data flows through the driver tree, timeline, AI payload, and exports unchanged.

### 👤 Role-based access (admin vs. analyst)
Everyone starts as an **analyst**: upload/connect evidence, pick a framework, run analyses, view benchmarks — with all infrastructure (API keys, model, alert/connector config) hidden. Entering the correct `ADMIN_PASSCODE` in the sidebar unlocks **admin** mode for that session: AI configuration status, a per-session model override, and alerting/connector configuration status. Leave `ADMIN_PASSCODE` unset to disable admin mode entirely.

### 📊 Benchmark library (`benchmarks.py`)
A reference sidebar panel of industry-typical thresholds per Business Model Framework (e.g. "15%+ funnel step drop-off is generally material," "±15% revenue swing is worth investigating"). These are also passed into the AI evidence payload so severity judgments are calibrated against a stated reference point, and a few concrete computed numbers (revenue change, funnel drop-offs, churn proxy) are automatically flagged against them with "⚠️ exceeds benchmark" markers. Always presented as reference points, not verdicts.


