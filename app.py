"""
WattWise - Full pipeline with vision-based extraction, RAG grounding,
Wattson (chatbot), history dashboard, bill comparison, PDF export, and email.

Pipeline:
  Upload bill -> extract text (regex, fast/free)
              -> if fields missing: vision LLM reads the ORIGINAL file directly
              -> calculation engine -> energy score
              -> RAG retrieval (knowledge_base/) -> LLM analysis (grounded)
              -> save to history.db (permanent, one row per upload)
              -> dashboard (nav sidebar, main center, recent-history right)
              -> optional PDF export / email
              -> Wattson chat lives on its own page
              -> any number of saved bills can be compared side-by-side

Key design principle (unchanged): the LLM never does arithmetic.
calculation.py's numbers are ground truth. The LLM explains, personalizes,
reads documents visually when needed, and converses -- never calculates.
"""

import os
import uuid
from flask import (Flask, render_template, request, redirect, url_for,
                    flash, session, jsonify, send_file)

from extraction import extract_text, parse_bill_text
from calculation import (
    calculate_metrics, energy_score, appliance_breakdown, simulate_savings,
    APPLIANCES, STAR_RATING_MULTIPLIERS,
)
from llm import (
    analyze_bill_with_llm,
    analyze_bill_document_freeform,
    analyze_bill_document_with_vision,
    chat_about_bill,
    build_bill_context,
    BOT_NAME,
<<<<<<< HEAD
    MODEL as LLM_MODEL,
    GEMINI_API_KEY,
=======
>>>>>>> 678ede362b6dfb8746e9ab27f1e398fe3bc83a7e
)
from rag.retriever import retrieve_context
import history
import pdf_export
import email_service

app = Flask(__name__)
app.secret_key = "dev-only-change-me"  # fine for localhost dev
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}

BILL_FIELDS = ["consumer_number", "current_reading", "previous_reading",
               "units_consumed", "bill_amount", "billing_month", "tariff"]

history.init_db()


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_upload(file_storage) -> str:
    """Saves an uploaded file under a unique name so re-uploading a bill
    with the same filename never overwrites a previous one on disk. Every
    upload is kept permanently in the uploads/ folder."""
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}_{file_storage.filename}"
    path = os.path.join(UPLOAD_FOLDER, unique_name)
    file_storage.save(path)
    return path


def _merge_vision_fields(bill_data: dict, file_path: str) -> tuple[dict, str | None]:
    """
    Sends the ORIGINAL bill file to the vision LLM and fills in any field
    the regex pass left as None. Returns (updated_bill_data, visual_notes).
    Regex-derived fields are trusted first (fast, free, deterministic);
    vision only fills the gaps, and never overwrites a value regex found.
    """
    vision_fields = analyze_bill_document_with_vision(file_path)
    if not vision_fields:
        return bill_data, None

    for field in BILL_FIELDS:
        if bill_data.get(field) is None and vision_fields.get(field) is not None:
            bill_data[field] = vision_fields[field]

    bill_data["missing_fields"] = [k for k, v in bill_data.items()
                                    if v is None and k in BILL_FIELDS]
    return bill_data, vision_fields.get("visual_notes")


def _recent_history(limit: int = 6) -> list[dict]:
    """Used to populate the right-hand history widget on every page --
    small enough to just fetch on every request."""
    return history.get_history(limit=limit)


@app.route("/")
<<<<<<< HEAD
def dashboard():
    stats = history.get_stats()
    recent = _recent_history(limit=8)
    latest = recent[0] if recent else None
    return render_template(
        "dashboard.html",
        bot_name=BOT_NAME,
        stats=stats,
        latest=latest,
        recent_history=recent,
        active_page="dashboard",
    )


@app.route("/upload")
def upload_page():
=======
def index():
>>>>>>> 678ede362b6dfb8746e9ab27f1e398fe3bc83a7e
    return render_template(
        "index.html",
        appliances=list(APPLIANCES.keys()),
        star_ratings=sorted(STAR_RATING_MULTIPLIERS.keys()),
        bot_name=BOT_NAME,
        recent_history=_recent_history(),
        active_page="upload",
    )


