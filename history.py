"""
Phase 11: History dashboard + permanent bill storage.

Every analyzed bill gets saved to a local SQLite file (history.db) so the
dashboard can show a real month-over-month trend, and so multiple bills can
be compared against each other (not just current vs. previous). This is
plain Python + sqlite3 (standard library) -- no ORM, no LLM involvement,
kept deterministic like calculation.py.

Storage rules:
  - Every upload gets its own row. Nothing is ever overwritten or updated
    in place -- re-analyzing a bill (even the same file) creates a new
    history entry, so the full upload history is preserved permanently.
  - `bill_json` stores the complete structured snapshot (bill_data, metrics,
    score, breakdown) as JSON, so a row is self-contained even for fields
    that don't have their own column.
"""

import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "history.db")


def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the bills table if it doesn't exist yet, and add any new
    columns to older databases. Safe to call every app startup (see app.py)."""
    conn = _get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_date TEXT NOT NULL,
            consumer_number TEXT,
            consumer_name TEXT,
            billing_month TEXT,
            bill_amount REAL,
            units_consumed INTEGER,
            current_reading REAL,
            previous_reading REAL,
            tariff TEXT,
            utility_company TEXT,
            bill_date TEXT,
            percentage_change REAL,
            cost_per_unit REAL,
            energy_score INTEGER,
            energy_rating TEXT,
            ai_summary TEXT,
            bill_json TEXT,
            image_path TEXT,
            pdf_path TEXT
        )
    """)

    # Lightweight migration: if an older history.db (pre-expansion) is
    # present, make sure any columns it's missing get added rather than
    # failing on INSERT. Existing rows just get NULL for new columns.
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(bills)")}
    expected_cols = {
        "upload_date": "TEXT", "consumer_number": "TEXT", "consumer_name": "TEXT",
        "billing_month": "TEXT", "bill_amount": "REAL", "units_consumed": "INTEGER",
        "current_reading": "REAL", "previous_reading": "REAL", "tariff": "TEXT",
        "utility_company": "TEXT", "bill_date": "TEXT", "percentage_change": "REAL",
        "cost_per_unit": "REAL", "energy_score": "INTEGER", "energy_rating": "TEXT",
        "ai_summary": "TEXT", "bill_json": "TEXT", "image_path": "TEXT", "pdf_path": "TEXT",
    }
    for col, col_type in expected_cols.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE bills ADD COLUMN {col} {col_type}")

    conn.commit()
    conn.close()


def save_bill_record(bill_data: dict, metrics: dict, score: dict, ai_analysis: str,
                      breakdown: dict | None = None, image_path: str | None = None,
                      pdf_path: str | None = None) -> int:
    """Insert one analyzed bill into history as a brand-new row. Never
    updates or overwrites an existing row -- every upload is kept.
    Returns the new row's id (used for PDF export / comparison links)."""
    conn = _get_connection()

    snapshot = {
        "bill_data": bill_data,
        "metrics": metrics,
        "score": score,
        "breakdown": breakdown,
    }

    cursor = conn.execute("""
        INSERT INTO bills (
            upload_date, consumer_number, consumer_name, billing_month,
            bill_amount, units_consumed, current_reading, previous_reading,
            tariff, utility_company, bill_date, percentage_change,
            cost_per_unit, energy_score, energy_rating, ai_summary,
            bill_json, image_path, pdf_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(timespec="seconds"),
        bill_data.get("consumer_number"),
        bill_data.get("consumer_name"),
        bill_data.get("billing_month"),
        bill_data.get("bill_amount"),
        bill_data.get("units_consumed"),
        bill_data.get("current_reading"),
        bill_data.get("previous_reading"),
        bill_data.get("tariff"),
        bill_data.get("utility_company"),
        bill_data.get("bill_date"),
        metrics.get("percentage_change") if isinstance(metrics.get("percentage_change"), (int, float)) else None,
        metrics.get("cost_per_unit") if isinstance(metrics.get("cost_per_unit"), (int, float)) else None,
        score.get("score") if isinstance(score.get("score"), (int, float)) else None,
        score.get("rating"),
        ai_analysis,
        json.dumps(snapshot, default=str),
        image_path,
        pdf_path,
    ))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def get_history(limit: int = 24) -> list[dict]:
    """Most recent bills first, for the history table / recent-bills widget."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM bills ORDER BY upload_date DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_bills_for_compare() -> list[dict]:
    """Every stored bill, most recent first, for the Compare Bills page --
    no artificial cap, so any number of bills can be selected."""
    conn = _get_connection()
    rows = conn.execute("SELECT * FROM bills ORDER BY upload_date DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_bills_by_ids(ids: list[int]) -> list[dict]:
    """Fetch a specific set of bills (any number) for side-by-side comparison,
    returned oldest-to-newest so charts/tables read left-to-right in time order."""
    if not ids:
        return []
    conn = _get_connection()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM bills WHERE id IN ({placeholders}) ORDER BY upload_date ASC", ids
    ).fetchall()
    conn.close()        
    return [dict(row) for row in rows]


def get_bill_by_id(bill_id: int) -> dict | None:
    conn = _get_connection()
    row = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_trend_data() -> dict:
    """Oldest-to-newest, for charting -- units and bill amount over time."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT upload_date, billing_month, units_consumed, bill_amount, energy_score "
        "FROM bills ORDER BY upload_date ASC"
    ).fetchall()
    conn.close()

    return {
        "labels": [r["billing_month"] or (r["upload_date"][:10] if r["upload_date"] else "Unknown") for r in rows],
        "units": [r["units_consumed"] for r in rows],
        "amounts": [r["bill_amount"] for r in rows],
        "scores": [r["energy_score"] for r in rows],
    }



def get_stats() -> dict:
    """Aggregate numbers for the Dashboard overview cards."""
    conn = _get_connection()
    row = conn.execute("""
        SELECT COUNT(*) AS total,
               AVG(energy_score) AS avg_score,
               AVG(bill_amount) AS avg_amount,
               AVG(units_consumed) AS avg_units
        FROM bills
    """).fetchone()
    conn.close()
    return {
        "total_bills": row["total"] or 0,
        "avg_score": round(row["avg_score"], 1) if row["avg_score"] is not None else None,
        "avg_amount": round(row["avg_amount"], 2) if row["avg_amount"] is not None else None,
        "avg_units": round(row["avg_units"], 1) if row["avg_units"] is not None else None,
    }



def delete_history() -> int:
    """Clear all saved history. Returns number of rows deleted."""
    conn = _get_connection()
    cursor = conn.execute("DELETE FROM bills")
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    return deleted


if __name__ == "__main__":
    init_db()
    new_id = save_bill_record(
        {"consumer_number": "TEST123", "billing_month": "June 2026",
         "units_consumed": 420, "bill_amount": 3650.0},
        {"percentage_change": 44.83, "cost_per_unit": 8.69},
        {"score": 45, "rating": "High Consumption"},
        "Sample analysis text.",
    )
    print("Inserted row id:", new_id)
    print("History:", get_history())
    print("Trend:", get_trend_data())
