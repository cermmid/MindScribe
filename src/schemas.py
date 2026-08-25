from enum import Enum

from pydantic import BaseModel, Field


class RyzykoSamobojcze(str, Enum):
    OBECNE = "OBECNE"
    NIEOBECNE = "NIEOBECNE"


class Klasyfikacja(str, Enum):
    ICD_10 = "ICD-10"
    ICD_11 = "ICD-11"


class JakoscNagrania(str, Enum):
    DOBRA = "DOBRA"
    SLABA = "SLABA"
    BRAK_MOWY = "BRAK_MOWY"


class ICDCode(BaseModel):
    code: str = Field(description="Kod rozpoznania, np. F32.1 (ICD-10) albo 6A70.1 (ICD-11)")
    description: str = Field(description="Pełna nazwa rozpoznania")
    confidence: float = Field(ge=0.0, le=1.0, description="Pewność modelu, 0.0-1.0")


class PsychiatricNote(BaseModel):
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
    klasyfikacja: Klasyfikacja = Field(
        description="Klasyfikacja rozpoznań użyta w polu kody_icd — dokładnie ta, o którą poproszono w poleceniu."
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
    kody_icd: list[ICDCode] = Field(
        default_factory=list,
        description=(
            "Proponowane rozpoznania w klasyfikacji wskazanej w poleceniu (ICD-10 albo ICD-11). "
            "Używaj kodów TEJ klasyfikacji, o którą poproszono — nie mieszaj obu."
        ),
    )
    zalecenia: list[str] = Field(
        default_factory=list,
        description="Zalecenia farmakologiczne i niefarmakologiczne, dalsze badania, follow-up.",
    )
    podsumowanie: str = Field(
        description="Krótkie 2-3 zdaniowe podsumowanie wizyty."
    )
