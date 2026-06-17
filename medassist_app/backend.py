"""
Backend logic for PV Review Frontend.

Handles:
  1. RSI lookup from rsi_mapping.json
  2. Per-drug PV review via the fine-tuned model (OpenAI-compatible API)
  3. Consolidated report generation via the base model

Auth note: The vLLM server is behind a Jupyter proxy. We use requests (with a
session cookie obtained by logging in with the Jupyter token) as the httpx
transport so the OpenAI SDK can pass through the Jupyter auth automatically.
"""

import json
import re
import os
import urllib.request
import urllib.parse
import http.cookiejar
from typing import Optional
import httpx
from openai import OpenAI

from config import (
    JUPYTER_BASE_URL,
    JUPYTER_TOKEN,
    FINETUNED_MODEL_BASE_URL,
    FINETUNED_MODEL_NAME,
    FINETUNED_MAX_TOKENS,
    FINETUNED_TEMPERATURE,
    FINETUNED_TOP_P,
    BASE_MODEL_BASE_URL,
    BASE_MODEL_NAME,
    BASE_MODEL_API_KEY,
    BASE_MAX_TOKENS,
    BASE_TEMPERATURE,
    RSI_MAPPING_PATH,
)

# ─── System Prompt (matches fine-tune training data exactly) ─────────────────
PV_SYSTEM_PROMPT = (
    "You are a Pharmacovigilance (PV) Medical Review Assistant.\n\n"
    "CRITICAL RULES:\n"
    "1. Base your 'Expectedness' evaluation STRICTLY on the RSI (Reference Safety Information) "
    "provided in the prompt. Do NOT use your own pre-trained clinical knowledge. If the prompt "
    "states 'RSI not available', you must output 'Cannot Evaluate' for expectedness.\n"
    "2. Base all other evaluations strictly on the Patient Narrative. Do not hallucinate external details.\n\n"
    "Output a clinical Chain of Thought as plain text first, followed by a markdown JSON block "
    "containing exactly four keys: 'seriousness', 'meddra_pt', 'expectedness', and 'causality'. "
    "Do NOT include 'chain_of_thought' inside the JSON dictionary.\n\n"
    "SCENARIOS:\n"
    "Valid Case: Assess Seriousness (criteria & MedDRA PT), Expectedness (strictly via provided RSI), "
    "and Causality (Naranjo score & interpretation).\n\n"
    "Rejection Case (Drug Mismatch / Noise): If the suspected drug in the narrative does not match "
    "the prompt's context, or the narrative lacks clinical data, explicitly state "
    "\"Drug Mismatch - Cannot Evaluate\" or \"Evaluation failed\" in your reasoning text. "
    "Then, set is_serious to false, output \"N/A\" for meddra_pt and expectedness, and output 0 for Naranjo score."
)

# ─── User Prompt Template ─────────────────────────────────────────────────────
PV_USER_PROMPT_TEMPLATE = """\
Conduct a medical safety review of the following adverse event case:

Patient Narrative:
{patient_narrative}

Reference Safety Information (RSI) for {suspected_drug}:
{rsi_text}

[INSTRUCTIONS]
Perform three tasks:
1. Seriousness Assessment: Determine if the adverse event is serious based on standard regulatory criteria \
(Death, Hospitalization, Life-threatening, Disabling, Congenital Anomaly, or Other medically important event). \
Identify the exact MedDRA Preferred Term (PT) for the primary adverse event as a text string (e.g. 'Myocardial infarction').
2. Expectedness Assessment: Compare the Patient Narrative adverse event against the provided drug's RSI text \
to determine if it is 'Expected' (Labelled) or 'Unexpected' (Unlabelled). If the RSI text is not available \
(i.e. 'RSI not available'), you must output 'Cannot Evaluate'. Do NOT use your own pre-trained medical knowledge.
3. Causality Assessment: Evaluate the relationship between the drug and the adverse event by applying the \
Naranjo scale logic. Deduce the score and assign the interpretation: Definite (>= 9), Probable (5-8), \
Possible (1-4), or Doubtful (<= 0).
"""

# ─── Consolidation Prompt ────────────────────────────────────────────────────
CONSOLIDATION_SYSTEM_PROMPT = (
    "You are a senior Clinical Pharmacovigilance (PV) Scientist preparing a formal safety report. "
    "You will receive structured PV assessment findings for one or more drugs suspected in a single "
    "adverse event case. Based STRICTLY on the provided findings and the original patient narrative, "
    "synthesize a clear, structured, professional clinical summary report. "
    "Do not add information not present in the provided context. "
    "Format the report with clear sections: Case Overview, Per-Drug Assessment Summary, "
    "Overall Causality Conclusion, and Recommended Actions."
)

