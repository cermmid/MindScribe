"""Panel właściciela — użytkownicy, czas wizyt, koszty.

Osobna aplikacja Streamlit, uruchamiana niezależnie od aplikacji dla specjalistów:

    streamlit run admin/app.py

Chroniona własnym hasłem (`admin_password`) — celowo osobnym mechanizmem niż
logowanie specjalistów, bo panel widzi dane wszystkich.

GRANICA DANYCH: panel pokazuje wyłącznie metadane i agregaty. Nigdy transkrypcji,
treści notatek ani etykiet wizyt — właściciel aplikacji nie jest osobą prowadzącą
tych pacjentów, więc wgląd w treść wizyty byłby udostępnieniem dokumentacji medycznej
osobie nieuprawnionej.
"""

import hmac
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import (  # noqa: E402
    DatabaseUnavailable,
    admin_daily_stats,
    admin_user_stats,
    admin_visit_durations,
    init_db,
)
from src.config import GEMINI_MODEL  # noqa: E402
from src.nbp import get_usd_pln_rate  # noqa: E402
from src.pricing import (  # noqa: E402
    PRICES_ARE_PROVISIONAL,
    PRICES_CHECKED_ON,
    estimate_audio_seconds,
    format_duration,
    is_priced,
    usd_to_pln,
)

st.set_page_config(page_title="MindScribe — panel właściciela", page_icon="📊", layout="wide")


def _require_admin_password() -> None:
    try:
        expected = st.secrets.get("admin_password")
    except Exception:
        expected = None

    if not expected:
        st.error(
            "Brak `admin_password` w sekretach. Panel jest zablokowany.\n\n"
            "Ustaw go w `.streamlit/secrets.toml` albo w panelu Streamlit Cloud. "
            "To osobne poświadczenie niż logowanie specjalistów — panel widzi dane wszystkich."
        )
        st.stop()

    if st.session_state.get("admin_ok"):
        return

    st.title("🔐 Panel właściciela")
    with st.form("admin_login"):
        password = st.text_input("Hasło administratora", type="password")
        submitted = st.form_submit_button("Wejdź", type="primary")
    if not submitted:
        st.stop()
    if not hmac.compare_digest(password, expected):
        st.error("Nieprawidłowe hasło.")
        st.stop()
    st.session_state["admin_ok"] = True
    st.rerun()


_require_admin_password()
try:
    init_db()
except DatabaseUnavailable as exc:
    st.error(str(exc))
    st.stop()

st.title("📊 Panel właściciela")

usd_pln, rate_source = get_usd_pln_rate()
users = admin_user_stats()
visits = admin_visit_durations()

if not visits:
    st.info("Brak zapisanych wizyt.")
    st.stop()


def _duration_for(row: dict) -> tuple[float | None, bool]:
    """Zwróć (sekundy, czy_szacowane). Pomiar wygrywa z szacunkiem z tokenów."""
    measured = row.get("audio_duration_seconds")
    if measured:
        return float(measured), False
    estimated = estimate_audio_seconds(row.get("prompt_audio_tokens"))
    return estimated, estimated is not None


# --- Podsumowanie --------------------------------------------------------------
_durations = [_duration_for(v) for v in visits]
_known = [d for d, _ in _durations if d]
_estimated_count = sum(1 for d, est in _durations if d and est)
total_cost_pln = usd_to_pln(sum(float(v["estimated_cost_usd"] or 0) for v in visits), usd_pln)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Specjalistów", len(users))
c2.metric("Wizyt", len(visits))
c3.metric("Łączny czas nagrań", format_duration(sum(_known)) if _known else "—")
c4.metric("Koszt łącznie", f"{total_cost_pln:.2f} zł")

avg_cost = total_cost_pln / len(visits) if visits else 0.0
st.caption(
    f"Średni koszt wizyty: **{avg_cost:.4f} zł**. "
    f"Kurs USD/PLN {usd_pln:.4f} ({rate_source}). "
    f"Model: `{GEMINI_MODEL}`. Stawki z `src/pricing.py`, sprawdzone {PRICES_CHECKED_ON} — "
    "realny rachunek jest w Google Cloud Billing."
)

# Cennik ustalono ze źródeł wtórnych; dopóki nikt go nie potwierdził w konsoli,
# kwoty powyżej trzeba czytać jako orientacyjne.
if PRICES_ARE_PROVISIONAL:
    st.info(
        "ℹ️ Stawki modeli nie zostały jeszcze potwierdzone w konsoli Google Cloud. "
        "Po sprawdzeniu popraw tabelę na górze `src/pricing.py` i zdejmij tę flagę."
    )

