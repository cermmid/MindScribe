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

## Baza danych

Warstwa danych stoi na SQLAlchemy Core i jest przenośna między SQLite a PostgreSQL. Adres bierze się z `DATABASE_URL`:

- **puste** → lokalny SQLite w `data/mindscribe.db` (development i testy działają bez serwera),
- **connection string z Neona** → PostgreSQL. Można go wkleić dokładnie tak, jak podaje panel — prefiks `postgresql://` jest zamieniany na `postgresql+psycopg://` automatycznie.

⚠️ Na Streamlit Community Cloud SQLite **znika przy każdym restarcie kontenera**, razem z wizytami. Trwała baza to warunek wieloosobowej pracy, nie ulepszenie.

### Sprawdzenie migracji na własnej bazie

Ta sama seria testów działa na obu silnikach — to jest dowód, że przejście na Postgresa niczego nie zmieniło:

```bash
pytest                                                   # SQLite
TEST_DATABASE_URL='postgresql://...' pytest              # PostgreSQL
```

⚠️ Testy **czyszczą tabelę `visits`** w podanej bazie. Podawaj wyłącznie bazę testową. Dlatego jest to osobna zmienna niż `DATABASE_URL` — żeby nie dało się wyczyścić produkcji przez pomyłkę.

### Rzeczy, które przy tej migracji psują się po cichu

Warto o nich wiedzieć, bo żadna nie rzuca błędu:

- `engine.connect()` w SQLAlchemy 2 **nie commituje** przy wyjściu z `with`, choć `sqlite3` commitował. Dlatego `_conn()` zwraca `engine.begin()` — inaczej zapisy znikałyby, a odczyty działały.
- `cur.lastrowid` nie działa pod psycopg — `insert_visit` używa `INSERT ... RETURNING id`.
- `date(created_at)` istnieje w SQLite, ale w Postgresie `date` to typ, nie funkcja. Grupowanie po dniu robimy w Pythonie.
- `REAL` w Postgresie to float4 — koszt trzymamy jako `Numeric(14,6)`.
- `SUM()` po kolumnie całkowitej zwraca `Decimal`; konwersja jest w jednym miejscu, przy odczycie wiersza.

## Weryfikacja rozpoznań w rejestrze WHO

