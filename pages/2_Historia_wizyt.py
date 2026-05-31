import json

import pandas as pd
import streamlit as st

from src.auth import require_password
from src.db import get_visit, list_visits, usage_totals
from src.formatting import display_name, note_to_text
from src.ui import copy_button, render_note

st.set_page_config(page_title="Historia wizyt — MindScribe", page_icon="📚", layout="wide")
require_password()
st.title("📚 Historia wizyt")

visits = list_visits()
if not visits:
    st.info("Brak zapisanych wizyt. Przejdź do **Nowa wizyta**, żeby wygenerować pierwszą notatkę.")
    st.stop()

totals = usage_totals()
t1, t2, t3, t4 = st.columns(4)
t1.metric("Wizyt łącznie", int(totals["n"]))
t2.metric("Tokeny wejściowe", f"{int(totals['prompt_tokens']):,}".replace(",", " "))
t3.metric("Tokeny wyjściowe", f"{int(totals['output_tokens']):,}".replace(",", " "))
t4.metric("Szacowany koszt łącznie", f"${totals['estimated_cost_usd']:.4f}")
st.caption(
    "Koszt to **szacunek** wg stawek z `src/pricing.py` (Gemini 2.5 Flash). "
    "Realny rachunek sprawdzisz w Google Cloud Billing → *Generative Language API*."
)

st.dataframe(pd.DataFrame(visits), use_container_width=True, hide_index=True)

_by_id = {v["id"]: v for v in visits}
selected_id = st.selectbox(
    "Wybierz wizytę do podglądu",
    options=[v["id"] for v in visits],
    format_func=lambda i: display_name(_by_id[i]),
)

visit = get_visit(selected_id)
if not visit:
    st.stop()

st.subheader(display_name(visit))
st.caption(f"Utworzono: {visit['created_at']} · status: **{visit['status']}** · pipeline: {visit['pipeline']}")

# Wybór wersji do pokazania: zatwierdzona przez lekarza, a jeśli brak — oryginał AI.
corrected = visit.get("doctor_note_corrected_json")
source_json = corrected or visit.get("ai_note_original_json")
if not corrected:
    st.info("Wizyta niezatwierdzona — pokazana wersja oryginalna AI.")

try:
    note = json.loads(source_json)
except Exception:
    note = None

if note:
    render_note(note, visit_type=visit.get("visit_type"))
    note_text = note_to_text(
        note,
        title=display_name(visit),
        visit_type=visit.get("visit_type"),
        created_at=visit.get("created_at"),
    )
    copy_button(note_text, key=f"copy_hist_{selected_id}")
    with st.expander("📄 Pełny tekst (zaznacz i skopiuj ręcznie)", expanded=False):
        st.text(note_text)
else:
    st.code(source_json or "_brak_")

with st.expander("📄 Surowa transkrypcja", expanded=False):
    st.write(visit.get("raw_transcript") or "_brak_")

with st.expander("🔬 Surowy JSON (debug)", expanded=False):
    st.json(json.loads(visit["ai_note_original_json"])) if visit.get("ai_note_original_json") else None
    if corrected:
        st.caption("Wersja lekarza:")
        st.json(json.loads(corrected))
