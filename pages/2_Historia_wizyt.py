import json

import streamlit as st

from src.auth import require_password
from src.db import get_visit, list_visits, usage_totals
from src.formatting import display_name, humanize_visits_df, note_to_text
from src.nbp import get_usd_pln_rate
from src.pricing import usd_to_pln
from src.services import resolve_note_version
from src.ui import copy_button, render_note

st.set_page_config(page_title="Historia wizyt — MindScribe", page_icon="📚", layout="wide")
require_password()
st.title("📚 Historia wizyt")

visits = list_visits()
if not visits:
    st.info("Brak zapisanych wizyt. Przejdź do **Nowa wizyta**, żeby wygenerować pierwszą notatkę.")
    st.stop()

usd_pln, rate_source = get_usd_pln_rate()
totals = usage_totals()
total_pln = usd_to_pln(float(totals["estimated_cost_usd"]), usd_pln)

t1, t2, t3, t4 = st.columns(4)
t1.metric("Wizyt łącznie", int(totals["n"]))
t2.metric("Tokeny wejściowe", f"{int(totals['prompt_tokens']):,}".replace(",", " "))
t3.metric("Tokeny wyjściowe", f"{int(totals['output_tokens']):,}".replace(",", " "))
t4.metric("Szacowany koszt łącznie", f"{total_pln:.4f} zł")
st.caption(
    f"Koszt to **szacunek** wg stawek z `src/pricing.py` (Gemini 2.5 Flash), "
    f"przeliczony kursem USD/PLN **{usd_pln:.4f}** ({rate_source}). "
    "Realny rachunek sprawdzisz w Google Cloud Billing."
)

st.dataframe(
    humanize_visits_df(visits, usd_pln),
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
    visit = get_visit(selected_id)
    if not visit:
        st.warning("Nie znaleziono wizyty.")
    else:
        st.subheader(display_name(visit))
        st.caption(
            f"Utworzono: {visit['created_at']} · status: **{visit['status']}** · "
            f"tryb: {visit['pipeline']} · lekarz: {visit.get('doctor_id') or '_brak_'}"
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
                doctor_name=visit.get("doctor_id"),
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
                st.caption("Wersja lekarza:")
                st.json(json.loads(corrected))
