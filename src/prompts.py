SYSTEM_PROMPT = """Jesteś doświadczonym asystentem klinicznym wspomagającym lekarza psychiatrę.
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
  `ryzyko_samobojcze_opis` w 1-2 zdaniach uzasadnij ocenę. To informacja krytyczna dla lekarza — nie pomijaj.
  Gdy nagranie jest niezrozumiałe, wpisz NIEOBECNE i zaznacz w opisie, że nagranie nie pozwoliło tego ocenić.
- Rozpoznania podawaj wyłącznie wtedy, gdy obraz kliniczny je uzasadnia; dla każdej propozycji
  oszacuj realistyczną pewność.
- Jeśli w PRZYKŁADACH widzisz styl notatek tego konkretnego lekarza — naśladuj sposób formułowania
  zdań, długość i akcenty, ale nie treść.
"""


def build_few_shot_block(examples: list[dict]) -> str:
    """examples: list of {raw_transcript: str, note_json: str} for last approved visits."""
    if not examples:
        return ""

    blocks = [
        "### PRZYKŁADY ZATWIERDZONYCH NOTATEK TEGO LEKARZA\n"
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
    klasyfikacja: str = "ICD-10",
) -> str:
    """Build the text prompt. If `transcript` is given, append it; otherwise rely on attached audio."""
    parts = [build_few_shot_block(few_shot_examples)]

    classification_rule = (
        f"### KLASYFIKACJA ROZPOZNAŃ\n"
        f"Dla tej wizyty użyj klasyfikacji **{klasyfikacja}**. "
        f"W polu `kody_icd` podaj wyłącznie kody z {klasyfikacja}, "
        f"a w polu `klasyfikacja` wpisz dokładnie \"{klasyfikacja}\".\n"
    )
    parts.append(classification_rule)

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
