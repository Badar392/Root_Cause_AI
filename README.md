# 🧬 Root Cause AI

**An evidence-first AI incident investigation platform.**

Root Cause AI turns fragmented business/operational evidence — sales CSVs,
ad-spend exports, analytics dumps, customer complaint logs, server error
logs, even `.eml` emails, plus live Google Sheets / SQL / Stripe / GA4
connections — into a traceable, quantified incident investigation: from raw
evidence, through deterministic statistics, to an AI-interpreted root cause,
a stress-tested hypothesis, a quantified business impact, and a tracked
remediation plan.

It is built around one principle:

> **The LLM is not the source of truth.** Every number that matters —
> severity, revenue impact, driver attribution, confidence — is calculated
> in Python first. The AI is used to interpret and explain those numbers,
> never to invent or arbitrate them.

---

## Overview

Open the app, load evidence, and you get:

1. An **Overview** dashboard — severity, status, revenue impact, root-cause
   confidence, evidence coverage, primary root cause with "why," top
   contributing factors, and top recommended actions, all visible in one
   screen.
2. An **Investigation** workspace — the full root-cause analysis (anomalies,
   trigger events, impact assessment, mathematical driver tree, Devil's
   Advocate hypothesis stress test) plus the industry benchmark library used
   to calibrate severity language.
3. An **Evidence** workspace — data-quality checks, evidence-source
   coverage, and a preview of every parsed file.
4. An **Impact & Simulation** workspace — the Shapley-based Traffic × CVR ×
   AOV Revenue Impact Calculator, plus a Before vs. After comparison.
5. A **Timeline** — every dated event from every source plotted together.
6. An **Actions** workspace — track remediation actions per incident, update
   status, and review incident history.
7. A **Reports** workspace — Markdown/PDF export, full or executive one-pager.

---

## Key Features

- **Evidence-first pipeline** — every upload/connection is parsed and
  aggregated into a bounded structured payload before the AI ever sees it;
  the AI is instructed to say "insufficient evidence" rather than invent a cause.
- **Exact Shapley driver-tree attribution** for `Revenue = Traffic × Conversion
  Rate × AOV`, usable any time via the standalone Revenue Impact Calculator —
  not gated behind a confirmed finding.
- **Deterministic severity classification** (LOW/MEDIUM/HIGH/CRITICAL) from
  computed percentage revenue/metric change — never asked of the LLM directly.
- **Deterministic root-cause confidence score** — a weighted composite of
  evidence-citation coverage, driver contribution, Devil's-Advocate
  alternative-hypothesis risk, and trigger-event temporal coverage. The AI's
  own summary is shown alongside it, clearly labeled as interpretation, not
  as the source of the number.
- **Data quality checks** — missing values, duplicate rows/dates, invalid
  date parsing, numeric-column type mismatches, tiny datasets, and IQR
  outlier flags, all informational (never blocks analysis).
- **Evidence-source coverage** — a checklist of which categories of evidence
  (revenue, traffic, conversion, error logs, complaints) are present at all,
  independent of how well the AI cited them.
- **Devil's Advocate hypothesis stress test** — every top hypothesis is
  required to be challenged with a genuinely competing alternative and a
  falsification-risk score before the final recommendation is produced.
- **Business-model frameworks** — Generic Financial, E-commerce Funnel,
  SaaS/Subscription (MRR/Churn), B2B Marketing Funnel — each with its own
  deterministic heuristics and AI consulting persona.
- **Benchmark library** — industry-typical reference thresholds per
  framework, with your own computed numbers automatically flagged against them.
- **Direct data connectors** — Google Sheets, SQL database (SQLite built-in;
  Postgres/MySQL via optional SQLAlchemy), Stripe, GA4 — return the same
  shape as a CSV upload, so they flow through the whole pipeline unchanged.
- **Alerting/webhooks** — Slack and/or email, auto-fired on a confirmed
  High/Critical finding, best-effort and never blocking the run.
- **Incident persistence (SQLite)** — every completed run is saved as an
  incident with a status workflow (Detected → Investigating → Root Cause
  Identified → Remediation In Progress → Resolved → Monitoring), a
  remediation action tracker, a lightweight "similar previous incidents"
  lookup, and an audit log of status/action changes.
- **Markdown/PDF export** — full report with cover page, or a one-page
  executive summary, optional company name and logo.

---

## Architecture

```text
Evidence (CSV/PDF/DOCX/TXT/.eml, or Sheets/SQL/Stripe/GA4)
   ↓
Data Quality Checks           (quality.py — deterministic)
   ↓
Deterministic Heuristics      (app.py: per-framework funnel/churn/etc math)
   ↓
Driver Analysis                (app.py: exact Shapley Traffic×CVR×AOV attribution)
   ↓
Evidence Correlation & Coverage (app.py + quality.py)
   ↓
Candidate Root Causes          (bounded JSON payload assembled from all of the above)
   ↓
LLM Interpretation             (groq_client.py — reasons ONLY over that payload)
   ↓
Hypothesis Stress Testing      (Devil's Advocate matrix, required by the system prompt)
   ↓
Confidence Scoring             (quality.py — deterministic composite, AI explains it)
   ↓
Recommendations & Business Impact
   ↓
Remediation & Incident Tracking (incident_store.py — SQLite)
```

Deterministic and statistical results are computed first and handed to the
LLM as evidence; the LLM's role is interpretation and synthesis, not
calculation. Structured output is schema-validated; malformed AI responses
fall back to a visible raw-text view instead of crashing the app.

---

## AI Safety

- The AI never receives raw uploaded files — only a bounded, pre-aggregated
  structured payload.
- Uploaded/connected content is treated as untrusted data, not instructions:
  the system prompt reasons over it but is not steered by it.
