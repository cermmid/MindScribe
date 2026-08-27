import pandas as pd
import streamlit as st

from src.audio import looks_silent
from src.db import DatabaseUnavailable
from src.auth import current_doctor, current_user_id
from src.formatting import (
    audio_quality_label,
    audio_unusable,
    get_icd_codes,
    needs_manual_check,
    note_to_text,
    verification_state,
)
from src.services import (
    DEFAULT_AUDIO_SUFFIX,
    VisitNotUpdated,
    approve_note,
    build_corrected_note,
    create_visit_from_audio,
    derive_audio_suffix,
    load_few_shot_examples,
    split_lines,
)
from src.ui import copy_button, render_note

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
st.markdown("**Klasyfikacje rozpoznań** — zaznacz jedną albo kilka naraz")
_systems = ["ICD-10", "ICD-11", "DSM-5"]
_cols = st.columns(len(_systems))
klasyfikacje = [
    system
    for system, col in zip(_systems, _cols)
    if col.checkbox(system, value=(system == "ICD-10"), key=f"kl_{system}")
]
if not klasyfikacje:
    st.warning("Zaznacz przynajmniej jedną klasyfikację — użyję ICD-10.")
    klasyfikacje = ["ICD-10"]
if len(klasyfikacje) > 1:
    st.caption("To samo rozpoznanie dostanie kod w każdym z zaznaczonych systemów.")
if "DSM-5" in klasyfikacje:
    st.caption(
        "ℹ️ DSM-5 wydaje Amerykańskie Towarzystwo Psychiatryczne i **nie ma publicznego "
        "rejestru**, więc jego rozpoznań nie potwierdzamy automatycznie — zostaną oznaczone "
        "do weryfikacji. W rejestrze WHO sprawdzamy ICD-11."
    )

# --- 2. Wejście audio ----------------------------------------------------------
st.header("2. Wejście audio")
col_a, col_b = st.columns(2)
with col_a:
    recorded = st.audio_input("🎙️ Nagraj wizytę")
with col_b:
    uploaded = st.file_uploader(
        "…albo wgraj plik audio (mp3 / wav / m4a / ogg)",
        type=["mp3", "wav", "m4a", "ogg", "webm", "flac"],
    )

audio_bytes: bytes | None = None
audio_suffix = DEFAULT_AUDIO_SUFFIX
audio_mime: str | None = None
# Nagranie z mikrofonu ma pierwszeństwo — to główna ścieżka, upload jest alternatywą.
if recorded is not None:
    audio_bytes = recorded.getvalue()
    audio_mime = getattr(recorded, "type", None)
    audio_suffix = derive_audio_suffix(getattr(recorded, "name", None))
elif uploaded is not None:
    audio_bytes = uploaded.getvalue()
    audio_mime = getattr(uploaded, "type", None)
    audio_suffix = derive_audio_suffix(uploaded.name)

# --- 3. Generacja notatki ------------------------------------------------------
st.header("3. Generacja notatki")

# Cisza w nagraniu = model nie ma czego transkrybować. Sprawdzamy PRZED wysyłką,
# żeby nie płacić za pustą notatkę i żeby lekarz od razu wiedział, że to mikrofon.
_silent = audio_bytes is not None and looks_silent(audio_bytes, audio_mime)
_force = False
if _silent:
    st.error(
        "🔇 **W nagraniu nie ma dźwięku.** Przeglądarka nagrywała, ale nie dostała sygnału "
        "z mikrofonu — jeśli podczas nagrywania wykres się nie ruszał, to jest właśnie ta sytuacja.\n\n"
        "Najczęstsze przyczyny (po kolei):\n"
        "1. **Windows blokuje mikrofon przeglądarce** — Ustawienia → Prywatność i zabezpieczenia → "
        "Mikrofon → włącz *Zezwalaj aplikacjom klasycznym na dostęp do mikrofonu*. "
        "Uprawnienie w przeglądarce może być przyznane, a system i tak podaje ciszę.\n"
        "2. **Przeglądarka używa innego urządzenia** niż testowane w Windows — kliknij ikonę "
        "kłódki/mikrofonu przy adresie strony i wybierz właściwy mikrofon.\n"
        "3. **Inna aplikacja trzyma mikrofon** (Teams, Zoom, Discord) — zamknij ją i odśwież stronę."
    )
    _force = st.checkbox("Wyślij mimo to (jeśli uważasz, że nagranie jest dobre)")

