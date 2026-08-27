"""Punkt wejścia — logowanie, inicjalizacja bazy i nawigacja.

Nawigację budujemy jawnie przez `st.navigation`, a nie przez katalog `pages/`.
Powód jest prozaiczny: przy katalogu `pages/` Streamlit bierze nazwy pozycji
wprost z nazw plików, więc strona główna nazywała się „app". Tutaj każda pozycja
ma nazwę i ikonę ustawioną wprost.

Efekt uboczny jest cenniejszy niż sama nazwa: logowanie i przygotowanie bazy
dzieją się w JEDNYM miejscu, zanim uruchomi się jakikolwiek widok. Wcześniej
wejście prosto pod adres podstrony omijało oba te kroki.
"""

import streamlit as st

from src.auth import require_login
from src.db import DatabaseUnavailable, init_db

st.set_page_config(page_title="MindScribe", page_icon="🧠", layout="wide")

require_login()

try:
    init_db()
except DatabaseUnavailable as exc:
    st.error(str(exc))
    st.stop()

st.navigation(
    [
        st.Page("views/home.py", title="Strona główna", icon="🏠", default=True),
        st.Page("views/new_visit.py", title="Nowa wizyta", icon="🎙️"),
        st.Page("views/history.py", title="Historia wizyt", icon="📚"),
    ]
).run()
