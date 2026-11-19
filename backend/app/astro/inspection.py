"""Read-only chart inspection results shared by the dashboard and chat."""
from jhora.horoscope.dhasa.graha import yogini

from . import constants as K, precision, stability, yogas
from .engine import engine

_EXTRA_ASPECTS = {"Mars": (4, 8), "Jupiter": (5, 9), "Saturn": (3, 10),
                  "Rahu": (5, 9), "Ketu": (5, 9)}


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


def chart_details(facts, birth, when, tzdb_version):
    aspects = [{"from": name, "to": K.SIGN_NAMES[(p["sign"] + distance - 1) % 12], "distance": distance}
               for name, p in facts["planets"].items() for distance in (7, *_EXTRA_ASPECTS.get(name, ()))]
    return {"settings": {**facts["meta"], "tzdb_version": tzdb_version},
            "vargas": facts["vargas"], "planets": facts["planets"], "lagna": facts["lagna"],
            "houses": facts["houses"], "aspects": aspects, "yogas": yogas.detect(facts),
            "ashtakavarga": {"signs": K.SIGN_NAMES, "planets": list(K.PLANET_NAMES.values())[:7],
                            "sav": facts["sarvastakavarga"], "bav": facts["binnashtakavarga"],
                            "details": facts.get("ashtakavarga")},
            "sensitivity": stability.lagna_windows(birth), "moon_pada": stability.moon_pada_window(birth),
            "dashas": active_dashas(birth, when)}
