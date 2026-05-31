"""Pomocnicze komponenty UI: ładny widok notatki + przycisk kopiowania do schowka."""

import json
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from .formatting import risk_is_present, visit_type_label


def render_note(note: dict[str, Any], *, visit_type: str | None = None) -> None:
    """Ładnie wyrenderuj notatkę (nagłówki, pogrubienia, czerwony alert dla ryzyka)."""
    if visit_type:
        st.caption(visit_type_label(visit_type))

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

    if note.get("kody_icd10"):
        st.markdown("#### Rozpoznania (ICD-10)")
        for k in note["kody_icd10"]:
            conf = k.get("confidence")
            suffix = f" _(pewność {float(conf):.2f})_" if conf is not None else ""
            st.markdown(f"- **{k.get('code', '')}** — {k.get('description', '')}{suffix}")

    if note.get("zalecenia"):
        st.markdown("#### Zalecenia")
        for z in note["zalecenia"]:
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