@app.route("/analyze", methods=["POST"])
def analyze_bill():
    current_file = request.files.get("current_bill")
    previous_file = request.files.get("previous_bill")  # optional, for comparison

    if not current_file or current_file.filename == "":
        flash("Please choose a bill file to upload.")
<<<<<<< HEAD
        return redirect(url_for("upload_page"))

    if not allowed_file(current_file.filename):
        flash("Unsupported file type. Upload a PDF, JPG, or PNG.")
        return redirect(url_for("upload_page"))
=======
        return redirect(url_for("index"))

    if not allowed_file(current_file.filename):
        flash("Unsupported file type. Upload a PDF, JPG, or PNG.")
        return redirect(url_for("index"))
>>>>>>> 678ede362b6dfb8746e9ab27f1e398fe3bc83a7e

    current_path = _save_upload(current_file)

    # --- Phase 1 & 2: extract + parse (deterministic, fast, free) ---
    raw_text = extract_text(current_path)
    bill_data = parse_bill_text(raw_text)
    visual_notes = None

    # --- Phase 1b: if regex missed fields, let the LLM SEE the actual
    # document (image/PDF bytes), not just OCR text. ---
    if bill_data.get("missing_fields"):
        bill_data, visual_notes = _merge_vision_fields(bill_data, current_path)

    previous_units = None
    if previous_file and previous_file.filename != "" and allowed_file(previous_file.filename):
        previous_path = _save_upload(previous_file)
        previous_raw = extract_text(previous_path)
        previous_data = parse_bill_text(previous_raw)
        if previous_data.get("units_consumed") is None:
            previous_data, _ = _merge_vision_fields(previous_data, previous_path)
        previous_units = previous_data.get("units_consumed")

    if previous_units is None:
        manual_previous = request.form.get("previous_units")
        previous_units = int(manual_previous) if manual_previous else None

    # If we STILL can't derive the required comparison numbers even after
    # the vision pass, fall back to a freeform vision analysis of the whole
    # document instead of failing completely.
    if bill_data.get("units_consumed") is None or previous_units is None:
        ai_analysis = analyze_bill_document_freeform(current_path, raw_text)
        session["bill_context"] = f"Raw bill text/notes: {raw_text}\n{ai_analysis}"
        session["chat_history"] = []
        session["last_bill_id"] = None  # not coherent enough to save to history

        return render_template(
            "results.html",
            bot_name=BOT_NAME,
            bill_data=bill_data,
            previous_units=previous_units,
            visual_notes=visual_notes,
            metrics={"difference": "—", "percentage_change": "—", "trend": "Unknown", "cost_per_unit": "—"},
            score={"score": "—", "rating": "Unknown"},
            breakdown=None,
            ai_analysis=ai_analysis,
            rag_sources=[],
            partial_analysis=True,
            appliances=list(APPLIANCES.keys()),
            star_ratings=sorted(STAR_RATING_MULTIPLIERS.keys()),
            recent_history=_recent_history(),
            bill_id=None,
            email_configured=email_service.is_configured(),
            active_page="upload",
        )

    # --- Phase 3 & 4: calculation engine + energy score ---
    metrics = calculate_metrics(
        current_units=bill_data["units_consumed"],
        previous_units=previous_units,
        bill_amount=bill_data.get("bill_amount") or 0,
    )
    score = energy_score(metrics["percentage_change"], bill_data["units_consumed"])

    # --- Phase 6 (+ star ratings): optional appliance usage from the form ---
    appliance_hours = {}
    star_ratings = {}
    for name in APPLIANCES:
        raw_hours = request.form.get(f"appliance_{name}")
        if raw_hours:
            try:
                appliance_hours[name] = float(raw_hours)
            except ValueError:
                pass
        raw_star = request.form.get(f"star_{name}")
        if raw_star:
            try:
                star_ratings[name] = int(raw_star)
            except ValueError:
                pass

    breakdown = appliance_breakdown(appliance_hours, star_ratings=star_ratings) if appliance_hours else None

    # --- Phase 7: RAG retrieval, grounded on what actually happened in this bill ---
    rag_query_parts = [f"electricity bill {metrics['trend']} {bill_data['units_consumed']} units"]
    if breakdown:
        top_appliance = max(breakdown.items(), key=lambda kv: kv[1]["kwh"])[0]
        rag_query_parts.append(f"{top_appliance} energy saving tips")
    rag_context, rag_sources = retrieve_context(" ".join(rag_query_parts), top_k=3)

    # --- Phase 8: LLM analysis, grounded in the retrieved knowledge ---
    ai_analysis = analyze_bill_with_llm(bill_data, metrics, score, breakdown, rag_context=rag_context)

    # --- Phase 11: save to history (permanent row, never overwritten) ---
    bill_id = history.save_bill_record(bill_data, metrics, score, ai_analysis,
                                        breakdown=breakdown, image_path=current_path)

    bill_context = build_bill_context(bill_data, metrics, score, breakdown)
    if visual_notes:
        bill_context += f"\nAdditional notes from reading the bill document: {visual_notes}"
    session["bill_context"] = bill_context
    session["cost_per_unit"] = metrics.get("cost_per_unit")
    session["chat_history"] = []
    session["last_bill_id"] = bill_id
    # Cache everything the PDF/email export needs, keyed by bill_id.
    session[f"bill_{bill_id}"] = {
        "bill_data": bill_data, "metrics": metrics, "score": score,
        "ai_analysis": ai_analysis, "breakdown": breakdown,
    }

    return render_template(
        "results.html",
        bot_name=BOT_NAME,
        bill_data=bill_data,
        previous_units=previous_units,
        visual_notes=visual_notes,
        metrics=metrics,
        score=score,
        breakdown=breakdown,
        ai_analysis=ai_analysis,
        rag_sources=rag_sources,
        appliances=list(APPLIANCES.keys()),
        star_ratings=sorted(STAR_RATING_MULTIPLIERS.keys()),
        recent_history=_recent_history(),
        bill_id=bill_id,
        email_configured=email_service.is_configured(),
        active_page="upload",
    )


