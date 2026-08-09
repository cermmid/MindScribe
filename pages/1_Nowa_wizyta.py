import pandas as pd
import streamlit as st

from src.auth import current_doctor, require_password
from src.formatting import note_to_text
from src.services import (
    DEFAULT_AUDIO_SUFFIX,
    approve_note,
    build_corrected_note,
    create_visit_from_audio,
    derive_audio_suffix,
    load_few_shot_examples,
    split_lines,
)
from src.ui import copy_button, render_note

st.set_page_config(page_title="Nowa wizyta — MindScribe", page_icon="🎙️", layout="wide")
require_password()
st.title("🎙️ Nowa wizyta")

# --- 1. Dane wizyty ------------------------------------------------------------
st.header("1. Dane wizyty")
visit_label = st.text_input(
    "Etykieta wizyty (opcjonalnie)",
    placeholder="np. pacjent A — lęki",
    help=(
        "NIE wpisuj imienia, nazwiska ani żadnych danych, które umożliwią identyfikację "
        "pacjenta przez osoby trzecie. Używaj pseudonimu lub krótkiego opisu."
    ),
)
visit_type = st.radio("Typ wizyty", ["Pierwsza", "Kolejna"], horizontal=True)

# --- 2. Wejście audio ----------------------------------------------------------
st.header("2. Wejście audio")
col_a, col_b = st.columns(2)
with col_a:
    uploaded = st.file_uploader(
        "Wgraj plik audio (mp3 / wav / m4a / ogg)",
        type=["mp3", "wav", "m4a", "ogg", "webm", "flac"],
    )
with col_b:
    recorded = st.audio_input("…lub nagraj z mikrofonu")

audio_bytes: bytes | None = None
audio_suffix = DEFAULT_AUDIO_SUFFIX
if uploaded is not None:
    audio_bytes = uploaded.getvalue()
    audio_suffix = derive_audio_suffix(uploaded.name)
elif recorded is not None:
    audio_bytes = recorded.getvalue()
    audio_suffix = DEFAULT_AUDIO_SUFFIX

# --- 3. Generacja notatki ------------------------------------------------------
st.header("3. Generacja notatki")

if st.button("🪄 Wygeneruj notatkę", type="primary", disabled=audio_bytes is None):
    few_shot = load_few_shot_examples()
    with st.spinner(f"Gemini analizuje nagranie (few-shot z {len(few_shot)} zatwierdzonych notatek)…"):
        try:
            created = create_visit_from_audio(
                audio_bytes,
                audio_suffix=audio_suffix,
                visit_label=visit_label,
                visit_type=visit_type,
                doctor_id=current_doctor(),
                few_shot=few_shot,
            )
        except Exception as e:
            st.error(f"Błąd wywołania Gemini: {e}")
            st.stop()

    st.session_state["current_visit_id"] = created.visit_id
    st.session_state["current_note"] = created.note.model_dump()
    st.session_state["debug_prompt"] = created.debug_prompt
    st.session_state["current_usage"] = created.usage
    st.success(f"Wizyta #{created.visit_id} zapisana jako draft.")

# Zużycie tokenów i koszt są dalej zapisywane do bazy, ale świadomie NIE pokazywane
# lekarzowi — to dane biznesowe właściciela, widoczne w osobnym panelu (admin/app.py).

# --- 4. HITL: edycja -----------------------------------------------------------
if "current_note" in st.session_state:
    st.header("4. Edycja (Human-in-the-Loop)")
    note_data = st.session_state["current_note"]

    with st.expander("📄 Surowa transkrypcja", expanded=False):
        raw = st.text_area(
            "Transkrypcja",
            value=note_data.get("raw_transcript", ""),
            height=200,
            label_visibility="collapsed",
        )

    st.markdown("**🛑 Myśli samobójcze** (pole krytyczne)")
    _risk_options = ["OBECNE", "NIEOBECNE"]
    _risk_default = note_data.get("ryzyko_samobojcze", "NIEOBECNE")
    ryzyko = st.radio(
        "Ryzyko samobójcze",
        _risk_options,
        index=_risk_options.index(_risk_default) if _risk_default in _risk_options else 1,
        horizontal=True,
        label_visibility="collapsed",
    )
    ryzyko_opis = st.text_input(
        "Opis / uzasadnienie ryzyka",
        value=note_data.get("ryzyko_samobojcze_opis", ""),
    )
    if ryzyko == "OBECNE":
        st.error("⚠️ Pacjent z myślami samobójczymi — wymaga szczególnej uwagi klinicznej.")

    status_psychiczny = st.text_area(
        "Status psychiczny",
        value=note_data.get("status_psychiczny", ""),
        height=120,
    )

    objawy_text = st.text_area(
        "Objawy (jeden w linii)",
        value="\n".join(note_data.get("objawy", [])),
        height=120,
    )

    st.markdown("**Proponowane kody ICD-10**")
    icd_df = pd.DataFrame(note_data.get("kody_icd10", []) or [{"code": "", "description": "", "confidence": 0.0}])
    edited_icd = st.data_editor(
        icd_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "code": st.column_config.TextColumn("Kod", required=True),
            "description": st.column_config.TextColumn("Opis"),
            "confidence": st.column_config.NumberColumn(
                "Pewność", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"
            ),
        },
        key="icd_editor",
    )

    zalecenia_text = st.text_area(
        "Zalecenia (jedno w linii)",
        value="\n".join(note_data.get("zalecenia", [])),
        height=120,
    )

    podsumowanie = st.text_area(
        "Podsumowanie",
        value=note_data.get("podsumowanie", ""),
        height=100,
    )

    if st.button("✅ Zatwierdź i zapisz", type="primary"):
        try:
            corrected = build_corrected_note(
                raw_transcript=raw,
                ryzyko_samobojcze=ryzyko,
                ryzyko_samobojcze_opis=ryzyko_opis,
                status_psychiczny=status_psychiczny,
                objawy=split_lines(objawy_text),
                kody_icd10=edited_icd.to_dict("records"),
                zalecenia=split_lines(zalecenia_text),
                podsumowanie=podsumowanie,
            )
        except Exception as e:
            st.error(f"Notatka nie przeszła walidacji: {e}")
            st.stop()

        approve_note(st.session_state["current_visit_id"], corrected)
        st.session_state["approved_note"] = corrected.model_dump()
        st.session_state["approved_visit_id"] = st.session_state["current_visit_id"]
        st.session_state["approved_visit_type"] = visit_type
        st.success(
            f"Wizyta #{st.session_state['current_visit_id']} zatwierdzona. "
            "Ta notatka zasili few-shot dla przyszłych generacji."
        )
        for key in ("current_note", "current_visit_id", "debug_prompt", "current_usage"):
            st.session_state.pop(key, None)

    if "debug_prompt" in st.session_state:
        with st.expander("🐛 Debug: prompt wysłany do Gemini", expanded=False):
            st.code(st.session_state["debug_prompt"], language="markdown")

# --- 5. Zatwierdzona notatka do skopiowania -----------------------------------
if "approved_note" in st.session_state:
    st.header("5. Gotowa notatka")
    approved = st.session_state["approved_note"]
    a_type = st.session_state.get("approved_visit_type")
    render_note(approved, visit_type=a_type)

    note_text = note_to_text(
        approved,
        title=f"Wizyta #{st.session_state.get('approved_visit_id', '')}",
        visit_type=a_type,
        doctor_name=current_doctor(),
    )
    copy_button(note_text, key="copy_new")
    with st.expander("📄 Pełny tekst (zaznacz i skopiuj ręcznie)", expanded=False):
        st.text(note_text)
