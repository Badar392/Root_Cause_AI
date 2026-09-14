"""
quality.py

Deterministic, non-LLM analysis layer for Root Cause AI:
    - Data quality checks on uploaded/connected CSV evidence.
    - Evidence-source coverage (which categories of evidence are present).
    - Severity classification from computed numbers (not the LLM's opinion).
    - A composite root-cause confidence score built from measurable
      components (evidence support, driver contribution, alternative-
      hypothesis risk, temporal alignment), with the LLM used only to
      *explain* the score afterward — never to set it.

Every function here is pure Python/pandas over data already parsed
elsewhere in the app. No network or AI calls happen in this module.
"""

import pandas as pd


# =============================================================================
# 1. Data quality
# =============================================================================

def assess_data_quality(parsed_files: list) -> dict:
    """
    Run lightweight, deterministic quality checks against every uploaded/
    connected CSV. Returns per-file findings plus an overall 0-100 score.
    Never blocks analysis — this is informational (ERROR/WARNING/INFO).
    """
    file_reports = []
    csv_files = [pf for pf in (parsed_files or []) if pf.get("kind") == "csv" and pf.get("dataframe") is not None]

    if not csv_files:
        return {"applicable": False, "files": [], "overall_score": None}

    total_checks = 0
    total_penalty = 0.0

    for pf in csv_files:
        df = pf["dataframe"]
        findings = []
        file_penalty = 0.0

        if df.empty:
            findings.append({"level": "ERROR", "message": "File contains no rows."})
            file_penalty += 40
        else:
            # Missing values
            missing = int(df.isna().sum().sum())
            if missing > 0:
                findings.append({"level": "WARNING", "message": f"{missing} missing value(s) across all columns."})
                file_penalty += min(20, missing * 0.5)
            else:
                findings.append({"level": "INFO", "message": "No missing values detected."})

            # Duplicate rows
            dup_rows = int(df.duplicated().sum())
            if dup_rows > 0:
                findings.append({"level": "WARNING", "message": f"{dup_rows} fully duplicate row(s)."})
                file_penalty += min(15, dup_rows * 1.0)

            # Date column checks (best-effort detection by name)
            date_cols = [c for c in df.columns if any(k in str(c).lower() for k in ("date", "time", "timestamp", "day"))]
            for dc in date_cols:
                parsed_dates = pd.to_datetime(df[dc], errors="coerce")
                invalid = int(parsed_dates.isna().sum()) - int(df[dc].isna().sum())
                if invalid > 0:
                    findings.append({"level": "WARNING", "message": f"'{dc}': {invalid} value(s) could not be parsed as dates."})
                    file_penalty += min(15, invalid * 1.0)
                dup_dates = int(parsed_dates.dropna().duplicated().sum())
                if dup_dates > 0:
                    findings.append({"level": "INFO", "message": f"'{dc}': {dup_dates} duplicate date(s) (may be legitimate multiple entries per day)."})
                if date_cols:
                    findings.append({"level": "INFO", "message": f"Date column detected: '{dc}'."}) if dc == date_cols[0] else None

            # Numeric columns holding non-numeric text (object dtype that mostly looks numeric-ish is out of scope;
            # we flag columns that are entirely non-numeric strings mixed with a few numbers as a simple heuristic)
            numeric_like_cols = [
                c for c in df.columns
                if c not in date_cols and df[c].dtype == object
                and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.5
                and pd.to_numeric(df[c], errors="coerce").notna().mean() < 1.0
            ]
            for c in numeric_like_cols:
                bad = int(pd.to_numeric(df[c], errors="coerce").isna().sum() - df[c].isna().sum())
                findings.append({"level": "WARNING", "message": f"'{c}' looks numeric but has {bad} non-numeric value(s)."})
                file_penalty += min(10, bad * 1.0)

            # Very small dataset
            if len(df) < 4:
                findings.append({"level": "WARNING", "message": f"Only {len(df)} row(s) — too small for reliable period comparisons or statistics."})
                file_penalty += 10

            # Outlier scan on purely numeric columns via IQR (informational only)
            numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            for c in numeric_cols:
                series = df[c].dropna()
                if len(series) >= 8:
                    q1, q3 = series.quantile(0.25), series.quantile(0.75)
                    iqr = q3 - q1
                    if iqr > 0:
                        outliers = int(((series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)).sum())
                        if outliers > 0:
                            findings.append({"level": "INFO", "message": f"'{c}': {outliers} statistical outlier(s) (IQR method)."})

        total_checks += 1
        total_penalty += min(60, file_penalty)  # cap penalty per file

        errors = sum(1 for f in findings if f["level"] == "ERROR")
        warnings = sum(1 for f in findings if f["level"] == "WARNING")
        file_score = max(0, 100 - file_penalty)
        file_reports.append({
            "filename": pf["filename"],
            "rows": len(df),
            "columns": len(df.columns),
            "findings": findings,
            "errors": errors,
            "warnings": warnings,
            "score": round(file_score, 0),
        })

    overall_score = round(max(0, 100 - (total_penalty / max(1, total_checks))), 0)
    return {"applicable": True, "files": file_reports, "overall_score": overall_score}


