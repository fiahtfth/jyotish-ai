import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator
from typing import Literal, Optional

from .astro.settings import PRESETS


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = ""
    # External AI is included in the service terms, not a separate option.
    terms_accepted: Literal[True]


class TermsIn(BaseModel):
    terms_accepted: Literal[True]


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
    # how the clock time maps to UTC: tz database ("zone"), local mean time, or typed-in offset
    time_basis: Literal["zone", "lmt", "manual"] = "zone"
    utc_offset_manual: Optional[float] = Field(default=None, ge=-14, le=14)
    dst_fold: Optional[Literal[0, 1]] = None    # which occurrence of a repeated local time
    calc_preset: str = "default"

    @model_validator(mode="after")
    def _valid_calendar_date(self):
        try:
            datetime.date(self.year, self.month, self.day)
        except ValueError:
            raise ValueError("invalid calendar date")
        if self.calc_preset not in PRESETS:
            raise ValueError(f"calc_preset must be one of: {', '.join(PRESETS)}")
        if self.time_basis == "manual" and self.utc_offset_manual is None:
            raise ValueError("utc_offset_manual is required when time_basis is 'manual'")
        return self


class BirthProfileOut(BirthProfileIn):
    id: int
    relation: Relation
    is_active: bool = True
    timezone_name: str
    utc_offset_hours: float
    offset_source: str = ""
    tz_warnings: list[str] = []
    tzdb_version: str = ""
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


class DegreeTableIn(BaseModel):
    """Mode B: a pasted planet-degree table from another program."""
    text: str = Field(min_length=3, max_length=4000)
    source_program: str = Field(min_length=2, max_length=40)
    ayanamsa_id: str = "LAHIRI"


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


class PredictionOutcomeIn(BaseModel):
    outcome: Literal["happened", "partly", "did_not", "unsure", "outside_window"]
    event_date: Optional[datetime.date] = None
