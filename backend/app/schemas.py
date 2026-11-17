import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator
from typing import Literal, Optional


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    needs_birth_profile: bool


class PlaceSearchOut(BaseModel):
    name: str
    state: str
    country: str
    latitude: float
    longitude: float
    label: str


class BirthProfileIn(BaseModel):
    display_name: str = ""
    year: int = Field(ge=1900, le=2030)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    second: int = Field(default=0, ge=0, le=59)
    place_name: str
    place_state: str = ""
    place_country: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    birth_time_precision: Literal["exact", "approximate", "unknown"] = "exact"

    @model_validator(mode="after")
    def _valid_calendar_date(self):
        try:
            datetime.date(self.year, self.month, self.day)
        except ValueError:
            raise ValueError("invalid calendar date")
        return self


class BirthProfileOut(BirthProfileIn):
    timezone_name: str
    utc_offset_hours: float
    calc_fingerprint: str
    calibration_state: str
    predictions_allowed: bool


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    kind: str
    meta: dict
    created_at: str


class ChartOut(BaseModel):
    varga: str
    lagna: dict
    planets: dict
    fingerprint: str
