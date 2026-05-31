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

## Deploy: link "kliknij i działa" dla lekarza (Streamlit Community Cloud)

Cel: wysyłasz lekarzowi *"hej, kliknij w ten link"* i wpisuje hasło — nic nie instaluje. Darmowe, jeśli repo jest publiczne.

### Setup jednorazowy (~5 min)

1. Upewnij się, że repo `cermmid/MindScribe` jest **public** na GitHubie i kod jest na branchu `main` (lub innym, który wskażesz w kroku 3).
2. Wejdź na **https://share.streamlit.io** → zaloguj się kontem GitHub → kliknij **Create app** → **Deploy a public app from GitHub**.
3. Wskaż:
   - Repository: `cermmid/MindScribe`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: np. `mindscribe-mvp` → dostaniesz `https://mindscribe-mvp.streamlit.app`
4. **Advanced settings → Secrets** — wklej (wartości weź ze swojego `.streamlit/secrets.toml`):
   ```toml
   GEMINI_API_KEY = "..."
   GEMINI_MODEL = "gemini-2.5-flash"
   app_password = "..."
   ```
5. **Deploy**. Po ~2 minutach apka żyje. Wysyłasz lekarzowi:
   > Link: https://mindscribe-mvp.streamlit.app
   > Hasło: \<to z `app_password`\>

Każdy push do tego brancha automatycznie redeployuje apkę.

### Ograniczenia darmowego hostingu — przeczytaj zanim wyślesz link

- **Dane znikają przy restarcie.** Streamlit Cloud ma efemeryczny filesystem — SQLite (`data/mindscribe.db`) i wgrane nagrania kasują się przy redeployu i po dłuższej bezczynności. Few-shot examples też. To OK na pokazanie UX lekarzowi w jednej sesji; do trwałości potrzebny zewnętrzny Postgres (Supabase/Neon — w roadmapie).
- **URL jest publiczny.** Bramka hasłowa (`src/auth.py`, snippet ze Streamlit docs) gate'uje wejście, ale każdy z linkiem zobaczy pole hasła — nadaj długie, losowe.
- **~1 GB RAM, 1 CPU**. Wystarczy dla jednego lekarza i plików do ~200 MB.
- **Brak BAA z Google**. ZERO realnych danych pacjentów na tym deploy'u. Fikcyjne nagrania tylko.

## Włączenie Vertex AI (10–15 min)

Vertex AI w Google Cloud nie wykorzystuje danych klienta do trenowania modeli publicznych — w przeciwieństwie do darmowego tieru Gemini API. To pierwszy krok w stronę użycia z realnymi pacjentami (ale nie jedyny — patrz checklista poniżej).

1. **Google Cloud Console** → projekt z włączonym billingiem (ten sam, z którego masz klucz API).
2. **APIs & Services → Library** → wyszukaj „Vertex AI API" → **Enable**.
3. **IAM & Admin → Service Accounts** → **Create Service Account**. Nazwa np. `mindscribe-vertex`.
4. Tej service account przypisz rolę **Vertex AI User** (`roles/aiplatform.user`).
5. Otwórz utworzone konto → zakładka **Keys** → **Add key → Create new key → JSON** → pobierze się plik.
6. W Streamlit Cloud → *Manage app → Settings → Secrets* dopisz (oprócz istniejących):
   ```toml
   USE_VERTEX_AI = true
   GCP_PROJECT_ID = "twoj-projekt-id"
   GCP_LOCATION = "europe-west4"    # region UE; fallback: "europe-west1"

   GOOGLE_APPLICATION_CREDENTIALS_JSON = """
   <<wklej tutaj CAŁY plik JSON service account, bez zmian>>
   """
   ```
   Potrójne cudzysłowy są obowiązkowe — JSON ma własne cudzysłowy i znaki nowej linii.
7. **Reboot** apki. W Cloud Console → **Vertex AI → Metrics** powinieneś zobaczyć request po pierwszej generacji notatki (a NIE w „Generative Language API").

Stawki na Vertex AI bywają minimalnie inne niż na Gemini API; szacunek z `src/pricing.py` zostaje przybliżony.

## Zanim wpuścisz REALNEGO pacjenta — checklista RODO/medyczna

**Samo przełączenie klienta na Vertex AI to NIE wystarcza** do legalnego przetwarzania danych psychiatrycznych w UE. Dane o zdrowiu psychicznym to dane szczególnej kategorii (art. 9 RODO).

- [ ] **Umowa powierzenia przetwarzania (DPA)** podpisana z Google Cloud (Data Processing and Security Terms — robisz to w Cloud Console po stronie organizacji).
- [ ] **Hosting przeniesiony ze Streamlit Community Cloud na Google Cloud Run** w regionie UE (Streamlit Cloud nie ma DPA dla danych medycznych, a filesystem jest efemeryczny).
- [ ] **Anonimizacja PII przed wysłaniem do Gemini** (`src/anonymize.py` — TODO; usuwanie imion, nazwisk, PESEL, adresów, telefonów z transkrypcji przed promptem).
- [ ] **Zgoda pacjenta** na nagrywanie i analizę AI (formularz w UI lub papierowy; konkretna, świadoma, dobrowolna).
- [ ] **Audyt logów dostępu**, RBAC i bezpieczne uwierzytelnianie lekarzy (zamiast jednego hasła w sekretach).
- [ ] **Polityka retencji** nagrań i transkrypcji, prawo pacjenta do usunięcia (RODO art. 17).
- [ ] **Trwała baza** poza efemerycznym kontenerem (np. Postgres w UE).

Do tego momentu apka **testowana jest wyłącznie na fikcyjnych/zaaranżowanych nagraniach**.

## Roadmapa (poza MVP)

- Migracja hostingu na **Cloud Run w UE** + DPA z Google.
- `src/anonymize.py` — usuwanie PII z transkrypcji.
- Formularz zgody pacjenta przed nagraniem.
- Trwała baza Postgres (Supabase/Neon/Cloud SQL w UE).
- Multi-tenant — `doctor_id` realnie wykorzystany do separacji danych.
- Autentykacja per lekarz (zamiast jednego hasła), RBAC, audyt logów.
- Ścieżka B: Whisper → tekst → Gemini (alternatywny pipeline, `generate_note_from_text` już jest jako stub).