# --- Phase 9: savings simulator (now star-rating aware) ---
@app.route("/simulate_savings", methods=["POST"])
def simulate_savings_route():
    data = request.get_json() or {}
    appliance = data.get("appliance")
    current_hours = data.get("current_hours")
    new_hours = data.get("new_hours")
    cost_per_unit = data.get("cost_per_unit")
    star_rating = data.get("star_rating")

    if appliance not in APPLIANCES:
        return jsonify({"error": "Unknown appliance."}), 400
    try:
        current_hours = float(current_hours)
        new_hours = float(new_hours)
        cost_per_unit = float(cost_per_unit) if cost_per_unit not in (None, "", "—") else 8.0
        star_rating = int(star_rating) if star_rating else None
    except (TypeError, ValueError):
        return jsonify({"error": "Please enter valid numbers for hours."}), 400

    result = simulate_savings(appliance, current_hours, new_hours, cost_per_unit, star_rating=star_rating)
    return jsonify(result)





# --- Phase 10: Wattson chat endpoint (used by the widget on any page) ---
@app.route("/chat", methods=["POST"])
def chat():
    bill_context = session.get("bill_context")
    user_message = (request.get_json() or {}).get("message", "").strip()
    if not user_message:
        return jsonify({"reply": f"Ask me something! - {BOT_NAME}"}), 400

    rag_context, _ = retrieve_context(user_message, top_k=2)

    chat_history = session.get("chat_history", [])
    reply = chat_about_bill(bill_context or "", chat_history, user_message, rag_context=rag_context)

    chat_history.append({"role": "user", "text": user_message})
    chat_history.append({"role": "assistant", "text": reply})
    session["chat_history"] = chat_history

    return jsonify({"reply": reply})


<<<<<<< HEAD
# --- Wattson AI: dedicated full-page chat (bigger than the sidebar widget) ---
@app.route("/wattson")
def wattson_page():
    return render_template(
        "wattson.html",
        bot_name=BOT_NAME,
        has_bill_context=bool(session.get("bill_context")),
        active_page="wattson",
    )