# =============================================================================
# 2. Evidence-source coverage (which categories of evidence exist at all)
# =============================================================================

EVIDENCE_CATEGORIES = [
    ("revenue_data", "Revenue data", ["revenue", "sales", "total_revenue", "revenue_amount", "mrr", "arr"]),
    ("traffic_data", "Traffic data", ["traffic", "sessions", "visits", "users", "site_visits", "clicks", "impressions"]),
    ("conversion_data", "Conversion / orders data", ["orders", "order_count", "purchases", "transactions", "conversion_rate", "conversion", "cvr"]),
    ("error_logs", "Error logs", None),   # detected by file kind == "log"
    ("customer_complaints", "Customer complaints", None),  # file kind == "txt" with structured entries, or "eml"
]


def compute_evidence_source_coverage(parsed_files: list) -> dict:
    """
    Deterministically check which *categories* of evidence are present at
    all (not whether the AI cited them well — see compute_evidence_coverage
    in app.py for that). Produces the "✓ Revenue data / ⚠ Server metrics
    unavailable" style checklist, plus a 0-100 score and a plain-language
    note about what's missing.
    """
    parsed_files = parsed_files or []
    csv_cols = set()
    for pf in parsed_files:
        if pf.get("kind") == "csv" and pf.get("dataframe") is not None:
            csv_cols.update(str(c).lower() for c in pf["dataframe"].columns)

    has_logs = any(pf.get("kind") == "log" for pf in parsed_files)
    has_complaints = any(pf.get("kind") in ("txt", "eml") for pf in parsed_files)

    checklist = []
    present_count = 0
    for key, label, keywords in EVIDENCE_CATEGORIES:
        if key == "error_logs":
            present = has_logs
        elif key == "customer_complaints":
            present = has_complaints
        else:
            present = any(any(kw in col for kw in keywords) for col in csv_cols)
        checklist.append({"key": key, "label": label, "present": present})
        present_count += int(present)

    score = round(present_count / len(EVIDENCE_CATEGORIES) * 100.0, 0)
    missing = [c["label"] for c in checklist if not c["present"]]

    if score >= 80:
        label = "Strong"
    elif score >= 50:
        label = "Moderate"
    else:
        label = "Weak"

    note = None
    if missing:
        note = (
            f"Missing: {', '.join(missing)}. Adding this evidence could strengthen or weaken "
            "the current hypotheses — the analysis below only reflects what was actually supplied."
        )

    return {"checklist": checklist, "score": score, "label": label, "missing": missing, "note": note}


# =============================================================================
# 3. Deterministic severity classification
# =============================================================================

