"""Testy warstwy danych — siatka zabezpieczająca przed migracją na Postgresa.

Do tej pory `src/db.py` nie miał żadnego pokrycia. To problem, bo błędy, które
pojawiają się przy przejściu na Postgresa, w większości **nie rzucają wyjątku,
tylko po cichu robią coś innego**: zapis, który nie zostaje zacommitowany,
`lastrowid`, który zwraca `None`, albo filtr własności, który przepuszcza wszystko.

Testy operują wyłącznie na publicznym API, więc mają przejść bez zmian zarówno na
SQLite, jak i po migracji na Postgresa. Rozjazd między nimi = regresja.
"""

import pytest


def _insert(db, **overrides):
    params = dict(
        audio_path=None,
        pipeline="multimodal",
        raw_transcript="transkrypcja",
        ai_note_original_json='{"podsumowanie": "AI"}',
        doctor_id="user-a",
        visit_label="pacjent A",
        visit_type="Pierwsza",
        usage={
            "prompt_tokens": 1000,
            "output_tokens": 200,
            "total_tokens": 1200,
            "estimated_cost_usd": 0.0015,
            "prompt_audio_tokens": 900,
            "modality_known": True,
        },
        audio_duration_seconds=1800.0,
    )
    params.update(overrides)
    return db.insert_visit(**params)


class TestRoundTrip:
    def test_insert_returns_usable_id(self, temp_db):
        """Po migracji `cur.lastrowid` przestaje działać — id musi nadal wracać."""
        visit_id = _insert(temp_db)
        assert isinstance(visit_id, int)
        assert visit_id > 0

    def test_insert_then_read_back(self, temp_db):
        visit_id = _insert(temp_db, visit_label="etykieta")
        visit = temp_db.get_visit(visit_id)
        assert visit is not None
        assert visit["visit_label"] == "etykieta"
        assert visit["status"] == "draft"
        assert visit["doctor_id"] == "user-a"

    def test_write_is_committed_not_just_visible_in_session(self, temp_db):
        """Łapie cichą utratę zapisu.

        `engine.connect()` w SQLAlchemy 2 NIE commituje przy wyjściu z `with`, choć
        `sqlite3` commituje. Naiwny port sprawiłby, że zapis wygląda na udany w obrębie
        wywołania, a znika po jego zakończeniu. Odczyt idzie tu przez osobne wywołanie,
        czyli osobne połączenie.
        """
        visit_id = _insert(temp_db)
        assert any(v["id"] == visit_id for v in temp_db.list_visits())

    def test_usage_metrics_are_persisted(self, temp_db):
        visit_id = _insert(temp_db)
        visit = temp_db.get_visit(visit_id)
        assert visit["prompt_tokens"] == 1000
        assert visit["prompt_audio_tokens"] == 900
        assert visit["audio_duration_seconds"] == pytest.approx(1800.0)
        assert visit["estimated_cost_usd"] == pytest.approx(0.0015)

    def test_audio_tokens_dropped_when_modality_unknown(self, temp_db):
        """Bez rozbicia modalności liczba zawiera też prompt tekstowy — nie zapisujemy jej."""
        visit_id = _insert(
            temp_db,
            usage={"prompt_audio_tokens": 50_000, "modality_known": False},
        )
        assert temp_db.get_visit(visit_id)["prompt_audio_tokens"] == 0

    def test_update_marks_approved(self, temp_db, sample_note_json):
        visit_id = _insert(temp_db)
        temp_db.update_visit(visit_id, doctor_note_corrected_json=sample_note_json)
        visit = temp_db.get_visit(visit_id)
        assert visit["status"] == "approved"
        assert visit["doctor_note_corrected_json"] == sample_note_json


class TestOwnershipFiltering:
    """Filtr własności — serce izolacji danych między użytkownikami."""

    @pytest.fixture
    def two_users(self, temp_db, sample_note_json):
        a = _insert(temp_db, doctor_id="user-a", visit_label="pacjent A")
        b = _insert(temp_db, doctor_id="user-b", visit_label="pacjent B")
        temp_db.update_visit(a, doctor_note_corrected_json=sample_note_json)
        temp_db.update_visit(b, doctor_note_corrected_json=sample_note_json)
        return a, b

    def test_list_visits_scoped_to_owner(self, temp_db, two_users):
        a, _ = two_users
        visits = temp_db.list_visits(doctor_id="user-a")
        assert [v["id"] for v in visits] == [a]

    def test_get_visit_refuses_other_owner(self, temp_db, two_users):
        _, b = two_users
        assert temp_db.get_visit(b, doctor_id="user-a") is None

    def test_get_visit_allows_own(self, temp_db, two_users):
        a, _ = two_users
        assert temp_db.get_visit(a, doctor_id="user-a") is not None

    def test_few_shot_examples_scoped_to_owner(self, temp_db, two_users):
        """Najgroźniejszy wyciek: cudza transkrypcja w promptzie do Gemini."""
        examples = temp_db.get_approved_examples(doctor_id="user-a")
        assert len(examples) == 1

    def test_few_shot_empty_for_user_without_approved_notes(self, temp_db, two_users):
        assert temp_db.get_approved_examples(doctor_id="user-c") == []

    def test_update_cannot_touch_other_owner(self, temp_db, two_users):
        """Aktualizacja cudzej wizyty nie może jej zmienić.

        UWAGA: dziś przechodzi po cichu — `update_visit` nie sprawdza `rowcount`,
        więc wołający dostaje sukces mimo zera zmienionych wierszy. Test pilnuje
        przynajmniej tego, że **dane cudzej wizyty pozostają nietknięte**.
        """
        _, b = two_users
        temp_db.update_visit(
            b, doctor_note_corrected_json='{"podsumowanie": "podmiana"}', doctor_id="user-a"
        )
        untouched = temp_db.get_visit(b)
        assert "podmiana" not in (untouched["doctor_note_corrected_json"] or "")


