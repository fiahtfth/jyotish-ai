"""PDF kundli (reportlab). English only; charts are rendered as house tables."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .astro import constants as K

_HEAD = colors.HexColor("#e8e1d4")


def _table(rows, widths=None):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("BACKGROUND", (0, 0), (-1, 0), _HEAD),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _house_table(facts: dict, varga: str = "D1"):
    chart = facts["vargas"][varga]
    lagna = chart["Lagna"]["sign"]
    rows = [["House", "Sign", "Planets"]]
    for h in range(1, 13):
        s = (lagna + h - 1) % 12
        occ = [n for n, p in chart.items() if n != "Lagna" and p["sign"] == s]
        if h == 1:
            occ = ["Lagna"] + occ
        rows.append([str(h), K.SIGN_NAMES[s], ", ".join(occ) or "-"])
    return _table(rows, [18 * mm, 40 * mm, 110 * mm])


def build_pdf(name: str, facts: dict, views: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm, title=f"Kundli - {name}")
    ss = getSampleStyleSheet()
    h1, h2, small = ss["Title"], ss["Heading3"], ss["BodyText"]
    story = [Paragraph(f"Kundli: {name}", h1),
             Paragraph(f"{facts['meta']['birth_datetime_local']} &middot; {facts['meta']['place']}", small),
             Paragraph(f"Calculation settings: {views['settings_line']}", small), Spacer(1, 6)]

    story.append(Paragraph("Planetary positions", h2))
    rows = [["Planet", "Sign", "Longitude", "House", "Nakshatra", "Lord", "Dignity", "Flags"]]
    for r in views["planets"]:
        rows.append([r["planet"], r["sign"], r["longitude_dms"], str(r["house"]), f"{r['nakshatra']} {r['pada']}",
                     r["nakshatra_lord"], ", ".join(r["dignity"]) or "-", ", ".join(r["flags"]) or "-"])
    story.append(_table(rows))

    known = views.get("time_known", True)
    if known:
        story += [Paragraph("Rasi chart (D1) by house", h2), _house_table(facts, "D1")]
    else:
        story.append(Paragraph("Birth time unknown: Lagna-based charts are omitted; positions are shown by sign only.", small))
    if known and "D9" in facts["vargas"]:
        story += [Paragraph("Navamsa (D9) by house", h2), _house_table(facts, "D9")]
    ch = views.get("chalit")
    if ch:
        story += [Paragraph("Bhava chalit", h2),
                  _table([["Planet", "Rasi house", "Chalit house"]] +
                         [[r["planet"], str(r["rasi_house"]), str(r["chalit_house"])] for r in ch["rows"]])]

    pan = views.get("panchang") or {}
    if "tithi" in pan:
        story += [Paragraph("Birth panchang", h2),
                  Paragraph(f"Tithi {pan['tithi']['paksha']} {pan['tithi']['name']} &middot; {pan['vaara']} &middot; "
                            f"{pan['nakshatra']['name']} pada {pan['nakshatra']['pada']} &middot; "
                            f"Yoga {pan['yoga']['name']} &middot; Karana {pan['karana']['name']}", small)]
    av = views["avakahada"]["items"]
    story += [Paragraph("Avakahada chakra", h2),
              _table([["Varna", "Vashya", "Yoni", "Gana", "Nadi", "Nak. lord", "Rashi lord", "Syllable"],
                      [av["varna"], av["vashya"], av["yoni"], av["gana"], av["nadi"], av["nakshatra_lord"],
                       av["rashi_lord"], av["name_syllable"]]])]

    sb = views.get("shadbala")
    if sb:
        story.append(Paragraph("Shadbala", h2))
        story.append(_table([["Planet", *[c for c in sb["planets"][0]["components"]], "Total", "Rupas", "Min", "Ratio"]] +
                            [[r["planet"], *[f"{v:.0f}" for v in r["components"].values()], f"{r['total_virupas']:.0f}",
                              f"{r['rupas']:.2f}", str(r["required_rupas"]), f"{r['ratio']:.2f}"]
                             for r in sb["planets"]]))

    av_ = views["ashtakavarga"]
    if av_.get("bav") and av_.get("sav"):
        story.append(Paragraph("Ashtakavarga", h2))
        story.append(_table([["", *[s[:3] for s in av_["signs"]]]] +
                            [[pl[:3], *map(str, row)] for pl, row in zip(av_["planets"], av_["bav"])] +
                            [["SAV", *map(str, av_["sav"])]]))

    story.append(Paragraph("Vimshottari dasha (mahadasha and antardasha)", h2))
    vim = views["dasha"]["vimshottari"]
    if isinstance(vim, list):
        story.append(_table([["Mahadasha", "From", "To"]] +
                            [[("* " if m["running"] else "") + m["lord"], m["start"], m["end"]] for m in vim]))
        run = next((m for m in vim if m["running"]), None)
        if run:
            story.append(Paragraph(f"Antardashas of the running {run['lord']} mahadasha", h2))
            story.append(_table([["Antardasha", "From", "To"]] +
                                [[("* " if a["running"] else "") + f"{run['lord']}-{a['lord']}", a["start"], a["end"]]
                                 for a in run["antars"]]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Traditional calculations for reflection; not professional advice. * = running period.",
                           small))
    doc.build(story)
    return buf.getvalue()
