"""Kurs USD→PLN z NBP API (tabela A), z cache i fallbackiem."""

import requests
import streamlit as st

NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/A/USD/?format=json"
FALLBACK_USD_PLN = 4.05


@st.cache_data(ttl=86400, show_spinner=False)
def get_usd_pln_rate() -> tuple[float, str]:
    """Zwraca (kurs, etykieta_źródła). Cache na dobę. Fallback do stałej przy błędzie."""
    try:
        r = requests.get(NBP_URL, timeout=5)
        r.raise_for_status()
        data = r.json()
        rate = float(data["rates"][0]["mid"])
        effective = str(data["rates"][0].get("effectiveDate", ""))
        return rate, f"NBP {effective}" if effective else "NBP"
    except Exception:
        return FALLBACK_USD_PLN, f"fallback {FALLBACK_USD_PLN:.2f}"
