"""
Phase 7, 8 & 10: RAG-grounded LLM analysis + Wattson, the follow-up chatbot.

Uses the Gemini API directly over REST (no SDK needed -- keeps the
dependency list small and easy to explain line-by-line in viva).

Get a free key from https://aistudio.google.com/apikey and set it as:
    export GEMINI_API_KEY="your-key-here"

IMPORTANT (unchanged design principle):
The LLM never does arithmetic. calculation.py's numbers are ground truth;
the LLM only explains, personalizes, reads documents visually, and converses.

WHAT'S NEW IN THIS VERSION
---------------------------
1. Vision-based document reading: instead of relying only on OCR/regex text
   (which is fragile on real bill photos), analyze_bill_document_with_vision()
   sends the ORIGINAL image or PDF bytes straight to Gemini, the same way a
   person would look at the bill. Gemini reads every visible field -- not
   just the ones our regex patterns anticipated -- and returns structured
   JSON plus free-text notes on anything else useful it noticed.
2. RAG grounding: analyze_bill_with_llm() and chat_about_bill() now accept
   retrieved knowledge-base context (from rag/retriever.py) and are told to
   ground their advice in it rather than general/invented knowledge.
3. The chatbot has a name: Wattson.
"""

import base64
import json
import mimetypes
import os
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# gemini-2.5-flash-lite is deprecated (official shutdown Oct 16, 2026) and has
# been returning 404 "no longer available" ahead of that date since July 9,
# 2026. gemini-3.1-flash-lite is Google's official recommended replacement --
# stable (GA, not preview), released May 7, 2026, no shutdown before May 7,
# 2027. Endpoint/API version (v1beta) is unchanged and still correct per
# https://ai.google.dev/gemini-api/docs/deprecations (checked against the
# live docs page).
MODEL = "gemini-3.1-flash-lite"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

BOT_NAME = "Wattson"

SYSTEM_INSTRUCTION = f"""You are {BOT_NAME}, a friendly residential energy advisor for the WattWise app.

Rules you must follow:
- You are given bill data, calculated metrics, an energy score, and appliance
  usage that were computed by deterministic Python code. Treat these numbers
  as ground truth -- never recalculate or contradict them.
- When "Retrieved energy-saving knowledge" is provided in the prompt, base your
  recommendations on it and prefer it over general knowledge. If nothing
  relevant was retrieved, you may still give sound general advice, but do not
  claim it came from a trusted source.
- Do not invent exact rupee savings figures beyond what's given to you in the
  data. If asked something you don't have enough data for, say so and ask
  the user for the missing detail instead of guessing.
- When reading a bill document directly (image or PDF), report only what is
  actually visible on the page. Never guess or fabricate a consumer number,
  reading, date, or amount that you cannot actually see -- return null for it
  instead.
- Keep responses concise, warm, and practical -- this is for a student's
  household bill, not a corporate report.
- The "WattWise Energy Score" is our own heuristic, not an official utility
  or government rating. Never imply otherwise.
- Sign off as {BOT_NAME} in spirit (friendly tone), but don't literally
  prefix every message with your name.
"""

BILL_FIELD_KEYS = [
    "consumer_number", "current_reading", "previous_reading",
    "units_consumed", "bill_amount", "billing_month", "tariff",
]


