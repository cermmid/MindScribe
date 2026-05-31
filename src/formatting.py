"""Renderowanie notatki jako czytelny zwykły tekst (do kopiowania) + pomocnicze nazwy wizyt.

Funkcje są tolerancyjne — czytają przez .get() z domyślnymi wartościami, więc działają także
na starszych zatwierdzonych notatkach sprzed dodania pola ryzyka samobójczego.
"""

from typing import Any


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

    kody = note.get("kody_icd10") or []
    if kody:
        lines.append("ROZPOZNANIA (ICD-10)")
        for k in kody:
            code = (k.get("code") or "").strip()
            desc = (k.get("description") or "").strip()
            conf = k.get("confidence")
            line = f"- {code}"
            if desc:
                line += f" — {desc}"
            if conf is not None:
                line += f" (pewność {float(conf):.2f})"
            lines.append(line)
        lines.append("")

    zalecenia = note.get("zalecenia") or []
    if zalecenia:
        lines.append("ZALECENIA")
        lines.extend(f"- {z}" for z in zalecenia)
        lines.append("")

    return "\n".join(lines).strip() + "\n"
