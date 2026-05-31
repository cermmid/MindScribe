from enum import Enum

from pydantic import BaseModel, Field


class RyzykoSamobojcze(str, Enum):
    OBECNE = "OBECNE"
    NIEOBECNE = "NIEOBECNE"


class ICDCode(BaseModel):
    code: str = Field(description="Kod ICD-10, np. F32.1")
    description: str = Field(description="Pełna nazwa rozpoznania")
    confidence: float = Field(ge=0.0, le=1.0, description="Pewność modelu, 0.0-1.0")


class PsychiatricNote(BaseModel):
    raw_transcript: str = Field(
        description="Pełna, dosłowna transkrypcja audio z wizyty po polsku."
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
    kody_icd10: list[ICDCode] = Field(
        default_factory=list,
        description="Proponowane rozpoznania w klasyfikacji ICD-10.",
    )
    zalecenia: list[str] = Field(
        default_factory=list,
        description="Zalecenia farmakologiczne i niefarmakologiczne, dalsze badania, follow-up.",
    )
    podsumowanie: str = Field(
        description="Krótkie 2-3 zdaniowe podsumowanie wizyty."
    )
