"""
AI client/configuration layer for Root Cause AI.

Infrastructure configuration is intentionally hidden from the UI. Provider,
API keys, and model names are resolved silently in this order:
    1. st.secrets
    2. environment variables

Supported provider: groq only.
"""

import json
import os
import re
from dataclasses import dataclass

import streamlit as st
from groq import Groq



DEFAULT_PROVIDER = "groq"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

# Curated set of Groq-hosted models an admin may switch to. The first entry
# is always the production default used for every analyst-run analysis
# unless an admin has explicitly overridden it for the session.
SELECTABLE_GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]


class GroqClientError(Exception):
    """Backward-compatible application-level AI configuration/API error."""


@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str
    api_key: str | None
    configured: bool


def _secret_get(name: str, default=None):
    """Read a Streamlit secret without exposing or crashing on missing secrets."""
    try:
        value = st.secrets.get(name, default)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    return default


def _setting(name: str, default=None):
    """Resolve configuration with st.secrets taking priority over environment."""
    secret_value = _secret_get(name)
    if secret_value:
        return secret_value
    env_value = os.environ.get(name)
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()
    return default


def get_ai_config(model_override: str = None) -> AIConfig:
    """Return the Groq configuration. `model_override` is only ever honored
    when explicitly passed by the caller (app.py only does this for an
    authenticated admin session) — every analyst-run analysis uses the
    fixed production default."""
    provider = "groq"
    key = _setting("GROQ_API_KEY")
    model = model_override if model_override in SELECTABLE_GROQ_MODELS else DEFAULT_GROQ_MODEL
    return AIConfig(provider=provider, model=model, api_key=key, configured=bool(key and model))


def get_client(api_key: str = None, model_override: str = None):
    """Create the configured provider client. The optional key is retained only
    for backward compatibility; the production UI never supplies one."""
    config = get_ai_config(model_override=model_override)
    key = api_key or config.api_key

    if not key:
        raise GroqClientError("AI engine is not configured.")

    try:
        return AIClient(provider="groq", model=config.model, client=Groq(api_key=key))
    except GroqClientError:
        raise
    except Exception as e:
        raise GroqClientError(f"Could not initialize the AI client: {e}")


@dataclass
class AIClient:
    provider: str
    model: str
    client: object


# =============================================================================
# Prompts
# =============================================================================