if st.button(
    "🪄 Wygeneruj notatkę",
    type="primary",
    disabled=audio_bytes is None or (_silent and not _force),
):
    try:
        few_shot = load_few_shot_examples(current_user_id())
    except DatabaseUnavailable as exc:
        st.error(str(exc))
        st.stop()
    _spinner_text = "Słucham nagrania i przygotowuję notatkę… to chwilę potrwa."
    if few_shot:
        _spinner_text = (
            f"Słucham nagrania i przygotowuję notatkę w Twoim stylu "
            f"(na podstawie {len(few_shot)} wcześniej zatwierdzonych)…"
        )
    with st.spinner(_spinner_text):
        try:
            created = create_visit_from_audio(
                audio_bytes,
                audio_suffix=audio_suffix,
                audio_mime=audio_mime,
                visit_label=visit_label,
                visit_type=visit_type,
                doctor_id=current_user_id(),
                doctor_name=current_doctor(),
                few_shot=few_shot,
                klasyfikacje=klasyfikacje,
            )
        except DatabaseUnavailable as exc:
            st.error(str(exc))
            st.stop()
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
    st.header("4. Edycja")
    note_data = st.session_state["current_note"]

    # Jeśli model nie miał czego słuchać, lekarz musi to zobaczyć PRZED czytaniem treści.
    if audio_unusable(note_data):
        st.error(
            "🔇 **W nagraniu nie wykryto zrozumiałej mowy.** "
            "Notatka poniżej jest pusta albo szczątkowa — to poprawne zachowanie, "
            "model ma zakaz zmyślania treści. Sprawdź mikrofon i nagraj wizytę ponownie."
        )
    elif warning := audio_quality_label(note_data):
        st.warning(f"🔉 {warning}")

    _transcript = (note_data.get("raw_transcript") or "").strip()
    if not _transcript and not audio_unusable(note_data):
        st.warning(
            "Transkrypcja jest pusta, choć model nie zgłosił problemu z nagraniem. "
            "Zweryfikuj nagranie przed zatwierdzeniem notatki."
        )

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

    st.markdown(f"**Proponowane rozpoznania — {' + '.join(klasyfikacje)}**")
    _codes = get_icd_codes(note_data)
    _unverified = [k for k in _codes if needs_manual_check(k)]
    if _unverified:
        st.warning(
            f"⚠️ {len(_unverified)} z {len(_codes)} rozpoznań **nie zostało potwierdzonych "
            "w oficjalnym rejestrze** — sprawdź je ręcznie."
        )
    for k in _codes:
        if uwaga := (k.get("uwaga") or "").strip():
            st.caption(f"• {k.get('klasyfikacja') or '?'} {k.get('code') or '—'}: {uwaga}")

    _default_system = klasyfikacje[0]
    icd_df = pd.DataFrame(
        [
            {
                "klasyfikacja": k.get("klasyfikacja") or _default_system,
                "code": k.get("code", ""),
                "description": k.get("description", ""),
                "confidence": k.get("confidence", 0.0),
                "weryfikacja": verification_state(k),
            }
            for k in _codes
        ]
        or [
            {
                "klasyfikacja": _default_system,
                "code": "",
                "description": "",
                "confidence": 0.0,
                "weryfikacja": "NIESPRAWDZANY",
            }
        ]
    )
    edited_icd = st.data_editor(
        icd_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "klasyfikacja": st.column_config.SelectboxColumn(
                "System", options=["ICD-10", "ICD-11", "DSM-5"], required=True
            ),
            "code": st.column_config.TextColumn(
                "Kod", help="Zostaw puste, żeby kod dobrał się automatycznie z nazwy rozpoznania."
            ),
            "description": st.column_config.TextColumn("Rozpoznanie", required=True),
            "confidence": st.column_config.NumberColumn(
                "Pewność", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"
            ),
            "weryfikacja": st.column_config.TextColumn(
                "Rejestr WHO",
                help=(
                    "POTWIERDZONY — sprawdzony w rejestrze. NIESPRAWDZANY — ICD-10 i DSM-5 "
                    "przyjmujemy bez odpytywania. NIEPOTWIERDZONY — sprawdzaliśmy i nie ma."
                ),
                disabled=True,
            ),
        },
        key="icd_editor",
    )
    st.caption("Po zatwierdzeniu kody ICD są ponownie sprawdzane w rejestrze WHO.")

    zalecenia_text = st.text_area(
        "Zalecenia (jedno w linii)",
        value="\n".join(note_data.get("zalecenia_terapeuty") or note_data.get("zalecenia") or []),
        height=120,
        help="To, co faktycznie zaleciłaś/zaleciłeś podczas wizyty.",
    )

    propozycje_text = st.text_area(
        "Propozycje do rozważenia (jedna w linii)",
        value="\n".join(note_data.get("zalecenia_proponowane") or []),
        height=100,
        help=(
            "Sugestie asystenta, których nie było na wizycie. Przenieś do pola wyżej to, "
            "co przyjmujesz, a resztę usuń."
        ),
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
                kody_icd=edited_icd.to_dict("records"),
                zalecenia_terapeuty=split_lines(zalecenia_text),
                zalecenia_proponowane=split_lines(propozycje_text),
                podsumowanie=podsumowanie,
                klasyfikacje=klasyfikacje,
                jakosc_nagrania=note_data.get("jakosc_nagrania", "DOBRA"),
            )
        except Exception as e:
            st.error(f"Notatka nie przeszła walidacji: {e}")
            st.stop()

        try:
            approve_note(
                st.session_state["current_visit_id"], corrected, doctor_id=current_user_id()
            )
        except VisitNotUpdated as e:
            # Zapis nie doszedł do skutku — lepiej powiedzieć to wprost, niż pokazać
            # „zatwierdzono" i pozwolić zamknąć kartę z niezapisaną notatką.
            st.error(f"Notatka NIE została zapisana. {e}")
            st.stop()

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
