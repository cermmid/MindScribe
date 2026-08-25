import streamlit as st

from src.auth import require_password
from src.db import init_db

st.set_page_config(page_title="MindScribe", page_icon="🧠", layout="wide")
require_password()

init_db()

st.title("🧠 MindScribe")
st.subheader("Asystent specjalistów od zdrowia psychicznego")

st.markdown(
    """
Nagraj wizytę i odzyskaj czas, który zwykle pochłania pisanie notatki.

MindScribe słucha nagrania i przygotowuje gotowy szkic dokumentacji: opis stanu
psychicznego, objawy, proponowane rozpoznania i zalecenia. Ty czytasz, poprawiasz
i zatwierdzasz — ostatnie słowo zawsze należy do Ciebie.

**Co wyróżnia tę aplikację:**

- **Myśli samobójcze zawsze na wierzchu.** Każda notatka zaczyna się od jednoznacznej
  informacji o ryzyku — nie trzeba jej szukać w tekście.
- **Kody rozpoznań sprawdzane u źródła.** ICD-10 i ICD-11 potwierdzamy w oficjalnym
  rejestrze WHO, więc kod i jego znaczenie nie mogą się rozjechać. Możesz też pracować
  na DSM-5.
- **Uczy się Twojego stylu.** Im więcej notatek zatwierdzisz, tym bardziej kolejne
  przypominają sposób, w jaki piszesz Ty.
- **Nic nie jest zmyślane.** Gdy nagranie jest nieczytelne, aplikacja powie to wprost,
  zamiast wypełniać notatkę treścią, której nie było.

Zacznij od **Nowa wizyta** w panelu po lewej.
    """
)

st.info(
    "⚠️ Wersja testowa. Korzystaj wyłącznie z nagrań fikcyjnych lub odegranych — "
    "aplikacja nie jest jeszcze przygotowana do pracy z danymi prawdziwych pacjentów."
)
