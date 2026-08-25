"""Wspólne fixture'y testowe.

Najważniejszy jest `temp_db`: podstawia bazę na plik tymczasowy, dzięki czemu testy
warstwy danych nie dotykają niczyjej roboczej bazy. Fixture celowo operuje na
publicznym API `src.db`, a nie na SQL-u — dzięki temu **ta sama seria testów przejdzie
na SQLite i na Postgresie** i będzie dowodem, że migracja niczego nie zmieniła.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db as db_module  # noqa: E402


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Świeża, pusta baza na czas jednego testu."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db()
    return db_module


@pytest.fixture
def sample_note_json():
    return '{"podsumowanie": "notatka testowa", "ryzyko_samobojcze": "NIEOBECNE"}'