=======
>>>>>>> 678ede362b6dfb8746e9ab27f1e398fe3bc83a7e
# --- Phase 11: history dashboard ---
@app.route("/history")
def history_page():
    records = history.get_history()
    trend = history.get_trend_data()
    return render_template("history.html", records=records, trend=trend, bot_name=BOT_NAME,
                            recent_history=_recent_history(), active_page="history")


@app.route("/history/clear", methods=["POST"])
def history_clear():
    deleted = history.delete_history()
    flash(f"Cleared {deleted} saved bill(s) from history.")
    return redirect(url_for("history_page"))


# --- Compare Bills: select any number of saved bills and see them side by side ---
@app.route("/compare")
def compare_page():
    all_bills = history.get_all_bills_for_compare()
    return render_template(
        "compare.html",
        bot_name=BOT_NAME,
        all_bills=all_bills,
        recent_history=_recent_history(),
        active_page="compare",
    )


<<<<<<< HEAD
# --- Settings: app configuration status + appliance reference data ---
@app.route("/settings")
def settings_page():
    return render_template(
        "settings.html",
        bot_name=BOT_NAME,
        recent_history=_recent_history(),
        active_page="settings",
        llm_configured=bool(GEMINI_API_KEY),
        llm_model=LLM_MODEL,
        email_configured=email_service.is_configured(),
        appliances=APPLIANCES,
        star_ratings=STAR_RATING_MULTIPLIERS,
        total_bills=history.get_stats()["total_bills"],
    )


=======
>>>>>>> 678ede362b6dfb8746e9ab27f1e398fe3bc83a7e
# --- PDF export ---
@app.route("/export/<int:bill_id>")
def export_pdf(bill_id):
    cached = session.get(f"bill_{bill_id}")
    if cached:
        path = pdf_export.generate_bill_pdf(
            cached["bill_data"], cached["metrics"], cached["score"],
            cached["ai_analysis"], cached["breakdown"],
            filename=f"wattwise_report_{bill_id}.pdf",
        )
        return send_file(path, as_attachment=True, download_name=f"WattWise_Report_{bill_id}.pdf")

    record = history.get_bill_by_id(bill_id)
    if not record:
        flash("Couldn't find that report -- try analyzing the bill again.")
        return redirect(url_for("history_page"))

    bill_data = {"consumer_number": record["consumer_number"], "billing_month": record["billing_month"],
                 "units_consumed": record["units_consumed"], "bill_amount": record["bill_amount"]}
    metrics = {"percentage_change": record["percentage_change"],
               "trend": "increased" if (record["percentage_change"] or 0) > 0 else "decreased",
               "cost_per_unit": record["cost_per_unit"]}
    score = {"score": record["energy_score"], "rating": record["energy_rating"]}
    path = pdf_export.generate_bill_pdf(bill_data, metrics, score, record["ai_summary"], None,
                                         filename=f"wattwise_report_{bill_id}.pdf")
    return send_file(path, as_attachment=True, download_name=f"WattWise_Report_{bill_id}.pdf")


# --- Email the report ---
@app.route("/email_report", methods=["POST"])
def email_report():
    data = request.get_json() or {}
    to_email = data.get("email", "").strip()
    bill_id = session.get("last_bill_id")

    if not to_email:
        return jsonify({"success": False, "message": "Enter an email address."}), 400
    if not bill_id:
        return jsonify({"success": False, "message": "Analyze a bill first."}), 400

    cached = session.get(f"bill_{bill_id}")
    if not cached:
        return jsonify({"success": False, "message": "That report has expired -- try re-analyzing."}), 400

    path = pdf_export.generate_bill_pdf(
        cached["bill_data"], cached["metrics"], cached["score"],
        cached["ai_analysis"], cached["breakdown"],
        filename=f"wattwise_report_{bill_id}.pdf",
    )
    result = email_service.send_report_email(to_email, path)
    return jsonify(result), (200 if result["success"] else 400)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