- Severity, driver attribution, and confidence are calculated in Python, not
  asked of the model — the model explains them, it doesn't set them.
- Every hypothesis must be stress-tested against a genuinely competing
  alternative (Devil's Advocate) before a final recommendation is produced.
- Responses are requested as strict JSON and defensively parsed; a
  malformed response is shown as raw text rather than silently discarded or
  causing a crash.

---

## Technology Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Data | pandas, numpy |
| Visualization | Plotly |
| AI | Groq API (`openai/gpt-oss-120b` by default) |
| File parsing | pdfplumber (PDF), python-docx (DOCX), stdlib `email` (.eml) |
| PDF/Markdown reports | ReportLab, Pillow |
| Persistence | SQLite (stdlib `sqlite3`) — incidents, actions, audit log |
| Connectors | `requests` (Sheets/Stripe/GA4 REST), optional `sqlalchemy` (non-SQLite DBs), optional `google-analytics-data` + `google-auth` (GA4) |

No new dependency was introduced for persistence or the deterministic
analysis layer — both use only the Python standard library plus packages
already in `requirements.txt`.

---

## Directory Structure

```
root-cause-ai/
├── app.py                  # Main Streamlit UI, navigation, session state, run pipeline
├── quality.py               # Deterministic data quality / evidence coverage / severity / confidence
├── incident_store.py         # SQLite persistence: incidents, status workflow, actions, audit log
├── groq_client.py           # Groq API wrapper + analysis prompts
├── parsers.py               # CSV, PDF, DOCX, TXT/log, .eml parsing
├── timeline.py               # Timeline construction + interactive Plotly chart
├── report.py                 # Markdown + PDF report export
├── alerts.py                  # Slack/email alerting on confirmed High/Critical findings
├── connectors.py              # Google Sheets / SQL / Stripe / GA4 data connectors
├── benchmarks.py               # Per-framework industry benchmark reference library
├── requirements.txt
├── .env.example
├── README.md
└── sample_data (sales.csv, ad_spend.csv, ga_export.csv, complaints.txt, error_logs.txt)
```

The five sample files tell one coherent story out of the box: a payment
database connection-pool misconfiguration on **2024-03-15** causes a
checkout outage — visible as a revenue drop in `sales.csv`, wasted ad spend
in `ad_spend.csv`, a bounce-rate spike in `ga_export.csv`, a surge of
tickets in `complaints.txt`, and the actual `ERROR`/`CRITICAL` log lines in
`error_logs.txt`. Click **"Load Sample Incident Bundle"** in the sidebar to
try the whole pipeline immediately.

---

## Installation

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
   - Create a new API key

5. **Run the app**
   ```bash
   streamlit run app.py
   ```
   Streamlit opens the app at `http://localhost:8501`.

---

## Configuration

Copy `.env.example` and fill in what you need — everything is optional
except `GROQ_API_KEY`. See `.env.example` for the full annotated list:

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` (required) | AI engine |
| `GROQ_MODEL` | Defaults to `openai/gpt-oss-120b` |
| `SLACK_WEBHOOK_URL`, `ALERT_SMTP_*` | Alerting on confirmed High/Critical findings |
| `DATABASE_URL`, `STRIPE_API_KEY`, `GA4_PROPERTY_ID`, `GA4_CREDENTIALS_PATH` | Data connectors |

Locally, `.streamlit/secrets.toml` also works. On Streamlit Community Cloud,
set these under the app's **Secrets** panel and reboot after changes. The
app never renders secret values in the UI — a missing/invalid key shows a clear configuration message and optional technical details.

> **Note on persistence:** `incident_store.py` writes `incidents.db` next to
> `app.py`. On Streamlit Community Cloud's default (ephemeral) filesystem,
> this resets on redeploy/reboot — treat incident history as session/short-
> term, not a permanent system of record, unless you attach persistent storage.

---

## Usage

1. **Load evidence** in the sidebar — upload files, load the sample bundle,
   or pull from a connected Google Sheet / database / Stripe / GA4.
2. Pick a **Business Model Framework** (controls both the deterministic
   heuristics and the AI's consulting persona).
3. Click **🚀 Run Root Cause Analysis**.
4. Start on **Overview** for the executive summary, then drill into
   **Investigation** for the full evidence-backed reasoning, **Evidence**
   for data quality and source coverage, **Impact & Simulation** for
   what-if scenarios, **Timeline** for the chronological view, **Actions**
   to track remediation, and **Reports** to export.

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

## Troubleshooting

- **"System configuration in progress"** — `GROQ_API_KEY` isn't set (or is
  invalid). Check `.streamlit/secrets.toml` / environment variables, or the
  **Technical details** expander for the exact error.
- **PDF/DOCX parsing errors** — scanned/image-only PDFs have no extractable
  text; OCR is out of scope. Try a text-based PDF instead.
- **AI response couldn't be parsed** — occasionally a model returns
  malformed JSON. Re-running usually resolves it; the raw output is always
  shown as a fallback so nothing is silently lost.
- **Incident history looks empty after a redeploy** — see the persistence
  note above; `incidents.db` doesn't survive an ephemeral-filesystem reboot.

---

## Limitations (honest, by design)

- **Temporal alignment** in the confidence score is a lightweight proxy
  (whether trigger events carry concrete timestamps at all), not full
  change-point-based alignment — statistical change-point detection is not
  implemented.
- **Root-cause hypothesis ranking** shows the AI's top hypothesis plus its
  Devil's-Advocate alternative; it does not yet rank an arbitrary N
  candidate hypotheses with independent confidence scores each.
- **"Similar previous incidents"** uses a transparent substring match on
  framework + primary-root-cause label, not embeddings/ML similarity.
- **Incident persistence** is a local SQLite file, not a managed database —
  see the ephemeral-filesystem note above.
