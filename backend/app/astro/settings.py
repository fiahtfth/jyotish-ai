"""Calculation settings: the single, explicit description of the engine frame.

Every choice that can move a planet, a sign boundary or a dasha date lives
here, is validated, and is folded into the calc fingerprint. Defaults
reproduce the engine's historical behaviour exactly (SE Lahiri, mean nodes,
true positions, PyJHora's true tropical dasha year, KN Rao Chara dasha).

Other packages (Jaimini, time zones, LLM layer) read these fields by name:
chara_school, karaka_scheme, colord_rule, arudha_exception, combust_table,
gandanta_arc, sandhi_arc. The engine itself acts on ayanamsa, node,
positions, dasha_year, chara_school (running Chara dasha) and d24.

PRESETS are APPROXIMATIONS of what Jagannatha Hora / Drik Panchang
typically use. They MUST be verified against the user's own JH / Drik
install (compare Lahiri ayanamsa, node type and Vimshottari dates for a
known chart) before being advertised as matching either program.
"""
from dataclasses import dataclass, asdict, fields
from typing import Any

AYANAMSAS = ("LAHIRI", "LAHIRI_ICRC", "LAHIRI_1940", "LAHIRI_VP285", "TRUE_CITRA")
NODES = ("mean", "true")
POSITIONS = ("true", "apparent")
CENTERS = ("geocentric", "topocentric")
# true_sidereal = PyJHora's native "true sidereal year" (solar return to the
# same sidereal longitude); sidereal = PyJHora's mean sidereal year constant.
DASHA_YEARS = ("true_tropical", "julian", "gregorian", "sidereal", "savana_360", "true_sidereal")
CHARA_SCHOOLS = ("KNRao", "PVR", "Rath")
KARAKA_SCHEMES = ("7_KNRao", "7or8_PVR", "8_Rath")
COLORD_RULES = ("school", "KNRao", "Rath", "PVR")
ARUDHA_EXCEPTIONS = ("standard", "none")
D24_MODES = ("forward", "reverse")
# "wide_variant" is the secondary-source variant (Jupiter 12°, Saturn 16°;
# other orbs as Surya Siddhanta). Labelled a variant, not a second siddhanta.
COMBUST_TABLES = ("surya_siddhanta", "wide_variant")

# Nominal length of a dasha year in days where the value is a constant.
# true_tropical / true_sidereal vary per birth (computed from the ephemeris);
# the engine reports the actual value in facts["meta"]["dasha_year"]["days"].
DASHA_YEAR_DAYS = {
    "julian": 365.25,
    "gregorian": 365.2425,
    "sidereal": 365.256364,   # PyJHora const.sidereal_year (JH value)
    "savana_360": 360.0,
    "true_tropical": 365.2407,  # nominal; actual value is computed per chart
}

_CHOICES = {
    "ayanamsa": AYANAMSAS, "node": NODES, "positions": POSITIONS,
    "center": CENTERS,
    "dasha_year": DASHA_YEARS, "chara_school": CHARA_SCHOOLS,
    "karaka_scheme": KARAKA_SCHEMES, "colord_rule": COLORD_RULES,
    "arudha_exception": ARUDHA_EXCEPTIONS, "d24": D24_MODES,
    "combust_table": COMBUST_TABLES,
}


@dataclass(frozen=True)
class CalcSettings:
    ayanamsa: str = "LAHIRI"
    node: str = "mean"
    positions: str = "true"
    center: str = "geocentric"
    dasha_year: str = "true_tropical"
    chara_school: str = "KNRao"
    karaka_scheme: str = "7_KNRao"
    colord_rule: str = "school"
    arudha_exception: str = "standard"
    d24: str = "forward"
    combust_table: str = "surya_siddhanta"
    gandanta_arc: float = 10.0 / 3.0   # degrees (one nakshatra pada)
    sandhi_arc: float = 1.5            # degrees from a sign boundary

    def __post_init__(self):
        for name, allowed in _CHOICES.items():
            val = getattr(self, name)
            if val not in allowed:
                raise ValueError(f"Unknown {name} {val!r}; allowed: {', '.join(allowed)}")
        for name in ("gandanta_arc", "sandhi_arc"):
            val = getattr(self, name)
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not 0 < val < 30:
                raise ValueError(f"{name} must be a number of degrees in (0, 30); got {val!r}")

    def fingerprint_dict(self) -> dict:
        """Stable, JSON-serialisable view of every setting (for cache keys/hashes)."""
        d = asdict(self)
        d["gandanta_arc"] = round(float(self.gandanta_arc), 6)
        d["sandhi_arc"] = round(float(self.sandhi_arc), 6)
        return d

    def to_dict(self) -> dict:
        return self.fingerprint_dict()

    @classmethod
    def from_dict(cls, data: dict | None) -> "CalcSettings":
        """Build from a (possibly partial) dict; unknown keys or values raise ValueError."""
        data = dict(data or {})
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown setting(s): {', '.join(unknown)}")
        return cls(**data)

    @classmethod
    def from_preset(cls, name: str) -> "CalcSettings":
        try:
            return PRESETS[name]
        except KeyError:
            raise ValueError(f"Unknown preset {name!r}; allowed: {', '.join(PRESETS)}") from None


DEFAULT = CalcSettings()

PRESETS: dict[str, CalcSettings] = {
    "default": DEFAULT,
    # Drik Panchang style: Lahiri, mean nodes, Julian-year dashas (unverified).
    "drik": CalcSettings(ayanamsa="LAHIRI", node="mean", positions="true",
                         dasha_year="julian"),
    # Jagannatha Hora style: Lahiri, true nodes, true positions, sidereal-year
    # dashas (unverified).
    "jh": CalcSettings(ayanamsa="LAHIRI", node="true", positions="true",
                       dasha_year="sidereal"),
    # IAE / Rashtriya Panchang style: Lahiri-ICRC ayanamsa, mean nodes, and
    # the 360-day savana year used by the ephemeris's own dasha tables
    # (unverified against the printed panchang).
    "iae": CalcSettings(ayanamsa="LAHIRI_ICRC", node="mean", positions="true",
                        dasha_year="savana_360"),
}


def as_settings(value: Any) -> CalcSettings:
    if value is None:
        return DEFAULT
    if isinstance(value, CalcSettings):
        return value
    if isinstance(value, str):
        return CalcSettings.from_preset(value)
    if isinstance(value, dict):
        return CalcSettings.from_dict(value)
    raise ValueError(f"Cannot build CalcSettings from {type(value).__name__}")
