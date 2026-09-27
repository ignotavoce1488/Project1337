from pydantic import BaseModel, Field, field_validator


class Summary(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=200000)
    key_points: list[str] = Field(default_factory=list, max_length=100)
    title_ru: str | None = Field(None, max_length=500)
    summary_ru: str | None = Field(None, max_length=200000)
    key_points_ru: list[str] | None = Field(None, max_length=100)
    translation_language: str | None = Field(None, pattern=r"^[a-z]{2}$")
    title_translated: str | None = Field(None, max_length=500)
    summary_translated: str | None = Field(None, max_length=200000)
    key_points_translated: list[str] | None = Field(None, max_length=100)


class Lecture(Summary):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    user_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    created_at: str
    transcription: str = Field(max_length=2000000)
    formatted_transcription: str | None = Field(None, max_length=2000000)
    transcription_translated: str | None = Field(None, max_length=2000000)
    transcription_translation_language: str | None = Field(None, pattern=r"^[a-z]{2}$")
    language: str = Field(default="ru", pattern=r"^(auto|[a-z]{2})$")
    audio_url: str | None = None

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_user_id(cls, value):
        if isinstance(value, bool):
            raise ValueError("Invalid owner")
        return str(value)
