"""Wspólne fixture'y testowe.

Najważniejszy jest `temp_db`. Domyślnie podstawia bazę na plik SQLite w katalogu
tymczasowym, więc testy nie dotykają niczyjej roboczej bazy.

Ale można też uruchomić **tę samą serię na PostgreSQL** i sprawdzić, czy migracja
niczego nie zmieniła:

    TEST_DATABASE_URL='postgresql://user:haslo@host/baza?sslmode=require' pytest

⚠️ Testy **czyszczą tabelę `visits`** w podanej bazie. Podawaj wyłącznie bazę
testową — nigdy tej, w której są prawdziwe wizyty. Dlatego jest to osobna zmienna
niż `DATABASE_URL`: żeby nie dało się wyczyścić produkcji przez przypadek.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db as db_module  # noqa: E402

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()


def _normalized(url: str) -> str:
    """Adres z panelu Neona ma prefiks `postgresql://`, SQLAlchemy chce sterownika."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Świeża, pusta baza na czas jednego testu."""
    url = _normalized(TEST_DATABASE_URL) if TEST_DATABASE_URL else f"sqlite:///{tmp_path/'test.db'}"
    monkeypatch.setattr(db_module, "DATABASE_URL", url)
    db_module.reset_engine_cache()

    if TEST_DATABASE_URL:
        # Na współdzielonej bazie każdy test musi zaczynać od czystego stanu.
        db_module.metadata.drop_all(db_module.get_engine())

    db_module.init_db()
    yield db_module
    db_module.reset_engine_cache()


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Baza wymuszona na SQLite — dla testów sprawdzających migrację starego pliku."""
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setattr(db_module, "DATABASE_URL", url)
    db_module.reset_engine_cache()
    yield tmp_path / "legacy.db", db_module
    db_module.reset_engine_cache()


@pytest.fixture
def sample_note_json():
    return '{"podsumowanie": "notatka testowa", "ryzyko_samobojcze": "NIEOBECNE"}'
