"""Punkt wejścia — logowanie, inicjalizacja bazy i nawigacja.

Nawigację budujemy jawnie przez `st.navigation`, a nie przez katalog `pages/`.
Powód jest prozaiczny: przy katalogu `pages/` Streamlit bierze nazwy pozycji
wprost z nazw plików, więc strona główna nazywała się „app". Tutaj każda pozycja
ma nazwę i ikonę ustawioną wprost.

Efekt uboczny jest cenniejszy niż sama nazwa: logowanie i przygotowanie bazy
dzieją się w JEDNYM miejscu, zanim uruchomi się jakikolwiek widok. Wcześniej
wejście prosto pod adres podstrony omijało oba te kroki.
"""

from pathlib import Path

import streamlit as st

from src.auth import require_login
from src.db import DatabaseUnavailable, init_db

# Ścieżka budowana od pliku, nie względna: `streamlit run` uruchomiony z innego
# katalogu roboczego nie znalazłby grafiki, a objawem byłby brak logo bez błędu.
_ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title="MindScribe", page_icon="🧠", layout="wide")

# Dwie poprawki wyglądu. Obie celują w wewnętrzne atrybuty Streamlita
# (`data-stale`, `data-testid`), więc przy jego aktualizacji trzeba je sprawdzić —
# gdy selektor przestanie trafiać, nic się nie zepsuje, tylko wróci zachowanie domyślne.
#
# 1. Streamlit przygasza całą stronę przy każdym przeładowaniu skryptu, a przeładowanie
#    odpala każde kliknięcie — zaznaczenie klasyfikacji, zmiana pola w tabeli. Miga to
#    bez przerwy i przy dłuższym wypełnianiu notatki męczy wzrok. Wygaszamy przygaszanie;
#    o tym, że coś się liczy, i tak mówi pasek postępu przy generowaniu.
# 2. Logo powiększone ponad to, co pozwala `st.logo` — szczegóły przy regule niżej.
st.markdown(
    """
    <style>
    [data-stale="true"], .element-container[data-stale="true"],
    [data-testid="stAppViewContainer"] [data-stale="true"] {
        opacity: 1 !important;
        transition: none !important;
        filter: none !important;
    }

    /* Logo. `size="large"` w `st.logo` to najwięcej, co daje API — reszta musi
       pójść stylem. Skalujemy SZEROKOŚCIĄ, nie wysokością: przy `height` i
       `max-width` naraz przeglądarka potrafi zgnieść proporcje, a tak logo
       zawsze mieści się w panelu i nigdy się nie zniekształca. */
    [data-testid="stLogo"] {
        width: 88% !important;
        max-width: 220px !important;
        height: auto !important;
        max-height: none !important;
        margin: 0.35rem 0 0.15rem 0;
    }
    /* Nagłówek panelu ma stałą wysokość i przyciąłby powiększone logo. */
    [data-testid="stSidebarHeader"] {
        height: auto !important;
        padding-bottom: 0.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

require_login()

# PO `require_login`, nie przed: logowanie kończy się `st.stop()`, a na ekranie
# logowania nie ma jeszcze panelu bocznego — logo trafiłoby wtedy w lewy górny róg
# obszaru głównego i wyglądało jak przypadek. `st.logo` renderuje się nad całą
# zawartością panelu, więc ląduje też nad podpisem „Zalogowano" z `src/auth.py`.
st.logo(
    str(_ASSETS / "logo.svg"),
    icon_image=str(_ASSETS / "logo-icon.svg"),
    size="large",
)

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
