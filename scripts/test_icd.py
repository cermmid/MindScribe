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

    # --- ICD-11: wyszukiwanie po nazwie ---
    term = "generalised anxiety disorder"
    try:
        matches = icd.search(term, icd11=True)
    except icd.IcdUnavailable as exc:
        _line(False, f"Wyszukiwanie ICD-11 nie zadziałało: {exc}")
        return 1
    if matches:
        _line(True, f"ICD-11, wyszukiwanie „{term}” → {len(matches)} trafień:")
        for m in matches[:5]:
            print(f"      {m.code:<10} {m.title}")
    else:
        _line(False, f"ICD-11: brak trafień dla „{term}” — to podejrzane.")

    # --- ICD-11: sprawdzenie konkretnego kodu ---
    # 6B00 to zaburzenie lękowe uogólnione; 6A70 to POJEDYNCZY EPIZOD DEPRESYJNY.
    for code in ("6B00", "6A70", "QE80"):
        try:
            hit = icd.lookup_code(code, icd11=True)
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
        "i zrestartuj ją — kody rozpoznań zaczną dostawać znacznik potwierdzenia."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
