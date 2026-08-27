import json

import streamlit as st

from src.auth import current_user_id, require_login
from src.db import DatabaseUnavailable, get_visit, list_visits
from src.formatting import display_name, humanize_visits_df, note_to_text
from src.services import resolve_note_version
from src.ui import copy_button, render_note

st.set_page_config(page_title="Historia wizyt — MindScribe", page_icon="📚", layout="wide")
require_login()
st.title("📚 Historia wizyt")

try:
    visits = list_visits(doctor_id=current_user_id())
except DatabaseUnavailable as exc:
    st.error(str(exc))
    st.stop()
if not visits:
    st.info("Brak zapisanych wizyt. Przejdź do **Nowa wizyta**, żeby wygenerować pierwszą notatkę.")
    st.stop()

# Koszty i zużycie tokenów są celowo poza widokiem lekarza — patrz admin/app.py.
st.metric("Wizyt łącznie", len(visits))

st.dataframe(
    humanize_visits_df(visits),
    use_container_width=True,
    hide_index=True,
)

_by_id = {v["id"]: v for v in visits}
selected_id = st.selectbox(
    "Wybierz wizytę do podglądu",
    options=[v["id"] for v in visits],
    format_func=lambda i: display_name(_by_id[i]),
)

with st.expander("📂 Pokaż szczegóły wizyty", expanded=False):
    visit = get_visit(selected_id, doctor_id=current_user_id())
    if not visit:
        st.warning("Nie znaleziono wizyty.")
    else:
        st.subheader(display_name(visit))
        st.caption(
            f"Utworzono: {visit['created_at']} · status: **{visit['status']}** · "
            f"tryb: {visit['pipeline']} · prowadzący: {visit.get('doctor_name') or '_brak_'}"
        )

        resolved = resolve_note_version(visit)
        corrected = visit.get("doctor_note_corrected_json")
        if not resolved.is_corrected:
            st.info("Wizyta niezatwierdzona — pokazana wersja oryginalna AI.")

        note = resolved.note
        if note:
            render_note(note, visit_type=visit.get("visit_type"))
            note_text = note_to_text(
                note,
                title=display_name(visit),
                visit_type=visit.get("visit_type"),
                created_at=visit.get("created_at"),
                doctor_name=visit.get("doctor_name"),
            )
            copy_button(note_text, key=f"copy_hist_{selected_id}")
            with st.expander("📄 Pełny tekst (zaznacz i skopiuj ręcznie)", expanded=False):
                st.text(note_text)
        else:
            st.code(resolved.source_json or "_brak_")

        with st.expander("📄 Surowa transkrypcja", expanded=False):
            st.write(visit.get("raw_transcript") or "_brak_")

        with st.expander("🔬 Surowy JSON (debug)", expanded=False):
            if visit.get("ai_note_original_json"):
                st.json(json.loads(visit["ai_note_original_json"]))
            if corrected:
                st.caption("Wersja po korekcie:")
                st.json(json.loads(corrected))