ROOT_CAUSE_SYSTEM_PROMPT = """You are Root Cause AI, an expert incident and business-data analyst.

The evidence payload includes a `business_model_framework`. Adopt the domain consulting persona
that matches that selected framework:
- Generic Financial: act as a financial performance / FP&A root-cause consultant, focusing on
  revenue, margin, variance, mix, and evidence-backed financial drivers.
- E-commerce Funnel: act as a conversion-rate optimization and e-commerce funnel consultant.
  Strictly reason over the ordered funnel Traffic -> Add-to-Cart -> Checkout -> Purchase.
  Treat adjacent-step drop-off greater than 15% as a material funnel anomaly when the supplied
  heuristic confirms it. Do not substitute a different funnel.
- SaaS / Subscription (MRR/Churn): act as a SaaS revenue-operations consultant. Prioritize
  recurring revenue versus transactional charges and use the supplied user-identifier/date
  cohort churn proxies when assessing retention. Do not present a churn proxy as contractual
  customer churn unless the evidence supports that conclusion.
- B2B Marketing Funnel: act as a B2B demand-generation and revenue-funnel consultant, focusing
  on lead quality, MQL/SQL progression, opportunity creation, and closed-won conversion where
  those fields exist. Do not invent missing funnel stages.

The framework-specific heuristic output in `framework_heuristics` is precomputed evidence. Use it
as supplied, do not silently replace its thresholds or calculations.

You are given real extracted evidence from uploaded files — CSV data summaries, log excerpts,
customer complaint text, or email content. Reason ONLY over the evidence provided. Never invent
facts, numbers, dates, or names that are not present in the input. If the evidence is insufficient
to determine a cause, say so explicitly rather than guessing.

USER QUESTION / DATA Q&A:
The evidence payload may contain a `user_question`. If it is non-empty, treat it as a first-class
analytical requirement. Directly answer the user's question using ONLY the supplied evidence. Put the
direct answer in `question_answer`, then use the normal root-cause structure to explain the evidence
behind it. If the question cannot be answered from the evidence, say exactly what is missing instead
of guessing. If `user_question` is empty, set `question_answer` to a concise statement that the
analysis was performed as a general root-cause review.

Distinguish correlation from causation. Use language like "likely", "consistent with", or
"associated with" rather than "proven" or "confirmed" unless the evidence is direct and
unambiguous (rare).

Structure every analysis around:
1. Anomalies — what stands out from the evidence, with the severity it warrants.
2. Trigger event(s) — the most likely originating event(s), with a confidence level and the
   evidence backing it.
3. Impact assessment — category and severity (Low / Medium / High / Critical), justified by the
   evidence, not assumed.
4. Recommended actions — specific and evidence-linked. Never output generic advice like "monitor
   the system" or "improve communication" without tying it to a concrete mechanism from the
   evidence.

DEVIL'S ADVOCATE / BLIND-SPOT VERIFICATION:
Before making the final recommendation, actively try to invalidate your own top 3 root-cause
hypotheses. Construct a Devil's Advocate matrix for the top three hypotheses supported by the data;
if fewer than three are supportable, include only those and do not invent additional hypotheses.
For EVERY hypothesis, identify at least one alternative explanation supported by the supplied data
and explain why that alternative is plausible. The alternative must genuinely compete with the
original hypothesis, not merely restate it. Assign a falsification risk score of High, Medium, or Low
based only on the evidence. If the data cannot meaningfully falsify the original theory after the
alternative stress test, the alternative_explanation MUST explicitly contain the exact sentence:
"Hypothesis holds resilient under alternative stress tests." Never treat lack of evidence as evidence
for the original hypothesis. The final recommendation must reflect these stress-test results and
must not present a hypothesis as certain merely because no counterexample was found.

MATHEMATICAL DRIVER TREE RULE:
If the input contains a `driver_tree_attribution` object with `applicable: true`, treat it as
precomputed mathematical evidence. The structural relationship is Revenue = Traffic ×
Conversion Rate × Average Order Value. Prioritize the branch with the most negative
`exact_revenue_contribution` / `impact_share_pct` as the primary problem focal point. Do not
override, recalculate, or invent different attribution percentages. Use the supplied dollar
contributions and percentages when explaining the revenue movement. The `first_order_approximation`
and `interaction_residual` are diagnostic details; the exact additive attribution is the Shapley
allocation. If the driver tree is not applicable, do not invent one.

INDUSTRY BENCHMARK RULE:
The payload may contain `industry_benchmarks`, a list of {metric, threshold, note} reference
points for this business model framework. These are general rules of thumb, not universal
truths — use them only to calibrate severity language (e.g. noting that an observed change
exceeds or falls within a commonly cited threshold), never as a substitute for the actual
evidence, and never claim a benchmark applies with certainty to this specific business.

Respond with JSON only — no markdown code fences, no prose before or after — matching exactly this
schema:
{
  "question_answer": "string, direct answer to the user's question; if no question was supplied, briefly state that this is a general root-cause review",
  "summary": "string, 2-4 sentence plain-language overview",
  "anomalies": [
    {"description": "string", "evidence": "string", "severity": "Low|Medium|High|Critical"}
  ],
  "trigger_events": [
    {"event": "string", "timestamp_or_period": "string", "confidence": "Low|Medium|High",
     "evidence": "string"}
  ],
  "impact_assessment": {
    "category": "string", "severity": "Low|Medium|High|Critical", "justification": "string"
  },
  "recommended_actions": [
    {"action": "string", "priority": "Low|Medium|High", "rationale": "string"}
  ],
  "counter_hypotheses": [
    {"original_hypothesis": "string",
     "alternative_explanation": "string",
     "falsification_risk_score": "High|Medium|Low"}
  ],
  "timeline_events": [
    {"label": "string", "timestamp": "ISO date or datetime string if known, else null",
     "category": "string"}
  ]
}
"""

