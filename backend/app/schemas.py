import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator
from typing import Literal, Optional


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = ""
    # opt-in to third-party AI providers; without it replies come from the
    # built-in offline responder and no chart data leaves the server
    llm_consent: bool = False


class ConsentIn(BaseModel):
    llm_consent: bool


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


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


Relation = Literal["self", "spouse", "mother", "father", "son", "daughter",
                   "brother", "sister", "friend", "other"]
MAX_PROFILES = 10


class BirthProfileIn(BaseModel):
    display_name: str = ""
    # omitted -> unchanged on edit, "self" when a profile is first created
    relation: Optional[Relation] = None
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
    id: int
    relation: Relation
    is_active: bool = True
    timezone_name: str
    utc_offset_hours: float
    calc_fingerprint: str
    calibration_state: str
    predictions_allowed: bool


class ProfileListItem(BaseModel):
    id: int
    display_name: str
    relation: Relation
    calibration_state: str
    predictions_allowed: bool
    is_active: bool


class FeedbackIn(BaseModel):
    rating: Literal[-1, 0, 1]          # 0 clears the vote
    comment: str = Field(default="", max_length=500)


class ReportIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    page: str = Field(default="", max_length=200)
    app_version: str = Field(default="", max_length=50)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    kind: str
    meta: dict
    created_at: str
    rating: int = 0                    # the caller's own thumbs vote (+1/-1), 0 = none


class ChartOut(BaseModel):
    varga: str
    lagna: dict
    planets: dict
    fingerprint: str
