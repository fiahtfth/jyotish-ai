"""Read-only chart inspection results shared by the dashboard and chat."""
from jhora.horoscope.dhasa.graha import yogini

from .. import moonmode
from . import constants as K, precision, stability, yogas
from .engine import engine

# Parashari special aspects. Rahu/Ketu 5/9 aspects are a minority school
# view, so nodes get only the common 7th aspect here.
_EXTRA_ASPECTS = {"Mars": (4, 8), "Jupiter": (5, 9), "Saturn": (3, 10)}


def active_dashas(birth, when):
    ymd = (when.year, when.month, when.day)
    with precision._frame(birth):
        rows = yogini.get_running_dhasa_for_given_date(
            precision._jd_noon(when), precision._jd_birth(birth), precision._place(birth), dhasa_level_index=2)
    yogini_rows = [{"lords": [K.PLANET_NAMES[planet] for planet in lords],
                    "start": precision._tuple_ymd(start), "end": precision._tuple_ymd(end)}
                   for lords, start, end in rows]
    return {"date": when.isoformat(), "vimshottari": engine.running_vimshottari(birth, ymd),
            "yogini": yogini_rows, "chara": engine.running_chara(birth, ymd), "dasha_year": birth.settings.dasha_year,
            "date_convention": "Calendar dates use the recorded birth UTC offset."}


def vimshottari_mahadashas(facts):
    """Group the saved antardasha rows from the same calculation into mahadashas."""
    periods = []
    for row in facts.get("vimshottari", {}).get("periods", []):
        if periods and periods[-1]["lord"] == row["maha"]:
            periods[-1]["end"] = row["end"]
        else:
            periods.append({"lord": row["maha"], "start": row["start"], "end": row["end"]})
    return periods


def chart_details(facts, birth, when, tzdb_version):
    if birth.birth_time_precision == "unknown":
        return _moon_chart_details(facts, birth, when, tzdb_version)
    aspects = [{"from": name, "to": K.SIGN_NAMES[(p["sign"] + distance - 1) % 12], "distance": distance}
               for name, p in facts["planets"].items() for distance in (7, *_EXTRA_ASPECTS.get(name, ()))]
    return {"settings": {**facts["meta"], "tzdb_version": tzdb_version},
            # retrograde/combust flags travel with each varga so the chart can mark them
            "vargas": moonmode.merged_vargas(facts), "planets": facts["planets"], "lagna": facts["lagna"],
            "houses": facts["houses"], "aspects": aspects, "yogas": yogas.detect(facts),
            "ashtakavarga": {"signs": K.SIGN_NAMES, "planets": list(K.PLANET_NAMES.values())[:7],
                            "sav": facts["sarvastakavarga"], "bav": facts["binnashtakavarga"],
                            "details": facts.get("ashtakavarga")},
            "sensitivity": stability.lagna_windows(birth), "moon_pada": stability.moon_pada_window(birth),
            "dashas": active_dashas(birth, when)}


def _moon_chart_details(facts, birth, when, tzdb_version):
    """Birth time unknown: the Moon chart only; no Lagna, Lagna houses, divisional Lagnas or sensitivity."""
    cf = moonmode.chandra_facts(facts, birth, when)
    aspects = [{"from": name, "to": K.SIGN_NAMES[(p["sign"] + distance - 1) % 12], "distance": distance}
               for name, p in cf["planets"].items() for distance in (7, *_EXTRA_ASPECTS.get(name, ()))]
    return {"settings": {**cf["meta"], "tzdb_version": tzdb_version}, "time_known": False,
            "chandra_lagna": True, "moon_mode": cf["moon_mode"],
            "vargas": cf["vargas"], "planets": cf["planets"], "lagna": cf["lagna"],
            "houses": cf["houses"], "aspects": aspects, "yogas": [],
            "ashtakavarga": {"signs": K.SIGN_NAMES, "planets": list(K.PLANET_NAMES.values())[:7],
                            "sav": cf["sarvastakavarga"], "bav": cf["binnashtakavarga"], "details": None},
            "sensitivity": {}, "moon_pada": None, "dashas": active_dashas(birth, when)}
