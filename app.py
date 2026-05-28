import streamlit as st

from src.db import init_db

st.set_page_config(page_title="MindScribe", page_icon="🧠", layout="wide")

init_db()

st.title("🧠 MindScribe")
st.subheader("Asystent psychiatry — transkrypcja i ustrukturyzowana notatka z wizyty")

st.markdown(
    """
**Workflow MVP:**

1. **Nowa wizyta** — wgraj/nagraj audio, AI wygeneruje notatkę (status psychiczny, objawy, kody ICD-10, zalecenia).
2. **Edytuj i zatwierdź** — naniesiesz poprawki w interfejsie HITL.
3. **Few-shot w locie** — 3 ostatnie zatwierdzone notatki są automatycznie doklejane do kolejnego promptu,
   więc model uczy się Twojego stylu pisania.
4. **Historia wizyt** — przegląd zapisanych wizyt i porównanie oryginału AI z wersją lekarza.

Wybierz stronę w panelu po lewej.
    """
)

st.info(
    "⚠️ MVP do testów wewnętrznych. Klucze API trzymaj w `.env`. "
    "Dla danych pacjentów produkcyjnie przełącz klienta Gemini na Vertex AI (patrz README)."
)
