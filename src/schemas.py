from enum import Enum

from pydantic import BaseModel, Field


class RyzykoSamobojcze(str, Enum):
    OBECNE = "OBECNE"
    NIEOBECNE = "NIEOBECNE"


class Klasyfikacja(str, Enum):
    ICD_10 = "ICD-10"
    ICD_11 = "ICD-11"
    DSM_5 = "DSM-5"


class JakoscNagrania(str, Enum):
    DOBRA = "DOBRA"
    SLABA = "SLABA"
    BRAK_MOWY = "BRAK_MOWY"


class ICDCode(BaseModel):
    """Propozycja rozpoznania od modelu — jeszcze niezweryfikowana."""

    klasyfikacja: Klasyfikacja = Field(
        description=(
            "Klasyfikacja, do której należy TEN wpis. Gdy poproszono o kilka klasyfikacji, "
            "podaj to samo rozpoznanie osobnym wpisem dla każdej z nich."
        )
    )
    code: str = Field(
        default="",
        description=(
            "Kod rozpoznania, jeśli jesteś go PEWIEN (np. F41.1 dla ICD-10). "
            "Jeśli nie masz pewności co do kodu, zostaw to pole PUSTE i wypełnij samo "
            "`description` — kod zostanie ustalony automatycznie w oficjalnym rejestrze WHO. "
            "Zgadnięty kod jest gorszy niż jego brak."
        ),
    )
    description: str = Field(
        description="Pełna nazwa rozpoznania po polsku — wypełnij ZAWSZE, to na jej podstawie szukamy kodu."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Twoja pewność co do samego ROZPOZNANIA (nie kodu), 0.0-1.0"
    )


class StanWeryfikacji(str, Enum):
    """Trzy stany, nie dwa — „nie sprawdzano" to co innego niż „sprawdzono i nie ma"."""

    POTWIERDZONY = "POTWIERDZONY"
    NIESPRAWDZANY = "NIESPRAWDZANY"
    NIEPOTWIERDZONY = "NIEPOTWIERDZONY"


class VerifiedICDCode(BaseModel):
    """Rozpoznanie po sprawdzeniu w rejestrze WHO.

    Pola weryfikacyjne wypełnia wyłącznie aplikacja — model nie ma do nich dostępu,
    bo jest osobny schemat wejściowy (`ICDCode`). To celowe: model nie może oświadczyć,
    że jego własna propozycja została potwierdzona.
    """

    klasyfikacja: str = ""
    code: str = ""
    description: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    weryfikacja: StanWeryfikacji = StanWeryfikacji.NIESPRAWDZANY
    # Zachowane dla notatek zapisanych przed wprowadzeniem trzech stanów.
    zweryfikowany: bool = False
    propozycja_ai: str = Field(
        default="", description="Pierwotna nazwa od modelu, gdy różni się od oficjalnej."
    )
    uwaga: str = ""


class _NoteBase(BaseModel):
    jakosc_nagrania: JakoscNagrania = Field(
        description=(
            "Ocena użyteczności nagrania. BRAK_MOWY — w nagraniu nie ma zrozumiałej mowy "
            "(cisza, szum, nagranie uszkodzone lub nierozpoznawalne). SLABA — mowa częściowo "
            "niezrozumiała. DOBRA — mowa zrozumiała. Oceniaj UCZCIWIE: jeśli nie słyszysz "
            "wyraźnie wypowiedzi, wpisz BRAK_MOWY i pozostaw pozostałe pola puste."
        )
    )
    raw_transcript: str = Field(
        description=(
            "Dosłowna transkrypcja tego, co FAKTYCZNIE słychać w nagraniu, po polsku. "
            "Jeśli w nagraniu nie ma zrozumiałej mowy, zostaw to pole PUSTE. "
            "Pod żadnym pozorem nie wymyślaj treści ani nie kopiuj jej z przykładów."
        )
    )
    klasyfikacje: list[Klasyfikacja] = Field(
        default_factory=list,
        description="Klasyfikacje, o które poproszono w poleceniu — wypisz dokładnie te i tylko te.",
    )
    ryzyko_samobojcze: RyzykoSamobojcze = Field(
        description=(
            "Ocena BINARNA myśli/ryzyka samobójczego. OBECNE jeśli w nagraniu pojawiają się "
            "jakiekolwiek treści lub myśli samobójcze; NIEOBECNE jeśli pacjent neguje lub nic "
            "na to nie wskazuje. Zawsze dokładnie jedna z dwóch wartości."
        )
    )
    ryzyko_samobojcze_opis: str = Field(
        default="",
        description="Krótkie (1-2 zdania) uzasadnienie oceny ryzyka samobójczego.",
    )
    status_psychiczny: str = Field(
        description="Opis aktualnego stanu psychicznego pacjenta (świadomość, orientacja, nastrój, afekt, tok myślenia, postrzeganie)."
    )
    objawy: list[str] = Field(
        default_factory=list,
        description="Lista konkretnych objawów zgłoszonych lub zaobserwowanych podczas wizyty.",
    )
    zalecenia_terapeuty: list[str] = Field(
        default_factory=list,
        description=(
            "Zalecenia, które specjalista FAKTYCZNIE wypowiedział podczas wizyty — "
            "wypisz tylko to, co słychać w nagraniu. Nic nie dodawaj od siebie."
        ),
    )
    zalecenia_proponowane: list[str] = Field(
        default_factory=list,
        description=(
            "Twoje własne propozycje zaleceń, których w nagraniu NIE było, a które warto "
            "rozważyć. To sugestie do decyzji specjalisty — nie mieszaj ich z tym, co padło na wizycie."
        ),
    )
    podsumowanie: str = Field(
        description="Krótkie 2-3 zdaniowe podsumowanie wizyty."
    )


class PsychiatricNoteDraft(_NoteBase):
    """Kształt odpowiedzi modelu — kody są jeszcze propozycjami."""

    kody_icd: list[ICDCode] = Field(
        default_factory=list,
        description=(
            "Proponowane rozpoznania w klasyfikacji wskazanej w poleceniu (ICD-10 albo ICD-11). "
            "Podawaj wyłącznie rozpoznania uzasadnione obrazem klinicznym."
        ),
    )


class PsychiatricNote(_NoteBase):
    """Notatka zapisywana i pokazywana lekarzowi — kody po sprawdzeniu w rejestrze WHO."""

    kody_icd: list[VerifiedICDCode] = Field(default_factory=list)
