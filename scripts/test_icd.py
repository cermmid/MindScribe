#!/usr/bin/env python3
"""Sprawdź poświadczenia WHO ICD API bez uruchamiania całej aplikacji.

Użycie:

    ICD_CLIENT_ID=... ICD_CLIENT_SECRET=... python3 scripts/test_icd.py

albo, jeśli masz już wpisane klucze w `.streamlit/secrets.toml` lub `.env`:

    python3 scripts/test_icd.py

Skrypt kolejno: pobiera token, wyszukuje rozpoznanie w ICD-11, sprawdza konkretny
kod w ICD-11 i w ICD-10. Po każdym kroku pisze, co dokładnie poszło nie tak —
dzięki temu wiadomo, czy problem jest w kluczach, w sieci, czy w samym API.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import icd  # noqa: E402


def _line(ok: bool, text: str) -> None:
    print(f"{'✅' if ok else '❌'} {text}")


def _dump_trace(trace: list[dict]) -> None:
    """Pokaż każdą próbę odpytania wyszukiwarki — to z tego wynika, gdzie jest problem.

    Rozróżnienie, na którym najbardziej zależy: „zapytanie się nie udało" (błąd HTTP,
    zły adres) to co innego niż „zapytanie się udało, ale nic nie zwróciło", a jedno
    i drugie kończy się w aplikacji tak samo — brakiem kodu.
    """
    if not trace:
        return
    print("      ── próby zapytań ──")
    for attempt in trace:
        head = (
            f"      {attempt['path']} [{attempt['language']}, "
            f"flexisearch={attempt['flexisearch']}]"
        )
        if error := attempt.get("error"):
            print(f"{head} → BŁĄD: {error}")
        elif (status := attempt.get("status", 200)) >= 400:
            print(f"{head} → HTTP {status} (zły adres albo błąd serwera, nie brak wyniku)")
        else:
            print(
                f"{head} → HTTP {status}, encji: {attempt.get('entities', 0)}, "
                f"z kodem: {attempt.get('matches', 0)}"
            )


def main() -> int:
    print("Sprawdzam integrację z rejestrem WHO ICD…\n")

    if not icd.is_configured():
        _line(False, "Brak ICD_CLIENT_ID / ICD_CLIENT_SECRET.")
        print(
            "\n   Klucze znajdziesz na https://icd.who.int/icdapi → zakładka\n"
            "   'API Access Keys' → 'Create new key'. Potem albo ustaw je jako\n"
            "   zmienne środowiskowe, albo wpisz do .streamlit/secrets.toml."
        )
        return 1
    _line(True, "Poświadczenia znalezione w konfiguracji.")

    try:
        token = icd._access_token()
    except icd.IcdUnavailable as exc:
        _line(False, f"Nie udało się pobrać tokenu: {exc}")
        print(
            "\n   Najczęstsze przyczyny: literówka w Client Id/Secret, klucz\n"
            "   usunięty w panelu WHO, albo brak dostępu do sieci."
        )
        return 1
    _line(True, f"Token pobrany (długość {len(token)} znaków).")

    # --- ICD-11: które wydanie widzimy ---
    release = icd._release_id()
    if release:
        _line(True, f"Najnowsze wydanie ICD-11 wg WHO: {release}")
    else:
        _line(False, "Nie udało się ustalić numeru wydania ICD-11 (zostaje adres bez numeru).")
    print(f"      adres linearyzacji: {icd.BASE_URL}/{icd._mms_prefix()}")

    # --- ICD-11: wyszukiwanie po nazwie ---
    # Szukamy po angielsku, bo tak robi aplikacja — rejestr WHO nie ma polskich nazw.
    for term in ("generalised anxiety disorder", "recurrent depressive disorder"):
        trace: list[dict] = []
        try:
            matches = icd.search(term, icd11=True, language="en", trace=trace)
        except icd.IcdUnavailable as exc:
            _line(False, f"Wyszukiwanie ICD-11 „{term}” nie zadziałało: {exc}")
            _dump_trace(trace)
            return 1
        if matches:
            _line(True, f"ICD-11, wyszukiwanie „{term}” → {len(matches)} trafień:")
            for m in matches[:5]:
                print(f"      {m.code:<10} {m.title}")
        else:
            _line(False, f"ICD-11: brak trafień dla „{term}” — to podejrzane.")
        _dump_trace(trace)

    # --- ICD-11: sprawdzenie konkretnego kodu ---
    # 6B00 to zaburzenie lękowe uogólnione; 6A70 to POJEDYNCZY EPIZOD DEPRESYJNY.
    for code in ("6B00", "6A70", "QE80"):
        try:
            hit = icd.lookup_code(code, icd11=True, language="en")
        except icd.IcdUnavailable as exc:
            _line(False, f"ICD-11, sprawdzenie {code}: {exc}")
            continue
        if hit:
            _line(True, f"ICD-11 {code} = {hit.title}")
        else:
            _line(False, f"ICD-11 {code} — nie znaleziono.")

    # --- ICD-10: sprawdzenie kodu ---
    for code in ("F41.1", "F32.1"):
        try:
            hit = icd.lookup_code(code, icd11=False)
        except icd.IcdUnavailable as exc:
            _line(False, f"ICD-10, sprawdzenie {code}: {exc}")
            continue
        if hit:
            _line(True, f"ICD-10 {code} = {hit.title}")
        else:
            _line(False, f"ICD-10 {code} — nie znaleziono.")

    print(
        "\nJeśli powyżej są same ✅, wpisz te same klucze do sekretów aplikacji\n"
        "i zrestartuj ją — kody rozpoznań zaczną dostawać znacznik potwierdzenia.\n"
        "\nJeśli ICD-11 nie znajduje nic, przeklej całe wyjście razem z sekcjami\n"
        "z próbami zapytań — widać w nich, czy zapytanie w ogóle doszło do WHO."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
