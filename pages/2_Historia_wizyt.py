import json

import pandas as pd
import streamlit as st

from src.auth import require_password
from src.db import get_visit, list_visits, usage_totals

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

selected_id = st.selectbox(
    "Wybierz wizytę do podglądu",
    options=[v["id"] for v in visits],
    format_func=lambda i: f"#{i}",
)

visit = get_visit(selected_id)
if not visit:
    st.stop()

st.caption(f"Utworzono: {visit['created_at']} · status: **{visit['status']}** · pipeline: {visit['pipeline']}")

with st.expander("📄 Surowa transkrypcja", expanded=False):
    st.write(visit.get("raw_transcript") or "_brak_")

col_orig, col_doc = st.columns(2)
with col_orig:
    st.subheader("🤖 Oryginał AI")
    try:
        st.json(json.loads(visit["ai_note_original_json"]))
    except Exception:
        st.code(visit["ai_note_original_json"])

with col_doc:
    st.subheader("👩‍⚕️ Wersja lekarza")
    corrected = visit.get("doctor_note_corrected_json")
    if corrected:
        try:
            st.json(json.loads(corrected))
        except Exception:
            st.code(corrected)
    else:
        st.info("Wizyta jeszcze niezatwierdzona — brak wersji lekarza.")
