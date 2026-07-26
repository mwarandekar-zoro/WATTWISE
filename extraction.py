"""
Phase 1 & 2: Extract raw text from an uploaded electricity bill,
then parse that raw text into structured fields.

Design notes:
- PDF -> PyMuPDF (fitz) reads selectable text directly, no OCR needed.
- Image -> Tesseract OCR reads text from a picture of a bill.
- No LLM is used here. Extraction and parsing are deterministic.
- This stays fast/free/offline-capable as the FIRST pass. When it can't
  find everything, app.py now falls back to llm.analyze_bill_document_with_vision()
  which sends the ORIGINAL file (not this OCR text) to a multimodal LLM so
  it can visually read fields this regex-based pass missed.
"""

import re
import fitz  # PyMuPDF
import pytesseract
from PIL import Image

# Windows only: pytesseract needs to be told exactly where the Tesseract
# engine .exe lives, since installing it doesn't add it to PATH automatically.
# If you installed it somewhere else, update this path to match.
import platform
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def extract_pdf_text(file_path: str) -> str:
    """Pull all selectable text out of a PDF bill."""
    text = ""
    with fitz.open(file_path) as document:
        for page in document:
            text += page.get_text()
    return text


def extract_pdf_image_text(file_path: str) -> str:
    """OCR PDF pages by rendering them as images."""
    text = ""
    with fitz.open(file_path) as document:
        for page in document:
            pix = page.get_pixmap(dpi=200)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            gray = image.convert("L")
            text += pytesseract.image_to_string(gray, config='--psm 6') + "\n"
    return text


def extract_image_text(file_path: str) -> str:
    """OCR a photographed/scanned bill (jpg, png, etc)."""
    image = Image.open(file_path)
    gray = image.convert("L")
    text = pytesseract.image_to_string(gray, config='--psm 6')
    return text


def extract_text(file_path: str) -> str:
    """Route to the right extractor based on file extension."""
    lower = file_path.lower()
    if lower.endswith(".pdf"):
        text = extract_pdf_text(file_path)
        if not text.strip():
            text = extract_pdf_image_text(file_path)
        return text
    elif lower.endswith((".jpg", ".jpeg", ".png", ".bmp", ".tiff")):
        return extract_image_text(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_path}")


# ---------------------------------------------------------------------------
# Phase 2: Regex parser. Runs first because it's fast, free and deterministic.
# If it can't find every field, app.py falls back to a vision-based LLM read
# of the original document (see llm.analyze_bill_document_with_vision).
# ---------------------------------------------------------------------------

FIELD_PATTERNS = {
    "consumer_number": [
        r"consumer\s*(?:no|number|id)[.:\s]*([A-Za-z0-9-]+)",
        r"consumer\s*id[.:\s]*([A-Za-z0-9-]+)",
    ],
    "current_reading": [
        r"(?:current|present)\s*reading[.:\s]*([\d,]+)",
        r"reading\s*\(?current\)?[.:\s]*([\d,]+)",
    ],
    "previous_reading": [
        r"(?:previous|last)\s*reading[.:\s]*([\d,]+)",
        r"reading\s*\(?previous\)?[.:\s]*([\d,]+)",
    ],
    "units_consumed": [
        r"units?\s*(?:consumed|used|this\s*month)?[.:\s]*([\d,]+)",
        r"consumption[.:\s]*([\d,]+)",
    ],
    "bill_amount": [
        r"(?:total\s*amt|bill\s*amount|total\s*amount|amount\s*due|net\s*amount|payable)[.:\s]*(?:Rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?:total|payable)\s*[:]?\s*(?:Rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)",
    ],
    "billing_month": [
        r"billing\s*month[.:\s]*([A-Za-z]+\s*\d{4})",
        r"bill\s*month[.:\s]*([A-Za-z]+\s*\d{4})",
        r"billing\s*period[.:\s]*([A-Za-z]+\s*\d{4})",
    ],
    "tariff": [
        r"tariff[.:\s]*([A-Za-z]+)",
        r"category[.:\s]*([A-Za-z]+)",
    ],
}


def _clean_number(value: str, is_float: bool = False):
    value = value.replace(",", "").strip()
    if not value:
        return None
    try:
        return float(value) if is_float else int(value)
    except ValueError:
        return None


def _find_first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _search_line_for_number(lines: list[str], keywords: list[str], allow_decimal: bool = False) -> str | None:
    pattern = r"([\d,]+(?:\.\d+)?)" if allow_decimal else r"([\d,]+)"
    for line in lines:
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            match = re.search(pattern, line)
            if match:
                return match.group(1).strip()
    return None


def parse_bill_text(raw_text: str) -> dict:
    """
    Turn messy OCR/PDF text into a structured dict.
    Numbers are cleaned (commas stripped) and cast to int/float.
    Missing fields come back as None so the caller knows what's left
    to fill in (regex fallbacks first, then a vision-based LLM pass).
    """
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    cleaned = " ".join(lines)
    result = {}

    for field, patterns in FIELD_PATTERNS.items():
        value = _find_first_match(cleaned, patterns)
        if value is None:
            result[field] = None
            continue

        if field in ("current_reading", "previous_reading", "units_consumed"):
            result[field] = _clean_number(value)
        elif field == "bill_amount":
            result[field] = _clean_number(value, is_float=True)
        else:
            result[field] = value

    # Secondary fallbacks for noisy OCR / alternate labels
    if result.get("current_reading") is None:
        fallback = _search_line_for_number(lines, ["current reading", "present reading", "reading (current)", "reading current"])
        if fallback:
            result["current_reading"] = _clean_number(fallback)

    if result.get("previous_reading") is None:
        fallback = _search_line_for_number(lines, ["previous reading", "last reading", "reading (previous)", "reading previous"])
        if fallback:
            result["previous_reading"] = _clean_number(fallback)

    if result.get("bill_amount") is None:
        fallback = _search_line_for_number(lines, ["total amt", "bill amount", "total amount", "amount due", "net amount", "payable", "total"], allow_decimal=True)
        if fallback:
            result["bill_amount"] = _clean_number(fallback, is_float=True)

    if result.get("units_consumed") is None:
        fallback = _search_line_for_number(lines, ["units consumed", "units used", "consumption", "kwh"], allow_decimal=False)
        if fallback:
            result["units_consumed"] = _clean_number(fallback)

    # If units_consumed wasn't found directly but both readings were,
    # derive it deterministically instead of leaving it blank.
    if result.get("units_consumed") is None:
        cur, prev = result.get("current_reading"), result.get("previous_reading")
        if cur is not None and prev is not None:
            result["units_consumed"] = cur - prev

    result["missing_fields"] = [k for k, v in result.items()
                                 if v is None and k != "missing_fields"]
    return result


if __name__ == "__main__":
    sample = """
    Maharashtra State Electricity Distribution
    Consumer No 123456789012
    Billing Month June 2026
    Current Reading 5420
    Previous Reading 5000
    Units Consumed 420
    Total Amt Rs 3650
    Tariff Residential
    """
    print(parse_bill_text(sample))