CONSOLIDATION_USER_TEMPLATE = """\
Patient Narrative:
{patient_narrative}

The following per-drug pharmacovigilance assessments were completed by a specialized PV review model:

{all_findings}

---
Based SOLELY on the above, generate a concise, structured Clinical PV Summary Report covering:
1. **Case Overview** – Brief description of the patient and event(s).
2. **Per-Drug Assessment Summary** – Table or bullet-point summary for each drug: Seriousness, MedDRA PT, Expectedness, Naranjo Score & Interpretation.
3. **Overall Causality Conclusion** – Which drug(s) are the most probable suspect(s) based on the assessments?
4. **Recommended Actions** – Any recommended regulatory or clinical actions (e.g., expedited reporting, label update consideration, further investigation).
"""

# ─── RSI Loading ─────────────────────────────────────────────────────────────
_rsi_cache: Optional[dict] = None


def load_rsi_mapping() -> dict:
    """Load and cache the RSI mapping from disk."""
    global _rsi_cache
    if _rsi_cache is None:
        if not os.path.exists(RSI_MAPPING_PATH):
            raise FileNotFoundError(
                f"RSI mapping not found at '{RSI_MAPPING_PATH}'. "
                "Run setup_rsi.py to copy it from the data/ directory."
            )
        with open(RSI_MAPPING_PATH, "r", encoding="utf-8") as f:
            _rsi_cache = json.load(f)
    return _rsi_cache


def lookup_rsi(drug_name: str) -> str:
    """
    Look up RSI text for a given drug name.
    Attempts exact match first, then case-insensitive partial match.
    Returns 'RSI not available' if no match is found.
    """
    rsi_map = load_rsi_mapping()

    # Exact match
    if drug_name in rsi_map:
        return rsi_map[drug_name]

    # Case-insensitive exact match
    drug_lower = drug_name.strip().lower()
    for key, val in rsi_map.items():
        if key.lower() == drug_lower:
            return val

    # Partial match (drug name is a substring of a key or vice versa)
    for key, val in rsi_map.items():
        if drug_lower in key.lower() or key.lower() in drug_lower:
            return val

    return "RSI not available"


# ─── Jupyter-Authenticated HTTP Client ───────────────────────────────────────
_jupyter_cookies: Optional[dict] = None


