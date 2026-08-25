"""Renderowanie notatki jako czytelny zwykły tekst (do kopiowania) + pomocnicze nazwy wizyt.

Funkcje są tolerancyjne — czytają przez .get() z domyślnymi wartościami, więc działają także
na starszych zatwierdzonych notatkach sprzed dodania pola ryzyka samobójczego.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pandas jest potrzebny wyłącznie dla tabeli Streamlita (patrz niżej)
    import pandas as pd


def visit_type_label(visit_type: str | None) -> str:
    v = (visit_type or "").strip().lower()
    if v.startswith("pierw"):
        return "Pierwsza wizyta"
    if v.startswith("kolej"):
        return "Wizyta kolejna"
    return "Typ wizyty nieokreślony"


def display_name(visit: dict[str, Any]) -> str:
    """Czytelna nazwa wizyty: 'Wizyta #N z dnia RRRR-MM-DD — etykieta'."""
    name = f"Wizyta #{visit.get('id', '?')}"
    created = (visit.get("created_at") or "")[:10]
    if created:
        name += f" z dnia {created}"
    label = (visit.get("visit_label") or "").strip()
    if label:
        name += f" — {label}"
    return name


def get_icd_codes(note: dict[str, Any]) -> list[dict[str, Any]]:
    """Kody rozpoznań, tolerancyjnie wobec notatek sprzed dodania wyboru ICD-11.

    Starsze notatki mają klucz `kody_icd10`, nowe `kody_icd`.
    """
    return note.get("kody_icd") or note.get("kody_icd10") or []


def classifications_of(note: dict[str, Any]) -> list[str]:
    """Klasyfikacje użyte w notatce, tolerancyjnie wobec starszych wpisów.

    Notatki sprzed wyboru wielu klasyfikacji mają pojedyncze `klasyfikacja`,
    a te sprzed dodania ICD-11 nie mają go wcale — wtedy z definicji ICD-10.
    """
    many = note.get("klasyfikacje")
    if isinstance(many, list) and many:
        return [str(k) for k in many if k]
    single = note.get("klasyfikacja")
    return [str(single)] if single else ["ICD-10"]


def classification_label(note: dict[str, Any]) -> str:
    """Czytelna etykieta klasyfikacji, np. „ICD-10" albo „ICD-10 + DSM-5"."""
    return " + ".join(classifications_of(note))


def group_codes_by_classification(note: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Rozpoznania pogrupowane po klasyfikacji, w kolejności z notatki."""
    codes = get_icd_codes(note)
    order = classifications_of(note)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for code in codes:
        key = str(code.get("klasyfikacja") or "").strip() or (order[0] if order else "ICD-10")
        grouped.setdefault(key, []).append(code)
    # Najpierw klasyfikacje zamówione przez lekarza, potem ewentualne pozostałe.
    ordered = {k: grouped[k] for k in order if k in grouped}
    ordered.update({k: v for k, v in grouped.items() if k not in ordered})
    return ordered


def audio_unusable(note: dict[str, Any]) -> bool:
    """Czy model zgłosił, że w nagraniu nie było zrozumiałej mowy."""
    return str(note.get("jakosc_nagrania", "")).upper() == "BRAK_MOWY"


def audio_quality_label(note: dict[str, Any]) -> str | None:
    quality = str(note.get("jakosc_nagrania", "")).upper()
    if quality == "BRAK_MOWY":
        return "W nagraniu nie wykryto zrozumiałej mowy — notatka może być pusta lub niepełna."
    if quality == "SLABA":
        return "Nagranie częściowo niezrozumiałe — sprawdź transkrypcję szczególnie uważnie."
    return None


def risk_is_present(note: dict[str, Any]) -> bool:
    return str(note.get("ryzyko_samobojcze", "")).upper() == "OBECNE"


def risk_line(note: dict[str, Any]) -> str:
    present = risk_is_present(note)
    head = "⚠️ MYŚLI SAMOBÓJCZE: OBECNE" if present else "MYŚLI SAMOBÓJCZE: NIEOBECNE"
    opis = (note.get("ryzyko_samobojcze_opis") or "").strip()
    return f"{head} — {opis}" if opis else head


