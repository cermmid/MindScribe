"""Pomocnicze komponenty UI: ładny widok notatki + przycisk kopiowania do schowka."""

import json
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from .formatting import (
    audio_quality_label,
    audio_unusable,
    group_codes_by_classification,
    risk_is_present,
    visit_type_label,
)


def render_note(note: dict[str, Any], *, visit_type: str | None = None) -> None:
    """Ładnie wyrenderuj notatkę (nagłówki, pogrubienia, czerwony alert dla ryzyka)."""
    if visit_type:
        st.caption(visit_type_label(visit_type))

    # Ostrzeżenie o nagraniu idzie NAD wszystkim — jeśli model nie miał czego słuchać,
    # lekarz musi to zobaczyć zanim przeczyta jakąkolwiek treść.
    if warning := audio_quality_label(note):
        if audio_unusable(note):
            st.error(f"🔇 **{warning}**")
        else:
            st.warning(f"🔉 {warning}")

    opis = (note.get("ryzyko_samobojcze_opis") or "").strip()
    if risk_is_present(note):
        st.error(f"⚠️ **MYŚLI SAMOBÓJCZE: OBECNE**{(' — ' + opis) if opis else ''}")
    else:
        st.success(f"**Myśli samobójcze: NIEOBECNE**{(' — ' + opis) if opis else ''}")

    if note.get("podsumowanie"):
        st.markdown("#### Podsumowanie")
        st.write(note["podsumowanie"])

    if note.get("status_psychiczny"):
        st.markdown("#### Status psychiczny")
        st.write(note["status_psychiczny"])

    if note.get("objawy"):
        st.markdown("#### Objawy")
        for o in note["objawy"]:
            st.markdown(f"- {o}")

    if grouped := group_codes_by_classification(note):
        all_codes = [k for kody in grouped.values() for k in kody]
        unverified = [k for k in all_codes if not k.get("zweryfikowany")]
        if unverified:
            st.warning(
                f"⚠️ {len(unverified)} z {len(all_codes)} rozpoznań **nie zostało potwierdzonych "
                "w oficjalnym rejestrze**. Sprawdź je ręcznie przed wpisaniem do dokumentacji."
            )
        for system, kody in grouped.items():
            st.markdown(f"#### Rozpoznania ({system})")
            for k in kody:
                mark = "✅" if k.get("zweryfikowany") else "❓"
                code = k.get("code") or "—"
                conf = k.get("confidence")
                suffix = f" _(pewność rozpoznania {float(conf):.2f})_" if conf is not None else ""
                st.markdown(f"- {mark} **{code}** — {k.get('description', '')}{suffix}")
                if uwaga := (k.get("uwaga") or "").strip():
                    st.caption(f"　↳ {uwaga}")

    # Starsze notatki miały jedno pole `zalecenia`.
    if wlasne := (note.get("zalecenia_terapeuty") or note.get("zalecenia")):
        st.markdown("#### Zalecenia")
        for z in wlasne:
            st.markdown(f"- {z}")

    if proponowane := note.get("zalecenia_proponowane"):
        st.markdown("#### Propozycje do rozważenia")
        st.caption("Sugestie asystenta — nie padły podczas wizyty.")
        for z in proponowane:
            st.markdown(f"- {z}")


def copy_button(text: str, *, label: str = "📋 Kopiuj notatkę", key: str = "copy") -> None:
    """Przycisk kopiujący `text` do schowka. Działa w iframe Streamlit (fallback execCommand)."""
    payload = json.dumps(text)
    html = f"""
    <button id="{key}" style="
        background:#1f77b4;color:#fff;border:none;border-radius:6px;
        padding:8px 16px;font-size:14px;cursor:pointer;">{label}</button>
    <script>
    const btn = document.getElementById("{key}");
    const txt = {payload};
    btn.addEventListener("click", async () => {{
        const orig = btn.innerText;
        try {{
            await navigator.clipboard.writeText(txt);
        }} catch (e) {{
            const ta = document.createElement("textarea");
            ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = "0";
            document.body.appendChild(ta); ta.focus(); ta.select();
            try {{ document.execCommand("copy"); }} catch (e2) {{}}
            document.body.removeChild(ta);
        }}
        btn.innerText = "✅ Skopiowano!";
        setTimeout(() => {{ btn.innerText = orig; }}, 1500);
    }});
    </script>
    """
    components.html(html, height=48)