def _get_jupyter_cookies() -> dict:
    """
    Log in to Jupyter once, cache the session cookies.
    Returns a dict suitable for use as httpx headers (Cookie: ...).
    """
    global _jupyter_cookies
    if _jupyter_cookies is not None:
        return _jupyter_cookies

    login_url = JUPYTER_BASE_URL + "/login"
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    # GET login page to extract XSRF token
    import re as _re
    page = opener.open(login_url).read().decode()
    xsrf_match = _re.search(r'name="_xsrf"\s+value="([^"]+)"', page)
    xsrf = xsrf_match.group(1) if xsrf_match else ""

    # POST credentials
    data = urllib.parse.urlencode({"password": JUPYTER_TOKEN, "_xsrf": xsrf}).encode()
    req = urllib.request.Request(
        login_url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    opener.open(req)

    # Collect cookies into a plain dict
    cookie_str = "; ".join(f"{c.name}={c.value}" for c in cj)
    _jupyter_cookies = {"Cookie": cookie_str}
    return _jupyter_cookies


def _get_finetuned_client() -> OpenAI:
    """
    Returns an OpenAI client for the fine-tuned model.
    Uses a custom httpx client that injects the Jupyter session cookie
    so requests pass through the Jupyter proxy transparently.
    """
    from config import FINETUNED_API_KEY
    cookies = _get_jupyter_cookies()
    http_client = httpx.Client(headers=cookies, follow_redirects=True)
    return OpenAI(
        base_url=FINETUNED_MODEL_BASE_URL,
        api_key=FINETUNED_API_KEY,
        http_client=http_client,
    )


def _get_base_client() -> OpenAI:
    """Returns an OpenAI client pointed at the base/consolidation model server."""
    return OpenAI(
        base_url=BASE_MODEL_BASE_URL,
        api_key=BASE_MODEL_API_KEY,
    )


# ─── Per-Drug PV Assessment ──────────────────────────────────────────────────
def run_pv_assessment(narrative: str, drug: str) -> dict:
    """
    Call the fine-tuned PV model for a single drug.

    Returns a dict with:
      - drug (str)
      - rsi_found (bool)
      - raw_response (str)
      - chain_of_thought (str)
      - json_data (dict or None)
      - error (str or None)
    """
    rsi_text = lookup_rsi(drug)
    rsi_found = rsi_text != "RSI not available"

    user_prompt = PV_USER_PROMPT_TEMPLATE.format(
        patient_narrative=narrative.strip(),
        suspected_drug=drug.strip(),
        rsi_text=rsi_text,
    )

    try:
        client = _get_finetuned_client()
        response = client.chat.completions.create(
            model=FINETUNED_MODEL_NAME,
            messages=[
                {"role": "system", "content": PV_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=FINETUNED_MAX_TOKENS,
            temperature=FINETUNED_TEMPERATURE,
            top_p=FINETUNED_TOP_P,
        )

        raw = response.choices[0].message.content or ""

        # Parse chain of thought and JSON block
        json_data = None
        chain_of_thought = raw
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if json_match:
            chain_of_thought = raw[: json_match.start()].strip()
            try:
                json_data = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Fallback: try to parse from raw braces
        if json_data is None:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    json_data = json.loads(raw[start : end + 1])
                    chain_of_thought = raw[:start].strip()
                except json.JSONDecodeError:
                    pass

        return {
            "drug": drug,
            "rsi_found": rsi_found,
            "raw_response": raw,
            "chain_of_thought": chain_of_thought,
            "json_data": json_data,
            "error": None,
        }

    except Exception as e:
        return {
            "drug": drug,
            "rsi_found": rsi_found,
            "raw_response": "",
            "chain_of_thought": "",
            "json_data": None,
            "error": str(e),
        }


# ─── Consolidated Report ─────────────────────────────────────────────────────
def generate_consolidated_report(narrative: str, per_drug_results: list[dict]) -> str:
    """
    Call the base model to synthesize all per-drug PV findings into a final report.

    per_drug_results: list of dicts returned by run_pv_assessment()
    Returns the consolidated report as a markdown string.
    """
    findings_parts = []
    for i, result in enumerate(per_drug_results, 1):
        drug = result["drug"]
        if result["error"]:
            findings_parts.append(
                f"### Drug {i}: {drug}\n"
                f"**Error during assessment:** {result['error']}\n"
            )
            continue

        jd = result.get("json_data") or {}
        seriousness = jd.get("seriousness", {})
        findings_parts.append(
            f"### Drug {i}: {drug}\n"
            f"- **RSI Available:** {'Yes' if result['rsi_found'] else 'No'}\n"
            f"- **Is Serious:** {seriousness.get('is_serious', 'N/A')}\n"
            f"- **Seriousness Criteria:** {seriousness.get('criteria', 'N/A')}\n"
            f"- **MedDRA PT:** {jd.get('meddra_pt', 'N/A')}\n"
            f"- **Expectedness:** {jd.get('expectedness', 'N/A')}\n"
            f"- **Naranjo Score:** {jd.get('causality', {}).get('naranjo_score', 'N/A')}\n"
            f"- **Causality Interpretation:** {jd.get('causality', {}).get('interpretation', 'N/A')}\n"
            f"\n**Clinical Reasoning:**\n{result['chain_of_thought']}\n"
        )

    all_findings_text = "\n---\n".join(findings_parts)
    user_prompt = CONSOLIDATION_USER_TEMPLATE.format(
        patient_narrative=narrative.strip(),
        all_findings=all_findings_text,
    )

    try:
        client = _get_base_client()
        response = client.chat.completions.create(
            model=BASE_MODEL_NAME,
            messages=[
                {"role": "system", "content": CONSOLIDATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=BASE_MAX_TOKENS,
            temperature=BASE_TEMPERATURE,
        )
        return response.choices[0].message.content or "No report generated."
    except Exception as e:
        return f"**Error generating consolidated report:** {e}"


# ─── Full Pipeline Orchestrator ───────────────────────────────────────────────
def run_full_analysis(narrative: str, drugs: list[str]) -> tuple[list[dict], str]:
    """
    Run the complete PV analysis pipeline:
      1. For each drug, call the fine-tuned model.
      2. Call the base model to consolidate findings.

    Returns (per_drug_results, consolidated_report_markdown).
    """
    drugs_clean = [d.strip() for d in drugs if d.strip()]
    per_drug_results = [run_pv_assessment(narrative, drug) for drug in drugs_clean]
    report = generate_consolidated_report(narrative, per_drug_results)
    return per_drug_results, report
