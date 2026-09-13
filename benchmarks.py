"""
benchmarks.py

A small reference library of industry-typical thresholds, keyed by Business
Model Framework, used two ways:

  1. Rendered directly in a sidebar/reference panel so analysts have a quick
     "is this normal?" gut-check without leaving the app.
  2. Included in the evidence payload sent to the AI, so severity judgments
     are calibrated against a stated reference point instead of the model's
     own (unstated, possibly inconsistent) sense of what's "material."

These are general rules of thumb aggregated from common growth/finance/SaaS
operating literature, not a guarantee for any specific business — they are
presented as reference points, not verdicts, and are always shown with that
framing in the UI.
"""

BENCHMARK_LIBRARY = {
    "Generic Financial": [
        {"metric": "Revenue week-over-week change", "threshold": "±15%",
         "note": "Beyond this is commonly treated as a material swing worth investigating."},
        {"metric": "Revenue month-over-month change", "threshold": "±10%",
         "note": "Larger monthly swings usually point to a structural cause, not noise."},
        {"metric": "Gross margin change", "threshold": "±3 pts",
         "note": "A margin move of 3+ percentage points typically has an identifiable driver."},
        {"metric": "Single-day revenue drop", "threshold": "20%+",
         "note": "A one-day drop this large is rarely organic variance — check for outages/incidents."},
    ],
    "E-commerce Funnel": [
        {"metric": "Funnel step drop-off", "threshold": "15%+",
         "note": "A 15%+ drop between adjacent funnel steps is generally considered material."},
        {"metric": "Cart abandonment rate", "threshold": "70%",
         "note": "Typical e-commerce baseline; sustained deviation above this warrants review."},
        {"metric": "Conversion rate change", "threshold": "±0.5 pts",
         "note": "Half a point of CVR movement is often enough to explain a meaningful revenue swing."},
        {"metric": "AOV change", "threshold": "±8%",
         "note": "Beyond this, check for promo/discount activity or product-mix shifts."},
        {"metric": "Cost per acquisition (CPA) change", "threshold": "±20%",
         "note": "Large CPA swings usually trace back to a channel/bidding/creative change."},
    ],
    "SaaS / Subscription (MRR/Churn)": [
        {"metric": "Monthly logo churn", "threshold": "3-5%",
         "note": "Commonly cited healthy range for SMB-focused SaaS; enterprise should be lower."},
        {"metric": "Net revenue retention (NRR)", "threshold": "100%+",
         "note": "Below 100% NRR means expansion isn't offsetting churn/contraction."},
        {"metric": "MRR movement (single month)", "threshold": "±10%",
         "note": "A double-digit single-month MRR swing usually has a specific, traceable cause."},
        {"metric": "Trial-to-paid conversion", "threshold": "15-25%",
         "note": "Typical self-serve SaaS range; well outside this suggests a funnel or ICP issue."},
    ],
    "B2B Marketing Funnel": [
        {"metric": "MQL-to-SQL conversion", "threshold": "13-20%",
         "note": "Common B2B benchmark range; well below suggests lead quality or SDR issues."},
        {"metric": "SQL-to-Opportunity conversion", "threshold": "40-50%",
         "note": "A sharp drop here often points to a qualification or handoff process problem."},
        {"metric": "Opportunity-to-Close win rate", "threshold": "20-30%",
         "note": "Typical enterprise B2B range; large deviations often trace to pricing/competition."},
        {"metric": "Pipeline coverage ratio", "threshold": "3x-4x quota",
         "note": "Below this range is a leading indicator of a future revenue shortfall."},
    ],
}


def get_benchmarks_for_framework(framework: str) -> list:
    """Return the benchmark rows for a framework, or an empty list if none defined."""
    return BENCHMARK_LIBRARY.get(framework, [])


def evaluate_against_benchmarks(framework: str, heuristics: dict, driver_tree: dict) -> list:
    """
    Best-effort comparison of a few concrete computed numbers (when available)
    against this framework's benchmark thresholds, so the UI can flag
    "⚠️ exceeds benchmark" next to a specific figure instead of only listing
    thresholds in the abstract.

    Returns a list of {metric, observed, threshold, flagged} dicts. Silent
    and conservative: if a needed number isn't available, it's simply skipped
    rather than guessed at.
    """
    flags = []

    if driver_tree and driver_tree.get("applicable"):
        baseline_revenue = (driver_tree.get("baseline_metrics") or {}).get("revenue")
        actual_change = driver_tree.get("actual_revenue_change")
        if baseline_revenue and actual_change is not None:
            pct = (actual_change / baseline_revenue) * 100.0
            flags.append({
                "metric": "Revenue change (baseline vs. current)",
                "observed": f"{pct:+.1f}%",
                "threshold": "±15%",
                "flagged": abs(pct) >= 15,
            })

    if framework == "E-commerce Funnel" and isinstance(heuristics, dict):
        for d in heuristics.get("adjacent_step_dropoffs") or []:
            flags.append({
                "metric": f"{d.get('from', 'step')} → {d.get('to', 'step')} drop-off",
                "observed": f"{d.get('dropoff_pct', 0):.1f}%",
                "threshold": "15%+",
                "flagged": bool(d.get("exceeds_15_pct")),
            })

    if framework == "SaaS / Subscription (MRR/Churn)" and isinstance(heuristics, dict):
        proxies = heuristics.get("cohort_churn_proxies") or []
        if proxies:
            latest = proxies[-1]
            churn_pct = latest.get("churn_proxy_pct")
            if churn_pct is not None:
                flags.append({
                    "metric": f"Monthly churn proxy ({latest.get('to_period', 'latest period')})",
                    "observed": f"{churn_pct:.1f}%",
                    "threshold": "3-5%",
                    "flagged": churn_pct > 5,
                })

    return flags
