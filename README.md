# MindScribe

MVP aplikacji webowej dla psychiatrów: nagranie wizyty → transkrypcja + ustrukturyzowana notatka medyczna (Gemini 2.5 Flash, Structured Outputs) → edycja i zatwierdzenie przez lekarza (Human-in-the-Loop) → zapis w SQLite.

Zatwierdzone notatki są automatycznie doklejane do kolejnych promptów jako **few-shot examples** (3 ostatnie), dzięki czemu model uczy się stylu danego lekarza w locie.

## Stack

- **UI + backend**: Python 3.11+, Streamlit (multi-page)
- **AI**: Gemini 2.5 Flash przez `google-genai` SDK, Structured Outputs (Pydantic → `response_schema`)
- **Audio**: ścieżka A — plik audio uploadowany do Gemini Files API i analizowany multimodalnie (transkrypcja + notatka w jednym wywołaniu)
- **DB**: SQLite (`data/mindscribe.db`)

## Uruchomienie lokalne

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# uzupełnij GEMINI_API_KEY w .env

streamlit run app.py
```

Aplikacja otworzy się w przeglądarce. W panelu po lewej dwie strony:

1. **Nowa wizyta** — wgraj/nagraj audio, kliknij **Wygeneruj notatkę**, popraw pola, **Zatwierdź**.
2. **Historia wizyt** — przegląd zapisanych wizyt, diff oryginału AI vs wersji lekarza.

## Struktura

```
MindScribe/
├── app.py                    # Streamlit entry
├── pages/
│   ├── 1_Nowa_wizyta.py      # upload audio → generacja → HITL → zapis
│   └── 2_Historia_wizyt.py   # lista + diff
├── src/
│   ├── config.py             # .env + stałe
│   ├── schemas.py            # PsychiatricNote (Pydantic, response_schema dla Gemini)
│   ├── prompts.py            # system prompt + builder few-shot
│   ├── db.py                 # SQLite: visits, get_approved_examples(3)
│   ├── audio.py              # zapis uploadu na dysk
│   └── gemini_client.py      # generate_note_from_audio() — Files API + Structured Output
└── data/                     # DB i nagrania (gitignored)
```

## Bezpieczeństwo — MUSISZ przeczytać przed użyciem na realnych pacjentach

To MVP. Do testów **wewnętrznych** w gabinecie, na danych fikcyjnych/zanonimizowanych.

Zanim wpuścisz tu dane pacjentów:

1. **Przełącz klienta na Vertex AI**. W `src/gemini_client.py` zamień:
   ```python
   genai.Client(api_key=GEMINI_API_KEY)
   ```
   na:
   ```python
   genai.Client(vertexai=True, project="twój-gcp-project", location="europe-west4")
   ```
   Vertex AI w Google Cloud nie wykorzystuje danych klienta do trenowania modeli publicznych i podpada pod BAA Google Cloud — w przeciwieństwie do darmowego tieru Gemini API.
2. **Zaimplementuj moduł anonimizacji** (planowany `src/anonymize.py`): usuwanie imion, nazwisk, PESEL, adresów z transkrypcji przed przekazaniem do widoku/eksportu.
3. **Wystaw produkcyjnie za autoryzacją**. Streamlit MVP nie ma uwierzytelniania — uruchamiaj tylko lokalnie lub za reverse-proxy z auth.
4. **Nie commituj `.env`** ani plików z `data/`.

## Roadmapa (poza MVP)

- Ścieżka B: Whisper → tekst → Gemini (alternatywny pipeline, `generate_note_from_text` już jest jako stub).
- Migracja DB do PostgreSQL.
- Multi-tenant (kolumna `doctor_id` już zarezerwowana).
- Moduł anonimizacji.
- Autentykacja, RBAC, audyt logów.
