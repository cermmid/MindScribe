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
    doctor_id TEXT
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


def insert_visit(
    *,
    audio_path: str | None,
    pipeline: str,
    raw_transcript: str,
    ai_note_original_json: str,
    doctor_id: str | None = None,
) -> int:
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO visits
               (created_at, audio_path, pipeline, raw_transcript, ai_note_original_json, status, doctor_id)
               VALUES (?, ?, ?, ?, ?, 'draft', ?)""",
            (
                datetime.utcnow().isoformat(timespec="seconds"),
                audio_path,
                pipeline,
                raw_transcript,
                ai_note_original_json,
                doctor_id,
            ),
        )
        return cur.lastrowid


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
            "SELECT id, created_at, status, pipeline, doctor_id FROM visits ORDER BY id DESC"
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
