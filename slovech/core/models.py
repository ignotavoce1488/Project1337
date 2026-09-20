from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Summary(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=200000)
    key_points: list[str] = Field(default_factory=list, max_length=100)
    title_ru: str | None = Field(None, max_length=500)
    summary_ru: str | None = Field(None, max_length=200000)
    key_points_ru: list[str] | None = Field(None, max_length=100)


class Lecture(Summary):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    user_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    created_at: str
    transcription: str = Field(max_length=2000000)
    language: Literal["ru", "en"] = "ru"
    audio_url: str | None = None

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_user_id(cls, value):
        if isinstance(value, bool):
            raise ValueError("Invalid owner")
        return str(value)
