# Klasyfikacje, dla których aplikacja sama ustala kod w rejestrze WHO. Reszta musi
# przyjść od modelu z kodem, bo nie ma kto go uzupełnić.
DEFAULT_LOOKUP_SYSTEMS = ["ICD-11"]

SYSTEM_PROMPT = """Jesteś doświadczonym asystentem klinicznym wspomagającym specjalistę zdrowia psychicznego
(psychiatrę, psychologa lub psychoterapeutę).
Twoje zadanie: na podstawie nagrania (lub transkrypcji) wizyty psychiatrycznej w języku polskim
przygotuj ustrukturyzowaną notatkę medyczną.

ZASADA NADRZĘDNA — ZAKAZ ZMYŚLANIA:
- Opisujesz WYŁĄCZNIE to, co faktycznie słychać w dołączonym nagraniu.
- Jeśli nagranie jest ciche, uszkodzone, zawiera tylko szum albo nie da się z niego nic zrozumieć:
  ustaw `jakosc_nagrania` na BRAK_MOWY, zostaw `raw_transcript` PUSTE, a pozostałe pola tekstowe
  wypełnij zwrotem "brak danych". NIE twórz wtedy żadnej transkrypcji ani objawów.
- Lepiej zwrócić pustą notatkę niż wymyśloną. Wymyślona treść w dokumentacji medycznej jest
  groźna dla pacjenta.
- PRZYKŁADY poniżej służą WYŁĄCZNIE do naśladowania stylu pisania. NIGDY nie przepisuj z nich
  treści, objawów, rozpoznań ani transkrypcji do nowej notatki.

Pozostałe zasady:
- Pisz po polsku, językiem klinicznym, ale zwięźle.
- Trzymaj się ŚCIŚLE schematu JSON podanego przez system — żadnych dodatkowych pól, żadnego tekstu poza JSON.
- KRYTYCZNE: pole `ryzyko_samobojcze` ZAWSZE wypełnij jedną z dwóch wartości — OBECNE lub NIEOBECNE.
  Wpisz OBECNE, jeśli w nagraniu pojawiają się jakiekolwiek myśli, plany, zamiary lub treści samobójcze
  (także pośrednie). Wpisz NIEOBECNE, jeśli pacjent je neguje lub nic na nie nie wskazuje. W
  `ryzyko_samobojcze_opis` w 1-2 zdaniach uzasadnij ocenę. To informacja krytyczna dla specjalisty — nie pomijaj.
  Gdy nagranie jest niezrozumiałe, wpisz NIEOBECNE i zaznacz w opisie, że nagranie nie pozwoliło tego ocenić.
- Rozpoznania podawaj wyłącznie wtedy, gdy obraz kliniczny je uzasadnia; dla każdej propozycji
  oszacuj realistyczną pewność.
- Jeśli w PRZYKŁADACH widzisz styl notatek tej konkretnej osoby — naśladuj sposób formułowania
  zdań, długość i akcenty, ale nie treść.
"""


def build_few_shot_block(examples: list[dict]) -> str:
    """examples: list of {raw_transcript: str, note_json: str} for last approved visits."""
    if not examples:
        return ""

    blocks = [
        "### PRZYKŁADY ZATWIERDZONYCH NOTATEK TEJ OSOBY\n"
        "UWAGA: to są notatki z INNYCH, wcześniejszych wizyt. Służą wyłącznie jako wzorzec STYLU.\n"
        "Nie przepisuj z nich żadnej treści do nowej notatki.\n"
    ]
    for i, ex in enumerate(examples, 1):
        blocks.append(
            f"--- PRZYKŁAD {i} (cudza wizyta, tylko styl) ---\n"
            f"Transkrypcja:\n{ex['raw_transcript']}\n\n"
            f"Zatwierdzona notatka (JSON):\n{ex['note_json']}\n"
        )
    blocks.append("--- KONIEC PRZYKŁADÓW ---\n")
    return "\n".join(blocks)


def build_user_prompt(
    few_shot_examples: list[dict],
    transcript: str | None = None,
    klasyfikacje: list[str] | str = "ICD-10",
    lookup_systems: list[str] | None = None,
) -> str:
    """Build the text prompt. If `transcript` is given, append it; otherwise rely on attached audio."""
    if isinstance(klasyfikacje, str):
        klasyfikacje = [klasyfikacje]
    wanted = [k for k in klasyfikacje if k] or ["ICD-10"]

    parts = [build_few_shot_block(few_shot_examples)]

    listing = ", ".join(f"**{k}**" for k in wanted)
    rule = [
        "### KLASYFIKACJE ROZPOZNAŃ",
        f"Dla tej wizyty użyj: {listing}.",
        f"W polu `klasyfikacje` wypisz dokładnie: {', '.join(wanted)}.",
    ]
    if len(wanted) > 1:
        rule.append(
            "To ten sam obraz kliniczny wyrażony w kilku systemach — dla KAŻDEGO rozpoznania "
            "utwórz osobny wpis w `kody_icd` dla każdej z tych klasyfikacji, oznaczając "
            "w polu `klasyfikacja` tę właściwą. Nie pomijaj żadnej i nie mieszaj kodów między nimi."
        )
    rule.append(
        "Najważniejsza jest **nazwa rozpoznania** (`description`) — wypełnij ją zawsze i precyzyjnie."
    )

    # Kod wolno pominąć TYLKO tam, gdzie aplikacja sama go ustali z rejestru.
    # Dla pozostałych klasyfikacji pusty kod oznacza wpis bezużyteczny dla lekarza.
    checked = [k for k in wanted if k in (lookup_systems or DEFAULT_LOOKUP_SYSTEMS)]
    unchecked = [k for k in wanted if k not in checked]

    if unchecked:
        rule.append(
            f"Dla {', '.join(unchecked)} pole `code` jest **OBOWIĄZKOWE** — podaj konkretny kod "
            "przy każdym rozpoznaniu. Nikt go za Ciebie nie uzupełni, więc wpis bez kodu jest "
            "dla specjalisty bezużyteczny."
        )
    if checked:
        rule.append(
            f"Dla {', '.join(checked)} pole `code` możesz zostawić PUSTE, jeśli nie masz pewności — "
            "kod zostanie ustalony w oficjalnym rejestrze WHO na podstawie nazwy, a każdy podany "
            "kod i tak jest tam sprawdzany. Tutaj zgadywanie nic nie daje."
        )
    if "DSM-5" in wanted:
        rule.append(
            "Przy DSM-5 podaj **pełną nazwę rozpoznania wg DSM-5** wraz z kodem, którego DSM-5 "
            "używa (są to kody ICD-10-CM)."
        )
    parts.append("\n".join(rule) + "\n")

    if transcript:
        parts.append(f"### TRANSKRYPCJA NOWEJ WIZYTY:\n{transcript}\n")
        parts.append("Wygeneruj notatkę zgodnie ze schematem.")
    else:
        parts.append(
            "### NOWA WIZYTA\n"
            "W załączeniu nagranie audio nowej wizyty psychiatrycznej.\n"
            "1. Najpierw posłuchaj nagrania i oceń, czy zawiera zrozumiałą mowę.\n"
            "2. Jeśli TAK — przepisz dosłowną transkrypcję do pola `raw_transcript`, "
            "a potem wygeneruj pozostałe pola na jej podstawie.\n"
            "3. Jeśli NIE (cisza, szum, nagranie nieczytelne) — ustaw `jakosc_nagrania` na BRAK_MOWY, "
            "zostaw `raw_transcript` puste i NIE wymyślaj treści wizyty."
        )
    return "\n".join(p for p in parts if p)