def note_to_text(
    note: dict[str, Any],
    *,
    title: str | None = None,
    visit_type: str | None = None,
    created_at: str | None = None,
    doctor_name: str | None = None,
) -> str:
    """Zbuduj pełną, czytelną notatkę tekstową gotową do skopiowania."""
    lines: list[str] = []

    if title:
        lines.append(title)
    meta = []
    if visit_type:
        meta.append(visit_type_label(visit_type))
    if created_at:
        meta.append(f"Data: {created_at[:10]}")
    if meta:
        lines.append(" · ".join(meta))
    lines.append("=" * 48)

    # Ostrzeżenie o nagraniu — przed treścią, żeby nie dało się go przeoczyć.
    if warning := audio_quality_label(note):
        lines.append(f"!! UWAGA: {warning}")
        lines.append("")

    # Ryzyko samobójcze — ZAWSZE na początku.
    lines.append(risk_line(note))
    lines.append("")

    podsumowanie = (note.get("podsumowanie") or "").strip()
    if podsumowanie:
        lines.append("PODSUMOWANIE")
        lines.append(podsumowanie)
        lines.append("")

    status = (note.get("status_psychiczny") or "").strip()
    if status:
        lines.append("STATUS PSYCHICZNY")
        lines.append(status)
        lines.append("")

    objawy = note.get("objawy") or []
    if objawy:
        lines.append("OBJAWY")
        lines.extend(f"- {o}" for o in objawy)
        lines.append("")

    grouped = group_codes_by_classification(note)
    if grouped:
        any_unverified = False
        for system, kody in grouped.items():
            lines.append(f"ROZPOZNANIA ({system})")
            for k in kody:
                code = (k.get("code") or "").strip()
                desc = (k.get("description") or "").strip()
                line = f"- {code}" if code else "- (brak kodu)"
                if desc:
                    line += f" — {desc}"
                # Oznaczenie trafia też tutaj, bo ten tekst lekarz wkleja do dokumentacji.
                if not k.get("zweryfikowany"):
                    line += " [DO WERYFIKACJI]"
                    any_unverified = True
                lines.append(line)
            lines.append("")
        if any_unverified:
            lines.append(
                "Pozycje [DO WERYFIKACJI] nie zostały potwierdzone w oficjalnym rejestrze."
            )
            lines.append("")

    zalecenia = note.get("zalecenia") or []
    if zalecenia:
        lines.append("ZALECENIA")
        lines.extend(f"- {z}" for z in zalecenia)
        lines.append("")

    if doctor_name:
        lines.append(f"Lekarz: {doctor_name}")

    return "\n".join(lines).strip() + "\n"


# Polskie nazwy kolumn dla widoku Historii. Kolejność = porządek kluczy w słowniku.
# Świadomie BEZ tokenów i kosztu — lekarz ich nie widzi, są tylko w panelu właściciela.
_COLUMN_RENAME: dict[str, str] = {
    "id": "numer",
    "visit_label": "nazwa wizyty",
    "created_at": "utworzona",
    "visit_type": "pierwsza czy kolejna wizyta",
    "doctor_id": "lekarz",
    "status": "status",
    "pipeline": "tryb",
}


def humanize_visits_df(visits: list[dict[str, Any]]) -> "pd.DataFrame":
    """Tabela wizyt z polskimi nagłówkami, w ustalonej kolejności.

    Jedyna funkcja w tym module wymagająca pandas — importujemy go tutaj, żeby
    reszta (formatowanie notatki, zgodność ze starymi wpisami) działała także
    w backendzie bez pandas. Ta funkcja i tak znika przy przejściu na PWA.
    """
    import pandas as pd

    if not visits:
        return pd.DataFrame(columns=list(_COLUMN_RENAME.values()))

    df = pd.DataFrame(visits)
    if "created_at" in df.columns:
        df["created_at"] = df["created_at"].astype(str).str.replace("T", " ").str[:16]
    if "visit_type" in df.columns:
        df["visit_type"] = df["visit_type"].apply(visit_type_label)

    keep = [c for c in _COLUMN_RENAME if c in df.columns]
    return df[keep].rename(columns=_COLUMN_RENAME)
