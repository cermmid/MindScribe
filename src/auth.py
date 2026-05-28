import hmac

import streamlit as st


def _get_expected_password() -> str | None:
    try:
        pw = st.secrets.get("app_password")
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        pw = None
    return pw or None


def require_password() -> None:
    """Block the page until the user enters the password from st.secrets["app_password"].

    If no password is configured (local dev without secrets.toml), this is a no-op.
    """
    expected = _get_expected_password()
    if expected is None:
        return

    if st.session_state.get("password_correct"):
        return

    def _check():
        entered = st.session_state.get("password", "")
        if hmac.compare_digest(entered, expected):
            st.session_state["password_correct"] = True
            st.session_state.pop("password", None)
        else:
            st.session_state["password_correct"] = False

    st.text_input(
        "🔒 Hasło dostępu",
        type="password",
        on_change=_check,
        key="password",
    )
    if st.session_state.get("password_correct") is False:
        st.error("Nieprawidłowe hasło.")
    st.stop()
