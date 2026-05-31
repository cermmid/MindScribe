import sqlite3
from datetime import datetime
from typing import Any

from .config import DB_PATH, FEW_SHOT_LIMIT

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    audio_path TEXT,
    pipeline TEXT NOT NULL DEFAULT 'multimodal',
    raw_transcript TEXT,
    ai_note_original_json TEXT NOT NULL,
    doctor_note_corrected_json TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    doctor_id TEXT,
    visit_label TEXT,
    visit_type TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0
);
"""

# Kolumny dodawane idempotentnie przy starcie (ALTER TABLE), by istniejące lokalne DB się zmigrowały.
ADDED_COLUMNS = {
    "prompt_tokens": "INTEGER DEFAULT 0",
    "output_tokens": "INTEGER DEFAULT 0",
    "total_tokens": "INTEGER DEFAULT 0",
    "estimated_cost_usd": "REAL DEFAULT 0.0",
    "visit_label": "TEXT",
    "visit_type": "TEXT",
}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
        existing = {row["name"] for row in c.execute("PRAGMA table_info(visits)")}
        for col, decl in ADDED_COLUMNS.items():
            if col not in existing:
                c.execute(f"ALTER TABLE visits ADD COLUMN {col} {decl}")


def insert_visit(
    *,
    audio_path: str | None,
    pipeline: str,
    raw_transcript: str,
    ai_note_original_json: str,
    doctor_id: str | None = None,
    visit_label: str | None = None,
    visit_type: str | None = None,
    usage: dict | None = None,
) -> int:
    usage = usage or {}
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO visits
               (created_at, audio_path, pipeline, raw_transcript, ai_note_original_json,
                status, doctor_id, visit_label, visit_type,
                prompt_tokens, output_tokens, total_tokens, estimated_cost_usd)
               VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(timespec="seconds"),
                audio_path,
                pipeline,
                raw_transcript,
                ai_note_original_json,
                doctor_id,
                visit_label,
                visit_type,
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("output_tokens", 0)),
                int(usage.get("total_tokens", 0)),
                float(usage.get("estimated_cost_usd", 0.0)),
            ),
        )
        return cur.lastrowid


def usage_totals() -> dict[str, float]:
    with _conn() as c:
        row = c.execute(
            """SELECT COUNT(*) AS n,
                      COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                      COALESCE(SUM(output_tokens), 0) AS output_tokens,
                      COALESCE(SUM(total_tokens),  0) AS total_tokens,
                      COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd
               FROM visits"""
        ).fetchone()
        return dict(row)


def update_visit(
    visit_id: int,
    *,
    doctor_note_corrected_json: str,
    status: str = "approved",
) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE visits SET doctor_note_corrected_json = ?, status = ? WHERE id = ?",
            (doctor_note_corrected_json, status, visit_id),
        )


def get_visit(visit_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        return dict(row) if row else None


def list_visits() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            """SELECT id, created_at, visit_label, visit_type, status, pipeline, doctor_id,
                      prompt_tokens, output_tokens, total_tokens, estimated_cost_usd
               FROM visits ORDER BY id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_approved_examples(limit: int = FEW_SHOT_LIMIT) -> list[dict[str, str]]:
    with _conn() as c:
        rows = c.execute(
            """SELECT raw_transcript, doctor_note_corrected_json
               FROM visits
               WHERE status = 'approved' AND doctor_note_corrected_json IS NOT NULL
               ORDER BY id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {"raw_transcript": r["raw_transcript"] or "", "note_json": r["doctor_note_corrected_json"]}
            for r in rows
        ]
