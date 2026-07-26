# WattWise — LLM & RAG-Powered Smart Energy Advisor

## What's here
- `extraction.py`   — PDF (PyMuPDF) + image OCR (Tesseract) text extraction, then regex parsing into structured fields. Deterministic, fast, free — always tried first.
- `llm.py`           — Gemini calls: (1) **vision-based document reading** when regex misses fields — sends the actual image/PDF bytes so the model reads the bill the way a person would, not just OCR text; (2) RAG-grounded bill analysis; (3) **Wattson**, the follow-up chatbot.
- `calculation.py`   — deterministic metrics, WattWise Energy Score, appliance breakdown, savings simulator. Plain Python arithmetic only — the LLM never calculates.
- `rag/retriever.py` — TF-IDF + cosine similarity retrieval over `rag/knowledge_base/*.txt`. Small, curated, explainable — no external embedding API needed.
- `rag/knowledge_base/` — curated energy-saving facts (AC, refrigerator, LED bulbs, water heater, tariffs, general tips, appliance wattage reference).
- `app.py`           — Flask app: upload → extract → (vision fallback) → calculate → RAG retrieve → LLM analyze → dashboard + Wattson sidebar chat → savings simulator.
- `templates/`       — `index.html` (upload form), `results.html` (dashboard with left sidebar chat).
- `static/style.css` — dark/neon dashboard styling, sidebar chat layout.

## Why vision-based reading, not just OCR text
Tesseract OCR often garbles real bill photos — misread digits, dropped labels,
jumbled table layout. Previously, if regex parsing failed, the app fell back to
feeding the *same broken OCR text* to the LLM, which doesn't fix the underlying
problem. Now, when regex can't find a field, `llm.analyze_bill_document_with_vision()`
sends the **original image or PDF file** to Gemini (which is multimodal), so it
visually reads the page directly — the same way a person looking at the bill would.
This fills gaps like consumer number, billing month, or amount that OCR missed,
without ever letting the LLM invent a number it can't actually see (it returns
`null` for anything not visible, per the system instruction).

If even the vision pass can't derive `units_consumed` and a previous-month
figure (the two numbers the calculation engine needs), the app falls back one
more level to `analyze_bill_document_freeform()`, which still looks at the
actual document and gives the best plain-language analysis it can, rather
than showing a wall of "—".

## The RAG layer
`rag/knowledge_base/` holds small, hand-written `.txt` files split into
paragraph-sized chunks. `rag/retriever.py` builds a TF-IDF matrix over these
chunks at startup and retrieves the top-k most relevant chunks for a query
built from the bill's trend + dominant appliance (for the main analysis) or
the user's actual question (for Wattson's chat replies). Retrieved chunks are
injected into the LLM prompt as "Retrieved energy-saving knowledge" and the
system instruction tells the model to ground its advice in them — this is
what makes the recommendations trustworthy rather than generic LLM guesses.
The results page shows which source files were used ("Grounded in retrieved
knowledge from: ac_tips.txt, tariff_info.txt").

## Wattson, the chatbot
Lives in the left sidebar on the results page (not a small chat box at the
bottom), stays visible while you scroll the dashboard, and remembers the
current bill's context for the whole session via Flask `session`. Each
question also triggers a fresh RAG retrieval so answers like "why did my
bill increase" stay grounded in the same trusted knowledge base as the main
analysis.

## Run it
    pip install -r requirements.txt
    # Tesseract must also be installed system-side for image OCR:
    #   Ubuntu/Debian: sudo apt install tesseract-ocr
    export GEMINI_API_KEY="your-key-here"   # get one free at https://aistudio.google.com/apikey
    python app.py
Then open http://localhost:5000

## Tested
Ran the full pipeline (extraction → vision fallback → calculation → RAG →
LLM analysis → Flask routes) against a synthetic sample bill (420 units, 290
previous, ₹3650) and confirmed the numbers match the worked example: 44.83%
increase, ₹8.69/unit, score 45/100 (High Consumption), 234 kWh AC estimate,
₹508 savings from 8hrs → 6hrs AC usage.

## Architecture summary (for viva)
Python calculates (deterministic, testable, exact) →
RAG retrieves trusted knowledge (small curated corpus, TF-IDF, explainable) →
LLM reasons, personalizes, reads documents visually, explains, and converses
(never recalculates, never invents numbers it can't see or wasn't given).

## Next steps / possible extensions
1. Swap TF-IDF for a proper embedding model + FAISS if you want to demonstrate vector embeddings specifically for the viva.
2. Add a `tests/` folder with pytest coverage for `calculation.py`'s formulas.
3. History dashboard: persist each analyzed bill (e.g. to SQLite) to show month-over-month trends across more than two bills.
4. Confidence/assumptions panel showing which fields came from regex vs. vision vs. manual entry.