**Model językowy nie może być źródłem kodów rozpoznań.** W testach podał kody ICD-11, które *istnieją*, ale znaczą co innego niż twierdził — np. `QE80` („ofiara przestępstwa lub terroryzmu") opisane jako zaburzenia snu, czy `6A70` (pojedynczy epizod depresyjny) podane jako lęk uogólniony. Walidacja formatu tego nie wykryje, bo kody są prawdziwe. ICD-11 obowiązuje dopiero od 2022 i jest w danych treningowych nieporównanie słabiej reprezentowana niż ICD-10, więc mapowanie kod ↔ znaczenie jest u modelu niepewne.

Dlatego kody przechodzą przez oficjalne API WHO:

1. model podaje przede wszystkim **nazwę rozpoznania**, a kod tylko gdy jest go pewien,
2. aplikacja potwierdza kod w rejestrze i **zastępuje opis oficjalnym tytułem WHO**, więc para kod–opis nie może się rozjechać,
3. gdy kodu brak lub nie istnieje — szuka po nazwie rozpoznania,
4. czego nie da się potwierdzić, trafia do notatki oznaczone jako **niezweryfikowane**, także w tekście do skopiowania (`[DO WERYFIKACJI]`).

### Konfiguracja (5 min)

1. Załóż konto na https://icd.who.int/icdapi (darmowe).
2. Zakładka **API Access Keys** → **Create new key**. Skopiuj `Client Id` i `Client Secret`.
3. **Sprawdź klucze zanim wrzucisz je do aplikacji:**
   ```bash
   ICD_CLIENT_ID=... ICD_CLIENT_SECRET=... python3 scripts/test_icd.py
   ```
   Skrypt pobiera token, wyszukuje rozpoznanie w ICD-11 i sprawdza kilka konkretnych kodów w ICD-11 i ICD-10. Po każdym kroku pisze, co poszło nie tak — dzięki temu wiadomo, czy problem jest w kluczach, w sieci, czy w samym API.
4. Gdy skrypt pokazuje same ✅, wpisz `ICD_CLIENT_ID` i `ICD_CLIENT_SECRET` do sekretów aplikacji i zrestartuj ją.

Bez tych kluczy aplikacja **działa normalnie**, ale każde rozpoznanie jest oznaczane jako niezweryfikowane — awaria API czy brak konfiguracji nigdy nie przerywa generowania notatki.

⚠️ Weryfikacja potwierdza, że **kod istnieje i co oznacza**. Nie potwierdza, że rozpoznanie jest trafne klinicznie — to zawsze decyzja lekarza.

### Wybór klasyfikacji: ICD-10, ICD-11, DSM-5

Lekarz zaznacza jedną albo kilka naraz — przy kilku to samo rozpoznanie dostaje osobny wpis w każdym systemie, a widok i tekst do skopiowania grupują je po systemie.

**DSM-5 działa inaczej i trzeba o tym wiedzieć.** Wydaje go Amerykańskie Towarzystwo Psychiatryczne, jest objęty prawem autorskim i **nie ma publicznego rejestru do odpytania** — odpowiednika API WHO po prostu nie ma. Dlatego rozpoznania DSM-5 **zawsze** wracają oznaczone do weryfikacji, niezależnie od tego, jak pewny jest model.

Ponieważ DSM-5 posługuje się kodami ICD-10-CM, gdy model poda kod, robimy pomocniczą kontrolę w ICD-10 i dopisujemy jej wynik w uwadze („Kontrolnie: F41.1 w ICD-10 to…"). To wskazówka dla lekarza, **nie potwierdzenie** — ICD-10-CM to amerykańska modyfikacja i nie każdy jej kod istnieje w wersji WHO.

## Panel właściciela (koszty i statystyki)

Lekarze **nie widzą** kosztów ani zużycia tokenów — te dane są dalej zbierane i zapisywane, ale pokazywane wyłącznie w osobnej aplikacji:

```bash
streamlit run admin/app.py
```

Panel wymaga sekretu `admin_password` (innego niż `app_password` lekarzy) i pokazuje:

- podsumowanie: liczba lekarzy, wizyt, łączny czas nagrań, koszt w PLN i średni koszt wizyty,
- tabelę per lekarz: liczba wizyt, łączny i średni czas, koszt, ostatnia aktywność,
- wykresy dzienne: liczba wizyt i koszt,
- listę wizyt pojedynczo — **wyłącznie metadane**.

### Czego panel nie pokazuje i dlaczego

Zapytania w `admin_user_stats()`, `admin_daily_stats()` i `admin_visit_durations()` celowo **nie selektują** `raw_transcript`, `ai_note_original_json`, `doctor_note_corrected_json` ani `visit_label`.

Właściciel aplikacji nie jest lekarzem prowadzącym tych pacjentów — wgląd w treść wizyty byłby udostępnieniem dokumentacji medycznej osobie nieuprawnionej. Liczba wizyt, czas trwania i koszt to dane operacyjne i te są w porządku. Nie usuwaj tego ograniczenia bez konsultacji z IOD.

### Skąd bierze się „czas wizyty"

Kolejność źródeł: **zmierzony** czas nagrania (kolumna `audio_duration_seconds`), a gdy go brak — **szacunek** z liczby tokenów audio (Gemini tokenizuje audio ze stałą częstotliwością ~32 tokeny/s).

Szacunek jest oznaczony w panelu i celowo **nie pojawia się dla nagrań krótszych niż 5 minut**: narzut tekstowy promptu (system prompt, schemat, few-shot) to 1–3 tys. tokenów, co przy krótkim nagraniu dominuje wynik. Przy realnej 30-minutowej wizycie ten sam narzut to kilka procent i jest do przyjęcia.

Aplikacja mobilna (PWA) będzie znała dokładny czas nagrywania, więc z czasem szacunek przestanie być potrzebny.

⚠️ **Panel jako osobna aplikacja wymaga wspólnej bazy.** Przy obecnym SQLite na dysku kontenera druga aplikacja na Streamlit Cloud dostanie własny, pusty plik. Lokalnie działa od razu; wdrożenie osobno ma sens dopiero po migracji na Postgresa.

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
