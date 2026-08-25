import hmac

import streamlit as st


def _get_expected_password() -> str | None:
    try:
        pw = st.secrets.get("app_password")
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        pw = None
    return pw or None


def current_doctor() -> str | None:
    """Imię i nazwisko zalogowanej osoby.

    Nazwa funkcji jest historyczna — aplikacja służy psychiatrom, psychologom
    i psychoterapeutom, więc w interfejsie nie pada słowo „lekarz".
    """
    return st.session_state.get("doctor_name") or None


def require_password() -> None:
    """Block the page until the doctor enters their name and the password.

    Doctor name is mandatory and persists in session_state['doctor_name'].
    If no password is configured (local dev), the password check is skipped
    but the doctor name is still required.
    """
    expected = _get_expected_password()
    already_in = st.session_state.get("auth_ok") and current_doctor()

    if already_in:
        if doc := current_doctor():
            st.sidebar.caption(f"👤 Zalogowano: {doc}")
        return

    st.title("🔐 Logowanie")
    with st.form("login_form", clear_on_submit=False):
        doctor_name = st.text_input(
            "Imię i nazwisko",
            value=st.session_state.get("doctor_name", ""),
            placeholder="np. Anna Kowalska",
        )
        password = (
            st.text_input("Hasło dostępu", type="password")
            if expected is not None
            else ""
        )
        submitted = st.form_submit_button("Wejdź", type="primary")

    if not submitted:
        st.stop()

    if not doctor_name.strip():
        st.error("Wpisz imię i nazwisko.")
        st.stop()

    if expected is not None and not hmac.compare_digest(password, expected):
        st.error("Nieprawidłowe hasło.")
        st.stop()

    st.session_state["doctor_name"] = doctor_name.strip()
    st.session_state["auth_ok"] = True
    st.rerun()