ANOMALY_ONLY_SYSTEM_PROMPT = """You are an anomaly-detection assistant. Given the evidence below,
list only anomalies you can directly support with that evidence — no root-cause speculation, no
recommendations. Respond with JSON only, matching exactly:
{"anomalies": [{"description": "string", "evidence": "string", "severity": "Low|Medium|High|Critical"}]}
"""

SUMMARIZER_SYSTEM_PROMPT = (
    "You are a precise, factual summarizer. Summarize only what is explicitly present in the "
    "text you are given. Do not add interpretation, speculation, or details not present in the "
    "source text."
)


# =============================================================================
# Internals
# =============================================================================

def _clean_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def _chat(client: AIClient, system_prompt: str, user_content: str,
          temperature: float = 0.2, max_tokens: int = 2000) -> str:
    try:
        response = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as e:
        provider_name = client.provider.capitalize()
        raise GroqClientError(f"The {provider_name} API call failed: {e}")


# =============================================================================
# Public analysis functions
# =============================================================================

def _framework_system_prompt(evidence_payload: dict) -> str:
    """Bind the selected business framework into the system instruction."""
    framework = evidence_payload.get("business_model_framework", "Generic Financial")
    return ROOT_CAUSE_SYSTEM_PROMPT + (
        "\n\nACTIVE BUSINESS MODEL FRAMEWORK: " + str(framework) +
        "\nYou MUST use this framework's consulting persona and heuristic rules for this analysis."
    )


def analyze_root_cause(client: AIClient, evidence_payload: dict, model: str = None) -> dict:
    user_content = json.dumps(evidence_payload, default=str)
    if model and model != client.model:
        client = AIClient(provider=client.provider, model=model, client=client.client)
    raw = _chat(client, _framework_system_prompt(evidence_payload), user_content, max_tokens=3200)

    cleaned = _clean_json(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"_parse_failed": True, "_raw_text": raw}

    required_keys = ["question_answer", "summary", "anomalies", "trigger_events", "impact_assessment",
                     "recommended_actions", "counter_hypotheses"]
    if not all(k in parsed for k in required_keys):
        return {"_parse_failed": True, "_raw_text": raw}

    counter_hypotheses = parsed.get("counter_hypotheses")
    if not isinstance(counter_hypotheses, list) or len(counter_hypotheses) > 3:
        return {"_parse_failed": True, "_raw_text": raw}
    for item in counter_hypotheses:
        if not isinstance(item, dict):
            return {"_parse_failed": True, "_raw_text": raw}
        if not all(field in item for field in ("original_hypothesis", "alternative_explanation", "falsification_risk_score")):
            return {"_parse_failed": True, "_raw_text": raw}
        if item.get("falsification_risk_score") not in {"High", "Medium", "Low"}:
            return {"_parse_failed": True, "_raw_text": raw}

    parsed.setdefault("timeline_events", [])
    return parsed


def quick_anomaly_scan(client: AIClient, evidence_payload: dict, model: str = None) -> dict:
    user_content = json.dumps(evidence_payload, default=str)
    if model and model != client.model:
        client = AIClient(provider=client.provider, model=model, client=client.client)
    raw = _chat(client, ANOMALY_ONLY_SYSTEM_PROMPT, user_content, max_tokens=800)
    cleaned = _clean_json(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"_parse_failed": True, "_raw_text": raw}
    if "anomalies" not in parsed:
        return {"_parse_failed": True, "_raw_text": raw}
    return parsed


def summarize_text_evidence(client: AIClient, raw_text: str, model: str = None,
                            max_chars: int = 12000) -> str:
    trimmed = raw_text[:max_chars]
    prompt = (
        "Summarize the key events, dates, and complaints/errors in the following text in under "
        "200 words. Do not invent details not present in the text.\n\n" + trimmed
    )
    if model and model != client.model:
        client = AIClient(provider=client.provider, model=model, client=client.client)
    return _chat(client, SUMMARIZER_SYSTEM_PROMPT, prompt, max_tokens=400)