# ---------------------------------------------------------------------------
# Low-level Gemini call, with optional image/PDF attachment
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, file_path: str | None = None, max_tokens: int = 500) -> str:
    """
    Calls Gemini with a text prompt, optionally attaching the raw bytes of
    an image or PDF so the model can visually read the document -- the same
    way a person looking at the bill would, rather than depending only on
    OCR text extraction.
    """
    if not GEMINI_API_KEY:
        return ("[LLM not configured] Set the GEMINI_API_KEY environment variable "
                "to enable AI analysis. Showing raw calculated numbers only for now.")

    parts = [{"text": prompt}]

    if file_path:
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(file_bytes).decode("utf-8"),
                }
            })
        except OSError:
            pass  # fall back to text-only if the file can't be read

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": max_tokens},
    }

    try:
        response = requests.post(API_URL, params={"key": GEMINI_API_KEY}, json=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    except requests.exceptions.HTTPError:
        # Pull out Google's own error message/status from the JSON body so the
        # user sees WHY the call failed, not just the generic HTTP error text.
        google_message, google_status = None, None
        try:
            error_body = response.json().get("error", {})
            google_message = error_body.get("message")
            google_status = error_body.get("status")
        except (ValueError, AttributeError):
            pass

        detail = (
            f"[Gemini API error] Status: {response.status_code}"
            f" | Google status: {google_status or 'unknown'}"
            f" | Model: {MODEL}"
            f" | Endpoint: {API_URL}"
            f" | Message: {google_message or response.text[:300]}"
        )
        return detail + "\nShowing raw calculated numbers only."

    except requests.exceptions.RequestException as e:
        detail = f"[LLM request failed] Model: {MODEL} | Endpoint: {API_URL} | Error: {e}"
        return detail + "\nShowing raw calculated numbers only."

    except (KeyError, IndexError):
        return "[LLM returned an unexpected response] Showing raw calculated numbers only."


def _extract_json_object(candidate: str) -> dict:
    """Extract the first balanced JSON object found in text."""
    start = candidate.find("{")
    if start == -1:
        return {}

    depth = 0
    for idx in range(start, len(candidate)):
        ch = candidate[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_text = candidate[start:idx + 1]
                try:
                    return json.loads(json_text)
                except json.JSONDecodeError:
                    return {}
    return {}


def _normalize_bill_fields(parsed: dict) -> dict:
    normalized = {}
    for key in BILL_FIELD_KEYS:
        value = parsed.get(key)
        if value is None:
            normalized[key] = None
        elif key == "bill_amount":
            try:
                normalized[key] = float(str(value).replace(",", "").replace("₹", "").strip())
            except ValueError:
                normalized[key] = None
        elif key in ("current_reading", "previous_reading", "units_consumed"):
            try:
                normalized[key] = int(float(str(value).replace(",", "").strip()))
            except ValueError:
                normalized[key] = None
        else:
            normalized[key] = str(value).strip()
    return normalized


# ---------------------------------------------------------------------------
# Phase 1b/2b: VISION-based document reading (the main fix)
# ---------------------------------------------------------------------------

_VISION_EXTRACTION_PROMPT = """Look at this electricity bill document (image or PDF) carefully,
the same way a person would read the physical page -- including any tables,
stamps, small print, or handwriting. Do not rely on any text I might separately
give you; read the document itself.

Return ONLY valid JSON, nothing else, in exactly this schema:
{
  "consumer_number": null,
  "current_reading": null,
  "previous_reading": null,
  "units_consumed": null,
  "bill_amount": null,
  "billing_month": null,
  "tariff": null,
  "visual_notes": null
}

Rules:
- Use null for any field you genuinely cannot find on the page. Never guess.
- "units_consumed" is the units billed this period (sometimes labelled
  "units consumed", "consumption", or derivable as current minus previous
  reading if both are visible and consumption isn't printed directly).
- "visual_notes" should be a short (1-3 sentence) free-text note on anything
  else relevant you noticed on the page -- e.g. arrears, due date, sanctioned
  load, connection type, meter reading date, or that the image was blurry/
  cut off in a way that affected what you could read. Use null if there's
  nothing extra to add.
"""


def analyze_bill_document_with_vision(file_path: str) -> dict:
    """
    Sends the ORIGINAL bill file (image or PDF) to Gemini so it can visually
    read every field on the page, not just the ones regex/OCR text happened
    to catch. Returns a dict with the standard bill fields plus "visual_notes".
    Returns {} if the LLM isn't configured or the call fails.
    """
    if not GEMINI_API_KEY:
        return {}

    response = _call_gemini(_VISION_EXTRACTION_PROMPT, file_path=file_path, max_tokens=400)
    parsed = _extract_json_object(response)
    if not parsed:
        return {}

    normalized = _normalize_bill_fields(parsed)
    normalized["visual_notes"] = parsed.get("visual_notes")
    return normalized


def analyze_bill_document_freeform(file_path: str, raw_text: str = "") -> str:
    """
    Used when even the vision-based structured extraction can't derive the
    numbers we need for the calculation engine (e.g. a badly damaged or
    non-standard bill). Instead of failing, Wattson looks at the actual
    document and gives the best analysis it can in plain language.
    """
    if not GEMINI_API_KEY:
        return ("[LLM not configured] Set the GEMINI_API_KEY environment variable "
                "to enable AI analysis. Showing raw calculated numbers only for now.")

    prompt = f"""Look at this electricity bill document directly and answer as {BOT_NAME},
a helpful residential energy advisor.

Extract and describe whatever useful information you can see on the page,
even if some standard fields are missing or unclear. Do not invent exact
numbers you cannot actually see.

Write:
1. A short summary of the bill and any consumption or cost signals visible.
2. The most likely reason for higher usage, if that's visible or inferable.
3. Practical, actionable recommendations the user can apply.

(For reference, here is whatever OCR text extraction managed to capture --
use it only as a secondary hint, the document image/PDF itself is the
primary source of truth: {raw_text[:1500] if raw_text else "none available"})
"""
    return _call_gemini(prompt, file_path=file_path, max_tokens=500)


# ---------------------------------------------------------------------------
# Phase 8: RAG-grounded one-shot bill analysis
# ---------------------------------------------------------------------------

def build_bill_context(bill_data: dict, metrics: dict, score: dict, breakdown: dict | None) -> str:
    """Turn the deterministic results into a compact text block for the LLM."""
    lines = [
        f"Units consumed: {bill_data.get('units_consumed')}",
        f"Bill amount: Rs {bill_data.get('bill_amount')}",
        f"Change vs previous month: {metrics.get('percentage_change')}% ({metrics.get('trend')})",
        f"Cost per unit: Rs {metrics.get('cost_per_unit')}",
        f"WattWise Energy Score: {score.get('score')}/100 ({score.get('rating')})",
    ]
    if breakdown:
        lines.append("Appliance usage breakdown:")
        for name, d in breakdown.items():
            lines.append(f"  - {name}: {d['kwh']} kWh/month ({d['percent_share']}% of tracked usage)")
    return "\n".join(lines)


def analyze_bill_with_llm(bill_data: dict, metrics: dict, score: dict,
                           breakdown: dict | None, rag_context: str = "") -> str:
    """Phase 8: RAG-grounded natural-language explanation of the bill."""
    context = build_bill_context(bill_data, metrics, score, breakdown)

    rag_block = (
        f"\nRetrieved energy-saving knowledge (ground your advice in this):\n{rag_context}\n"
        if rag_context else ""
    )

    prompt = f"""Here is this user's electricity bill analysis:

{context}
{rag_block}
Write:
1. A short consumption summary (1-2 sentences)
2. The likely reason(s) for the change, based on the appliance data if present
3. Up to three practical, personalized recommendations, grounded in the
   retrieved knowledge above where relevant
4. One line on the overall consumption assessment

Keep the whole thing under 150 words."""
    return _call_gemini(prompt, max_tokens=500)


# ---------------------------------------------------------------------------
# Phase 10: Wattson, the follow-up chatbot
# ---------------------------------------------------------------------------

def chat_about_bill(bill_context: str, conversation_history: list,
                     user_question: str, rag_context: str = "") -> str:
    """
    conversation_history is a list of {"role": "user"/"assistant", "text": "..."}
    dicts kept in the Flask session so Wattson remembers earlier turns.
    rag_context (optional) is retrieved knowledge relevant to this specific
    question, from rag/retriever.py.
    """
    if not GEMINI_API_KEY:
        return ("[LLM not configured] Set the GEMINI_API_KEY environment variable "
                "to enable the chatbot.")

    history_text = "\n".join(
        f"{'User' if h['role'] == 'user' else BOT_NAME}: {h['text']}"
        for h in conversation_history[-6:]
    )

    rag_block = (
        f"\nRetrieved energy-saving knowledge relevant to this question:\n{rag_context}\n"
        if rag_context else ""
    )

    prompt = f"""This user's bill data:
{bill_context}
{rag_block}
Conversation so far:
{history_text}

New question from the user: {user_question}

Answer specifically using their bill data above. If the question needs
information you don't have (e.g. an appliance they haven't told you about),
ask them for it instead of guessing."""

    return _call_gemini(prompt, max_tokens=400)


if __name__ == "__main__":
    sample_bill = {"units_consumed": 420, "bill_amount": 3650.0}
    sample_metrics = {"percentage_change": 44.83, "trend": "increased", "cost_per_unit": 8.69}
    sample_score = {"score": 45, "rating": "High Consumption"}
    sample_breakdown = {
        "AC": {"kwh": 234.0, "percent_share": 79.8},
        "Refrigerator": {"kwh": 50.4, "percent_share": 17.2},
        "TV": {"kwh": 9.0, "percent_share": 3.1},
    }
    print(analyze_bill_with_llm(sample_bill, sample_metrics, sample_score, sample_breakdown))
