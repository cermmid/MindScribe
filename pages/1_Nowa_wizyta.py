import pandas as pd
import streamlit as st

from src.audio import save_uploaded_audio
from src.auth import require_password
from src.db import get_approved_examples, insert_visit, update_visit
from src.gemini_client import generate_note_from_audio
from src.schemas import ICDCode, PsychiatricNote

st.set_page_config(page_title="Nowa wizyta — MindScribe", page_icon="🎙️", layout="wide")
require_password()
st.title("🎙️ Nowa wizyta")

# --- 1. Wejście audio ----------------------------------------------------------
st.header("1. Wejście audio")
col_a, col_b = st.columns(2)
with col_a:
    uploaded = st.file_uploader(
        "Wgraj plik audio (mp3 / wav / m4a / ogg)",
        type=["mp3", "wav", "m4a", "ogg", "webm", "flac"],
    )
with col_b:
    recorded = st.audio_input("…lub nagraj z mikrofonu")

audio_bytes: bytes | None = None
audio_suffix = ".wav"
if uploaded is not None:
    audio_bytes = uploaded.getvalue()
    audio_suffix = "." + (uploaded.name.rsplit(".", 1)[-1].lower() if "." in uploaded.name else "wav")
elif recorded is not None:
    audio_bytes = recorded.getvalue()
    audio_suffix = ".wav"

# --- 2. Generacja notatki ------------------------------------------------------
st.header("2. Generacja notatki")

if st.button("🪄 Wygeneruj notatkę", type="primary", disabled=audio_bytes is None):
    audio_path = save_uploaded_audio(audio_bytes, suffix=audio_suffix)
    few_shot = get_approved_examples()
    with st.spinner(f"Gemini analizuje nagranie (few-shot z {len(few_shot)} zatwierdzonych notatek)…"):
        try:
            note, debug_prompt = generate_note_from_audio(audio_path, few_shot)
        except Exception as e:
            st.error(f"Błąd wywołania Gemini: {e}")
            st.stop()

    visit_id = insert_visit(
        audio_path=str(audio_path),
        pipeline="multimodal",
        raw_transcript=note.raw_transcript,
        ai_note_original_json=note.model_dump_json(indent=2),
    )
    st.session_state["current_visit_id"] = visit_id
    st.session_state["current_note"] = note.model_dump()
    st.session_state["debug_prompt"] = debug_prompt
    st.success(f"Wizyta #{visit_id} zapisana jako draft.")

# --- 3. HITL: edycja -----------------------------------------------------------
if "current_note" in st.session_state:
    st.header("3. Edycja (Human-in-the-Loop)")
    note_data = st.session_state["current_note"]

    with st.expander("📄 Surowa transkrypcja", expanded=False):
        raw = st.text_area(
            "Transkrypcja",
            value=note_data.get("raw_transcript", ""),
            height=200,
            label_visibility="collapsed",
        )

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
            icd_records = [
                ICDCode(
                    code=str(r.get("code", "")).strip(),
                    description=str(r.get("description", "")).strip(),
                    confidence=float(r.get("confidence", 0.0) or 0.0),
                ).model_dump()
                for _, r in edited_icd.iterrows()
                if str(r.get("code", "")).strip()
            ]
            corrected = PsychiatricNote(
                raw_transcript=raw,
                status_psychiczny=status_psychiczny,
                objawy=[s.strip() for s in objawy_text.splitlines() if s.strip()],
                kody_icd10=[ICDCode(**r) for r in icd_records],
                zalecenia=[s.strip() for s in zalecenia_text.splitlines() if s.strip()],
                podsumowanie=podsumowanie,
            )
        except Exception as e:
            st.error(f"Notatka nie przeszła walidacji: {e}")
            st.stop()

        update_visit(
            st.session_state["current_visit_id"],
            doctor_note_corrected_json=corrected.model_dump_json(indent=2),
            status="approved",
        )
        st.success(
            f"Wizyta #{st.session_state['current_visit_id']} zatwierdzona. "
            "Ta notatka zasili few-shot dla przyszłych generacji."
        )
        for key in ("current_note", "current_visit_id", "debug_prompt"):
            st.session_state.pop(key, None)

    if "debug_prompt" in st.session_state:
        with st.expander("🐛 Debug: prompt wysłany do Gemini", expanded=False):
            st.code(st.session_state["debug_prompt"], language="markdown")