class TestFailOpenDefault:
    """Dokumentuje obecne zachowanie: brak `doctor_id` = brak filtrowania.

    To jest **zamierzone tylko przejściowo**. Faza B zmienia domyślne zachowanie na
    zawodzenie zamknięciem, bo dziś zapomniany argument to cichy wyciek danych.
    Gdy to nastąpi, poniższe testy trzeba świadomie odwrócić — i o to chodzi.
    """

    def test_list_visits_without_owner_returns_everything(self, temp_db):
        _insert(temp_db, doctor_id="user-a")
        _insert(temp_db, doctor_id="user-b")
        assert len(temp_db.list_visits()) == 2

    def test_get_visit_without_owner_returns_any_row(self, temp_db):
        visit_id = _insert(temp_db, doctor_id="user-b")
        assert temp_db.get_visit(visit_id) is not None


class TestAdminAggregates:
    """Agregaty właściciela — celowo BEZ filtrowania, ale i bez treści wizyt."""

    @pytest.fixture
    def populated(self, temp_db, sample_note_json):
        a = _insert(temp_db, doctor_id="user-a")
        _insert(temp_db, doctor_id="user-a")
        _insert(temp_db, doctor_id="user-b")
        temp_db.update_visit(a, doctor_note_corrected_json=sample_note_json)
        return temp_db

    def test_user_stats_group_by_owner(self, populated):
        stats = {row["doctor"]: row for row in populated.admin_user_stats()}
        assert stats["user-a"]["visits"] == 2
        assert stats["user-b"]["visits"] == 1

    def test_user_stats_count_approved(self, populated):
        stats = {row["doctor"]: row for row in populated.admin_user_stats()}
        assert stats["user-a"]["approved"] == 1
        assert stats["user-b"]["approved"] == 0

    def test_daily_stats_group_by_day(self, populated):
        """Grupowanie po dniu — miejsce, które łamie się przy przejściu na Postgresa.

        SQLite parsuje `date()` z tekstu; w Postgresie `date` to typ, nie funkcja.
        Test pilnuje, że po migracji nadal dostajemy jedną grupę na dzień.
        """
        daily = populated.admin_daily_stats()
        assert len(daily) == 1
        assert daily[0]["visits"] == 3

    def test_visit_durations_cover_all_users(self, populated):
        rows = populated.admin_visit_durations()
        assert {r["doctor"] for r in rows} == {"user-a", "user-b"}

    @pytest.mark.parametrize(
        "forbidden",
        ["raw_transcript", "ai_note_original_json", "doctor_note_corrected_json", "visit_label"],
    )
    def test_aggregates_never_expose_visit_content(self, populated, forbidden):
        """Granica danych: właściciel widzi metadane, nigdy treści wizyty."""
        for row in populated.admin_user_stats():
            assert forbidden not in row
        for row in populated.admin_daily_stats():
            assert forbidden not in row
        for row in populated.admin_visit_durations():
            assert forbidden not in row


class TestMigration:
    def test_init_db_is_idempotent(self, temp_db):
        """Uruchamiane przy każdym starcie aplikacji — nie może niczego zepsuć."""
        visit_id = _insert(temp_db)
        temp_db.init_db()
        temp_db.init_db()
        assert temp_db.get_visit(visit_id) is not None

    def test_legacy_database_gains_new_columns(self, tmp_path, monkeypatch):
        """Baza sprzed `doctor_id` i kolumn czasu ma się zmigrować bez utraty wierszy."""
        import sqlite3

        from src import db as db_module

        path = tmp_path / "legacy.db"
        con = sqlite3.connect(path)
        con.executescript(
            """
            CREATE TABLE visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                audio_path TEXT,
                pipeline TEXT NOT NULL DEFAULT 'multimodal',
                raw_transcript TEXT,
                ai_note_original_json TEXT NOT NULL,
                doctor_note_corrected_json TEXT,
                status TEXT NOT NULL DEFAULT 'draft'
            );
            INSERT INTO visits (created_at, ai_note_original_json, status)
            VALUES ('2026-05-01T10:00:00', '{"podsumowanie":"stara"}', 'draft');
            """
        )
        con.commit()
        con.close()

        monkeypatch.setattr(db_module, "DB_PATH", path)
        db_module.init_db()

        visit = db_module.get_visit(1)
        assert visit is not None, "migracja zgubiła istniejący wiersz"
        for column in ("doctor_id", "prompt_audio_tokens", "audio_duration_seconds"):
            assert column in visit
