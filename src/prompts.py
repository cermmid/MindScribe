SYSTEM_PROMPT = """Jesteś doświadczonym asystentem klinicznym wspomagającym lekarza psychiatrę.
Twoje zadanie: na podstawie nagrania (lub transkrypcji) wizyty psychiatrycznej w języku polskim
przygotuj ustrukturyzowaną notatkę medyczną.

Zasady:
- Pisz po polsku, językiem klinicznym, ale zwięźle.
- Trzymaj się ŚCIŚLE schematu JSON podanego przez system — żadnych dodatkowych pól, żadnego tekstu poza JSON.
- Nie zmyślaj danych, których nie ma w nagraniu. Jeśli czegoś brak, zostaw pole puste lub krótko zaznacz "brak danych".
- Kody ICD-10 podawaj wyłącznie wtedy, gdy obraz kliniczny je uzasadnia; dla każdej propozycji oszacuj realistyczną pewność.
- Jeśli w PRZYKŁADACH poniżej widzisz styl notatek tego konkretnego lekarza — naśladuj jego sposób formułowania zdań, długość, akcenty.
"""


def build_few_shot_block(examples: list[dict]) -> str:
    """examples: list of {raw_transcript: str, note_json: str} for last approved visits."""
    if not examples:
        return ""

    blocks = ["### PRZYKŁADY ZATWIERDZONYCH NOTATEK TEGO LEKARZA (naśladuj styl):\n"]
    for i, ex in enumerate(examples, 1):
        blocks.append(
            f"--- PRZYKŁAD {i} ---\n"
            f"Transkrypcja:\n{ex['raw_transcript']}\n\n"
            f"Zatwierdzona notatka (JSON):\n{ex['note_json']}\n"
        )
    blocks.append("--- KONIEC PRZYKŁADÓW ---\n")
    return "\n".join(blocks)


def build_user_prompt(few_shot_examples: list[dict], transcript: str | None = None) -> str:
    """Build the text prompt. If `transcript` is given, append it; otherwise rely on attached audio."""
    parts = [build_few_shot_block(few_shot_examples)]
    if transcript:
        parts.append(f"### TRANSKRYPCJA NOWEJ WIZYTY:\n{transcript}\n")
        parts.append("Wygeneruj notatkę zgodnie ze schematem.")
    else:
        parts.append(
            "### NOWA WIZYTA\n"
            "W załączeniu nagranie audio nowej wizyty psychiatrycznej. "
            "Najpierw przepisz pełną transkrypcję do pola `raw_transcript`, "
            "a następnie wygeneruj pozostałe pola notatki zgodnie ze schematem."
        )
    return "\n".join(p for p in parts if p)