# Nieznany model wyceniamy najdroższą znaną stawką — lepiej pokazać kwotę za wysoką
# i ją poprawić niż zaniżoną, która zniknęłaby z sumy bez śladu.
_unpriced = [v for v in visits if v.get("pricing_known") is False]
if _unpriced:
    _models = sorted({(v.get("gemini_model") or "?") for v in _unpriced})
    st.warning(
        f"⚠️ {len(_unpriced)} z {len(visits)} wizyt wyceniono **stawką zastępczą** — nie znamy "
        f"cennika modelu: {', '.join(f'`{m}`' for m in _models)}. Podane kwoty to **górne "
        "oszacowanie**. Dopisz stawki do `MODEL_PRICING_USD_PER_1M` w `src/pricing.py`."
    )
elif not is_priced(GEMINI_MODEL):
    st.warning(
        f"⚠️ Aplikacja jest ustawiona na `{GEMINI_MODEL}`, dla którego **nie mamy stawek**. "
        "Kolejne wizyty będą wyceniane najdroższą znaną stawką, aż dopiszesz cennik "
        "do `src/pricing.py`."
    )

if _estimated_count:
    st.warning(
        f"Czas {_estimated_count} z {len(visits)} wizyt jest **szacowany z liczby tokenów audio**, "
        "bo nagranie powstało zanim aplikacja zaczęła mierzyć długość. "
        "Szacunek jest wiarygodny dla dłuższych wizyt, a dla nagrań poniżej 5 minut "
        "w ogóle się nie pojawia (pokazujemy „—”)."
    )

# --- Per lekarz ----------------------------------------------------------------
st.subheader("Specjaliści")

_by_doctor: dict[str, list[float]] = {}
for visit, (seconds, _) in zip(visits, _durations):
    if seconds:
        _by_doctor.setdefault(visit["doctor"], []).append(seconds)

user_rows = []
for u in users:
    doctor_durations = _by_doctor.get(u["doctor"], [])
    total_seconds = sum(doctor_durations)
    user_rows.append(
        {
            "specjalista": u["doctor"],
            "wizyt": int(u["visits"]),
            "zatwierdzonych": int(u["approved"]),
            "łączny czas": format_duration(total_seconds) if doctor_durations else "—",
            "średni czas": (
                format_duration(total_seconds / len(doctor_durations)) if doctor_durations else "—"
            ),
            "koszt (PLN)": round(usd_to_pln(float(u["cost_usd"] or 0), usd_pln), 4),
            "ostatnia aktywność": str(u["last_activity"] or "")[:16].replace("T", " "),
        }
    )

st.dataframe(pd.DataFrame(user_rows), use_container_width=True, hide_index=True)

# --- W czasie ------------------------------------------------------------------
st.subheader("Aktywność w czasie")
daily = admin_daily_stats()
if daily:
    daily_df = pd.DataFrame(
        [
            {
                "dzień": d["day"],
                "wizyt": int(d["visits"]),
                "koszt (PLN)": round(usd_to_pln(float(d["cost_usd"] or 0), usd_pln), 4),
            }
            for d in daily
        ]
    ).set_index("dzień")
    left, right = st.columns(2)
    with left:
        st.caption("Liczba wizyt")
        st.bar_chart(daily_df["wizyt"])
    with right:
        st.caption("Koszt dzienny (PLN)")
        st.bar_chart(daily_df["koszt (PLN)"])

# --- Szczegóły wizyt -----------------------------------------------------------
with st.expander("📋 Wizyty pojedynczo (bez treści)", expanded=False):
    detail_rows = []
    for visit, (seconds, is_estimated) in zip(visits, _durations):
        detail_rows.append(
            {
                "numer": visit["id"],
                "data": str(visit["created_at"] or "")[:16].replace("T", " "),
                "specjalista": visit["doctor"],
                "typ": visit.get("visit_type") or "—",
                "status": visit["status"],
                "czas": format_duration(seconds) + (" (szac.)" if is_estimated else ""),
                "koszt (PLN)": round(usd_to_pln(float(visit["estimated_cost_usd"] or 0), usd_pln), 4),
            }
        )
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
    st.caption(
        "Panel celowo nie pokazuje transkrypcji, treści notatek ani etykiet wizyt — "
        "to dokumentacja medyczna dostępna wyłącznie osobie prowadzącej."
    )