def compute_deterministic_severity(driver_tree: dict, heuristics: dict = None) -> dict:
    """
    Classify incident severity from measurable indicators — never from the
    LLM's unsupported opinion. Primary signal: percentage revenue change
    from the driver tree (Traffic x CVR x AOV) when available. Falls back
    to framework heuristics (e.g. funnel drop-off, churn proxy) otherwise.
    """
    heuristics = heuristics or {}
    reasons = []
    pct_candidates = []

    if driver_tree and driver_tree.get("applicable"):
        baseline_rev = driver_tree["baseline_metrics"].get("revenue") or 0
        actual_change = driver_tree.get("actual_revenue_change", 0)
        if baseline_rev:
            pct = abs(actual_change) / abs(baseline_rev) * 100.0
            pct_candidates.append(pct)
            direction = "declined" if actual_change < 0 else "increased"
            reasons.append(f"Revenue {direction} {pct:.1f}% between the compared periods.")

    # Framework heuristics can also surface a material % move (e.g. funnel step drop, churn proxy).
    for key, val in (heuristics or {}).items():
        if isinstance(val, dict) and "pct_change" in val:
            try:
                pct = abs(float(val["pct_change"]))
                pct_candidates.append(pct)
                reasons.append(f"{val.get('label', key)}: {pct:.1f}% change.")
            except (TypeError, ValueError):
                continue

    if not pct_candidates:
        return {
            "level": "LOW",
            "reason": "No quantifiable revenue/metric decline could be computed from the supplied evidence.",
            "basis_pct": None,
        }

    worst_pct = max(pct_candidates)
    if worst_pct >= 40:
        level = "CRITICAL"
    elif worst_pct >= 20:
        level = "HIGH"
    elif worst_pct >= 8:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {"level": level, "reason": " ".join(reasons), "basis_pct": round(worst_pct, 1)}


SEVERITY_COLOR = {"LOW": "#39d6a8", "MEDIUM": "#ffe06a", "HIGH": "#ff9d4d", "CRITICAL": "#ff6262"}
SEVERITY_ICON = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}


# =============================================================================
# 4. Deterministic root-cause confidence score
# =============================================================================

_RISK_TO_SCORE = {"low": 100.0, "medium": 60.0, "high": 20.0}


def compute_root_cause_confidence(ai_result: dict, driver_tree: dict, evidence_coverage_pct: float) -> dict:
    """
    Composite 0-100 confidence score built from measurable components:
      - Evidence support:      % of findings citing specific evidence (existing citation-coverage score)
      - Driver contribution:   |impact share| of the primary mathematical driver, when available
      - Alternative risk:      inverse of the Devil's-Advocate falsification risk on the top hypothesis
      - Temporal alignment:    proxy — whether trigger events carry concrete timestamps at all
                                (a lightweight stand-in; full change-point-based alignment is not
                                implemented, see README limitations)

    The LLM is never asked "what is your confidence" — this is calculated
    first, and the AI's own summary/question_answer text is shown alongside
    it, clearly labeled as interpretation rather than the source of the number.
    """
    components = {}

    components["evidence_support"] = round(evidence_coverage_pct or 0.0, 1)

    if driver_tree and driver_tree.get("applicable"):
        primary = driver_tree.get("primary_driver") or {}
        components["driver_contribution"] = round(min(100.0, abs(primary.get("impact_share_pct", 0))), 1)
    else:
        components["driver_contribution"] = None

    counter = (ai_result or {}).get("counter_hypotheses") or []
    if counter:
        risks = [_RISK_TO_SCORE.get(str(c.get("falsification_risk_score", "")).strip().lower(), 60.0) for c in counter]
        components["alternative_risk"] = round(sum(risks) / len(risks), 1)
    else:
        components["alternative_risk"] = None

    trigger_events = (ai_result or {}).get("trigger_events") or []
    with_ts = sum(1 for t in trigger_events if str(t.get("timestamp_or_period", "")).strip().lower() not in ("", "unknown", "n/a"))
    if trigger_events:
        components["temporal_alignment"] = round(with_ts / len(trigger_events) * 100.0, 1)
    else:
        components["temporal_alignment"] = None

    # Weighted average over whichever components are actually available.
    weights = {"evidence_support": 0.35, "driver_contribution": 0.30, "alternative_risk": 0.20, "temporal_alignment": 0.15}
    available = {k: v for k, v in components.items() if v is not None}
    if not available:
        overall = 0.0
    else:
        weight_sum = sum(weights[k] for k in available)
        overall = sum(available[k] * weights[k] for k in available) / weight_sum

    return {
        "overall": round(overall, 0),
        "components": components,
        "basis": "Weighted average of evidence-citation coverage, mathematical driver contribution, "
                 "Devil's-Advocate alternative-hypothesis risk, and trigger-event timestamp coverage. "
                 "Components with no data available are excluded rather than assumed.",
    }
