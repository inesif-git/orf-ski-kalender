
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

WIEN = ZoneInfo("Europe/Vienna")
JETZT = datetime.now(timezone.utc)

FIS_URL = (
    "https://www.fis-ski.com/DB/services/public/"
    "icalendar-feed-fis-events.html?"
    "seasoncode=2027&sectorcode=AL&categorycode=WC"
)

KALENDER = Path("ski-weltcup.ics")
STARTZEITEN = Path("rennstarts.json")

SENDER = {
    "ORF 1": "438442",
    "ORF SPORT+": "76756",
}

# Alpine Ski-WM Crans-Montana 2027
WM_PLAN = [
    ("2027-02-01", "Team-Parallel Mixed", "Mixed", ["11:15"]),
    ("2027-02-04", "Super-G", "Damen", ["11:15"]),
    ("2027-02-05", "Super-G", "Herren", ["11:15"]),
    ("2027-02-06", "Abfahrt", "Damen", ["11:15"]),
    ("2027-02-07", "Abfahrt", "Herren", ["11:15"]),
    ("2027-02-09", "Team-Kombination", "Damen", ["10:00", "13:30"]),
    ("2027-02-10", "Team-Kombination", "Herren", ["10:00", "13:30"]),
    ("2027-02-11", "Riesentorlauf", "Damen", ["10:00", "13:30"]),
    ("2027-02-12", "Riesentorlauf", "Herren", ["10:00", "13:30"]),
    ("2027-02-13", "Slalom", "Damen", ["10:00", "13:30"]),
    ("2027-02-14", "Slalom", "Herren", ["10:00", "13:30"]),
]

# Bestätigte ORF-Countdown-Zeiten für Sölden
SOELDEN_ORF = {
    ("2026-10-24", "Damen", 1): "09:30",
    ("2026-10-24", "Damen", 2): "12:45",
    ("2026-10-25", "Herren", 1): "09:25",
    ("2026-10-25", "Herren", 2): "12:35",
}


def laden(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as antwort:
        return antwort.read().decode(
            "utf-8-sig", errors="replace"
        )


def entfalten(text):
    zeilen = []
    for zeile in text.replace("\r\n", "\n").split("\n"):
        if zeile.startswith((" ", "\t")) and zeilen:
            zeilen[-1] += zeile[1:]
        else:
            zeilen.append(zeile)
    return zeilen


def bereinigen(text):
    return (
        str(text)
        .replace("\\n", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .strip()
    )


def disziplin(text):
    text = text.lower()

    if re.search(
        r"team[- ]?kombination|team combined", text
    ):
        return "Team-Kombination"

    if re.search(
        r"team[- ]?parallel|mixed team|team event", text
    ):
        return "Team-Parallel Mixed"

    if any(x in text for x in (
        "giant slalom",
        "riesentorlauf",
        "riesenslalom",
    )):
        return "Riesentorlauf"

    if "super-g" in text or "super g" in text:
        return "Super-G"

    if "downhill" in text or "abfahrt" in text:
        return "Abfahrt"

    if re.search(r"\bslalom\b", text):
        return "Slalom"

    return None


def zeit_lesen(wert, datum):
    if not wert:
        return None

    wert = str(wert).strip()

    if re.fullmatch(r"\d{1,2}:\d{2}", wert):
        h, m = map(int, wert.split(":"))

        if h > 23 or m > 59:
            return None

        return (
            datetime.fromisoformat(datum)
            .replace(hour=h, minute=m, tzinfo=WIEN)
            .astimezone(timezone.utc)
        )

    try:
        zeit = datetime.fromisoformat(
            wert.replace("Z", "+00:00")
        )
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=WIEN)
        return zeit.astimezone(timezone.utc)
    except ValueError:
        return None


def fis_datum(feld, wert):
    wert = wert.strip()

    if (
        "VALUE=DATE" in feld
        or re.fullmatch(r"\d{8}", wert)
    ):
        return (
            datetime.strptime(
                wert[:8], "%Y%m%d"
            ).date(),
            None,
        )

    try:
        if wert.endswith("Z"):
            zeit = datetime.strptime(
                wert, "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc)
        else:
            zeit = datetime.strptime(
                wert[:15], "%Y%m%dT%H%M%S"
            ).replace(tzinfo=WIEN)

        return (
            zeit.astimezone(WIEN).date(),
            zeit.astimezone(timezone.utc),
        )
    except ValueError:
        return None, None


def fis_rennen():
    inhalt = laden(FIS_URL)

    if "BEGIN:VCALENDAR" not in inhalt:
        raise RuntimeError(
            "FIS-Kalender nicht lesbar. "
            "Alte Kalenderdatei bleibt erhalten."
        )

    bloecke = []
    block = None

    for zeile in entfalten(inhalt):
        if zeile == "BEGIN:VEVENT":
            block = {}

        elif zeile == "END:VEVENT":
            if block is not None:
                bloecke.append(block)
            block = None

        elif block is not None and ":" in zeile:
            feld, wert = zeile.split(":", 1)

            if feld.startswith("DTSTART"):
                block["startfeld"] = feld
                block["startwert"] = wert

            elif feld == "SUMMARY":
                block["titel"] = bereinigen(wert)

            elif feld == "DESCRIPTION":
                block["beschreibung"] = bereinigen(wert)

    rennen = []

    for e in bloecke:
        datum, fis_zeit = fis_datum(
            e.get("startfeld", ""),
            e.get("startwert", ""),
        )

        if datum is None:
            continue

        titel = e.get("titel", "")
        beschreibung = e.get("beschreibung", "")

        if re.search(
            r"Gender:\s*Women\b",
            beschreibung,
            re.I,
        ):
            geschlecht = "Damen"

        elif re.search(
            r"Gender:\s*Men\b",
            beschreibung,
            re.I,
        ):
            geschlecht = "Herren"

        else:
            continue

        art = disziplin(titel + " " + beschreibung)

        if not art:
            continue

        ort = re.split(
            r"\s+[-–]\s+", titel
        )[0].strip()

        rennen.append({
            "datum": datum.isoformat(),
            "ort": ort,
            "disziplin": art,
            "geschlecht": geschlecht,
            "fis_zeit": fis_zeit,
            "rennstarts": [],
            "sendungen": [],
            "wm": False,
        })

    if not rennen:
        raise RuntimeError(
            "Keine FIS-Rennen gefunden. "
            "Alte Datei bleibt erhalten."
        )

    return rennen


def startzeiten_ergaenzen(rennen):
    if not STARTZEITEN.exists():
        return

    daten = json.loads(
        STARTZEITEN.read_text(encoding="utf-8")
    )

    for r in rennen:
        zusatz = daten.get(r["datum"], {})

        if not isinstance(zusatz, dict):
            continue

        if (
            zusatz.get("geschlecht") != r["geschlecht"]
            or zusatz.get("disziplin") != r["disziplin"]
        ):
            continue

        for key in (
            "erster_lauf",
            "zweiter_lauf",
            "start",
            "startzeit",
        ):
            zeit = zeit_lesen(
                zusatz.get(key), r["datum"]
            )

            if zeit and zeit not in r["rennstarts"]:
                r["rennstarts"].append(zeit)

        r["rennstarts"].sort()


def wm_ergaenzen(rennen):
    for datum, art, geschlecht, starts in WM_PLAN:
        rennen.append({
            "datum": datum,
            "ort": "Crans-Montana",
            "disziplin": art,
            "geschlecht": geschlecht,
            "fis_zeit": None,
            "rennstarts": [
                zeit_lesen(z, datum)
                for z in starts
            ],
            "sendungen": [],
            "wm": True,
        })


def programmzeit(wert):
    try:
        zeit = datetime.fromisoformat(
            str(wert).replace("Z", "+00:00")
        )

        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)

        return zeit.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def ist_ski(titel):
    return bool(re.search(
        r"ski|riesentorlauf|riesenslalom|"
        r"slalom|abfahrt|super[- ]?g",
        titel,
        re.I,
    ))


def ist_live(titel, beschreibung):
    text = titel + " " + beschreibung

    if re.search(
        r"wiederholung|highlights?|"
        r"zusammenfassung|rückblick|"
        r"replay|analyse",
        text,
        re.I,
    ):
        return False

    return bool(re.search(
        r"live|direkt|countdown|"
        r"\b[12]\.?\s*(?:durchgang|lauf)",
        text,
        re.I,
    ))


def durchgang_erkennen(text):
    if re.search(
        r"\b(?:1\.|erster|erste)\s*"
        r"(?:durchgang|lauf)",
        text,
        re.I,
    ):
        return 1

    if re.search(
        r"\b(?:2\.|zweiter|zweite)\s*"
        r"(?:durchgang|lauf)",
        text,
        re.I,
    ):
        return 2

    return None


def zuordnen(titel, beschreibung, datum, rennen):
    text = titel + " " + beschreibung

    kandidaten = [
        r for r in rennen
        if r["datum"] == datum
    ]

    damen = bool(re.search(
        r"\b(?:damen|frauen|women|ladies)\b",
        text,
        re.I,
    ))

    herren = bool(re.search(
        r"\b(?:herren|männer|maenner|men)\b",
        text,
        re.I,
    ))

    if damen and herren:
        return None

    if damen:
        kandidaten = [
            r for r in kandidaten
            if r["geschlecht"] == "Damen"
        ]

    if herren:
        kandidaten = [
            r for r in kandidaten
            if r["geschlecht"] == "Herren"
        ]

    art = disziplin(text)

    if art:
        kandidaten = [
            r for r in kandidaten
            if r["disziplin"] == art
        ]

    mit_ort = [
        r for r in kandidaten
        if r["ort"].lower() in text.lower()
    ]

    if mit_ort:
        kandidaten = mit_ort

    if re.search(
        r"\b(?:weltmeisterschaft|"
        r"ski[- ]?wm|crans[- ]?montana)\b",
        text,
        re.I,
    ):
        kandidaten = [
            r for r in kandidaten if r["wm"]
        ]

    elif re.search(r"\bweltcup\b", text, re.I):
        kandidaten = [
            r for r in kandidaten if not r["wm"]
        ]

    return (
        kandidaten[0]
        if len(kandidaten) == 1
        else None
    )


def sendung_hinzufuegen(
    renn, beginn, ende, sender, titel, lauf=None
):
    if ende <= beginn:
        return

    renn["sendungen"].append({
        "beginn": beginn,
        "ende": ende,
        "sender": sender,
        "titel": titel,
        "durchgang": (
            lauf
            if lauf is not None
            else durchgang_erkennen(titel)
        ),
    })


def epg_ergaenzen(rennen):
    for sender, nummer in SENDER.items():
        try:
            daten = json.loads(laden(
                "https://epg.pw/api/epg.json?"
                "channel_id=" + nummer
            ))

            liste = daten.get("epg_list")

            if not isinstance(liste, list):
                raise ValueError("Programmliste fehlt")

            programm = []

            for s in liste:
                beginn = programmzeit(
                    s.get("start_date")
                )

                if beginn:
                    programm.append((beginn, s))

            programm.sort(key=lambda x: x[0])
            treffer = 0

            for i, (beginn, s) in enumerate(
                programm[:-1]
            ):
                titel = str(s.get("title") or "")
                beschreibung = str(
                    s.get("desc") or ""
                )

                if (
                    not ist_ski(titel)
                    or not ist_live(
                        titel, beschreibung
                    )
                ):
                    continue

                datum = (
                    beginn.astimezone(WIEN)
                    .date().isoformat()
                )

                renn = zuordnen(
                    titel,
                    beschreibung,
                    datum,
                    rennen,
                )

                if renn is None:
                    continue

                sendung_hinzufuegen(
                    renn,
                    beginn,
                    programm[i + 1][0],
                    sender,
                    titel,
                )

                treffer += 1

            print(
                sender,
                "- EPG-Treffer:",
                treffer,
            )

        except Exception as fehler:
            print(
                "EPG momentan nicht verfügbar:",
                sender,
                fehler,
            )


class TextLeser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.teile = []
        self.versteckt = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.versteckt += 1

        if tag in (
            "p", "li", "div", "tr",
            "br", "h2", "h3",
        ):
            self.teile.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.versteckt:
            self.versteckt -= 1

        if tag in (
            "p", "li", "div", "tr",
            "br", "h2", "h3",
        ):
            self.teile.append("\n")

    def handle_data(self, data):
        if not self.versteckt:
            self.teile.append(data)


def offizieller_orf_ergaenzen(rennen):
    # Zusätzlicher Versuch, den offiziellen
    # ORF-Sport-Sendeplan auszulesen.
    # Nur eindeutig zuordenbare Sendungen.
    try:
        leser = TextLeser()

        leser.feed(laden(
            "https://sport.orf.at/"
        ))

        text = " ".join(
            "".join(leser.teile).split()
        )

        tage = re.split(
            r"(?=(?:Montag|Dienstag|Mittwoch|"
            r"Donnerstag|Freitag|Samstag|Sonntag),"
            r"\s+\d{1,2}\.\s+\w+)",
            text,
        )

        monate = {
            "jänner": 1,
            "januar": 1,
            "februar": 2,
            "märz": 3,
            "maerz": 3,
            "april": 4,
            "mai": 5,
            "juni": 6,
            "juli": 7,
            "august": 8,
            "september": 9,
            "oktober": 10,
            "november": 11,
            "dezember": 12,
        }

        treffer = 0

        for teil in tage:
            kopf = re.match(
                r"(?:Montag|Dienstag|Mittwoch|"
                r"Donnerstag|Freitag|Samstag|"
                r"Sonntag),\s+(\d{1,2})\.\s+(\w+)",
                teil,
            )

            if not kopf:
                continue

            monat = monate.get(
                kopf.group(2).lower()
            )

            if not monat:
                continue

            tag = int(kopf.group(1))

            moegliche = [
                r for r in rennen
                if (
                    int(r["datum"][5:7]) == monat
                    and int(r["datum"][8:10]) == tag
                )
            ]

            if not moegliche:
                continue

            muster = (
                r"(\d{1,2})[.:](\d{2})\s*Uhr"
                r"\s*\|?\s*Ski\s*alpin"
                r"\s*\|?\s*(.{0,160}?)"
                r"\s*\|\s*"
                r"(ORF\s*1|ORF1|OSP|"
                r"ORF\s*Sport\s*\+)"
            )

            for match in re.finditer(
                muster, teil, re.I
            ):
                inhalt = match.group(3)
                sender = match.group(4)

                lauf = durchgang_erkennen(inhalt)

                if lauf is None:
                    continue

                kandidaten = [
                    r for r in moegliche
                    if r is zuordnen(
                        inhalt,
                        "",
                        r["datum"],
                        rennen,
                    )
                ]

                if len(kandidaten) != 1:
                    continue

                r = kandidaten[0]

                beginn = zeit_lesen(
                    match.group(1)
                    + ":"
                    + match.group(2),
                    r["datum"],
                )

                if not beginn:
                    continue

                sender = (
                    "ORF 1"
                    if "1" in sender
                    else "ORF SPORT+"
                )

                sendung_hinzufuegen(
                    r,
                    beginn,
                    beginn + timedelta(minutes=90),
                    sender,
                    "Offizieller ORF-Sport-Sendeplan",
                    lauf,
                )

                treffer += 1

        print(
            "Offizieller ORF-Sport-Sendeplan:",
            treffer,
        )

    except Exception as fehler:
        print(
            "Offizieller ORF-Sport-Sendeplan "
            "momentan nicht lesbar:",
            fehler,
        )


def soelden_absichern(rennen):
    treffer = 0

    for r in rennen:
        if (
            r["ort"].lower() != "sölden"
            or r["disziplin"] != "Riesentorlauf"
        ):
            continue

        for lauf in (1, 2):
            uhr = SOELDEN_ORF.get((
                r["datum"],
                r["geschlecht"],
                lauf,
            ))

            if not uhr:
                continue

            beginn = zeit_lesen(
                uhr, r["datum"]
            )

            sendung_hinzufuegen(
                r,
                beginn,
                beginn + timedelta(minutes=90),
                "ORF 1",
                "ORF Countdown (bestätigt)",
                lauf,
            )

            treffer += 1

    print(
        "Sölden-ORF-Zeiten abgesichert:",
        treffer,
    )


def ics_text(wert):
    return (
        str(wert)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def utc_format(zeit):
    return (
        zeit.astimezone(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )


def zeilen_falten(zeilen):
    ergebnis = []

    for zeile in zeilen:
        teil = ""

        for zeichen in zeile:
            if len(
                (teil + zeichen).encode("utf-8")
            ) > 70:
                ergebnis.append(teil)
                teil = " "

            teil += zeichen

        ergebnis.append(teil)

    return ergebnis


def uid_fuer_rennen(r, nummer):
    if r["wm"]:
        identitaet = "|".join((
            "WM2027",
            r["datum"],
            r["geschlecht"],
            r["disziplin"],
        ))
    else:
        # Bestehende Weltcup-UIDs beibehalten
        identitaet = "|".join((
            r["datum"],
            r["geschlecht"],
            r["disziplin"],
            r["ort"],
            str(nummer),
        ))

    return (
        hashlib.sha256(
            identitaet.encode("utf-8")
        ).hexdigest()[:24]
        + "@orf-ski-kalender"
    )


def rennlaeufe(r):
    starts = sorted(set(
        x for x in r["rennstarts"] if x
    ))

    if not starts and r["fis_zeit"]:
        starts = [r["fis_zeit"]]

    if r["disziplin"] in (
        "Slalom",
        "Riesentorlauf",
        "Team-Kombination",
    ):
        if len(starts) >= 2:
            return [
                {"nummer": 1, "start": starts[0]},
                {"nummer": 2, "start": starts[1]},
            ]

        return [{
            "nummer": 1,
            "start": starts[0] if starts else None,
        }]

    return [{
        "nummer": None,
        "start": starts[0] if starts else None,
    }]


def sendungen_aufteilen(r, laeufe):
    zuordnung = {
        lauf["nummer"]: []
        for lauf in laeufe
    }

    for s in r["sendungen"]:
        nummer = s["durchgang"]

        if nummer in zuordnung:
            zuordnung[nummer].append(s)
            continue

        if len(laeufe) == 1:
            zuordnung[
                laeufe[0]["nummer"]
            ].append(s)
            continue

        kandidaten = []

        for lauf in laeufe:
            if lauf["start"] is None:
                continue

            abstand = (
                lauf["start"] - s["beginn"]
            ).total_seconds() / 60

            if -30 <= abstand <= 90:
                kandidaten.append((
                    abs(abstand),
                    lauf["nummer"],
                ))

        kandidaten.sort()

        if kandidaten and (
            len(kandidaten) == 1
            or kandidaten[0][0]
            != kandidaten[1][0]
        ):
            zuordnung[
                kandidaten[0][1]
            ].append(s)

    return zuordnung


def kalender_schreiben(rennen):
    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ORF Ski Kalender//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:ORF Ski-Weltcup LIVE",
    ]

    statistik = {
        "ORF": 0,
        "Rennstart": 0,
        "Ganztag": 0,
        "WM-Einträge": 0,
    }

    for nummer, r in enumerate(rennen):
        datum = datetime.fromisoformat(
            r["datum"]
        ).date()

        basis_uid = uid_fuer_rennen(
            r, nummer
        )

        laeufe = rennlaeufe(r)

        sendungen = sendungen_aufteilen(
            r, laeufe
        )

        for lauf in laeufe:
            laufnummer = lauf["nummer"]
            start = lauf["start"]

            if laufnummer == 2:
                uid = basis_uid.replace(
                    "@orf-ski-kalender",
                    "-lauf2@orf-ski-kalender",
                )
            else:
                uid = basis_uid

            titel = (
                "🏆 Ski-WM 2027 – "
                if r["wm"]
                else "🎿 " + r["ort"] + " – "
            )

            titel += (
                r["disziplin"]
                + " "
                + r["geschlecht"]
            )

            if laufnummer is not None:
                if (
                    r["disziplin"]
                    == "Team-Kombination"
                ):
                    titel += (
                        " | Abfahrt"
                        if laufnummer == 1
                        else " | Slalom"
                    )
                else:
                    titel += (
                        " | "
                        + str(laufnummer)
                        + ". Durchgang"
                    )

            beschreibung = (
                "Alpine Ski-WM Crans-Montana 2027."
                if r["wm"]
                else "FIS Ski-Weltcup 2026/27."
            )

            if start:
                beschreibung += (
                    "\nOffizieller Rennstart: "
                    + start.astimezone(WIEN)
                    .strftime("%H:%M")
                    + " Uhr"
                )

            passende = sendungen.get(
                laufnummer, []
            )

            if passende:
                beginn = min(
                    s["beginn"] for s in passende
                )

                ende = max(
                    s["ende"] for s in passende
                )

                sender = ", ".join(sorted({
                    s["sender"] for s in passende
                }))

                titel += " | ORF LIVE"

                beschreibung += (
                    "\nORF-Sendebeginn: "
                    + beginn.astimezone(WIEN)
                    .strftime("%H:%M")
                    + " Uhr\nSender: "
                    + sender
                )

                zeitzeilen = [
                    "DTSTART:" + utc_format(beginn),
                    "DTEND:" + utc_format(ende),
                ]

                statistik["ORF"] += 1

            elif start:
                titel += (
                    " | Start "
                    + start.astimezone(WIEN)
                    .strftime("%H:%M")
                    + " Uhr"
                )

                beschreibung += (
                    "\nORF-Sendezeit noch nicht "
                    "erkannt. Dauer vorläufig."
                )

                zeitzeilen = [
                    "DTSTART:" + utc_format(start),
                    "DTEND:" + utc_format(
                        start + timedelta(minutes=90)
                    ),
                ]

                statistik["Rennstart"] += 1

            else:
                titel += " | vorläufig"

                beschreibung += (
                    "\nNoch keine bestätigte "
                    "Startzeit."
                )

                zeitzeilen = [
                    "DTSTART;VALUE=DATE:"
                    + datum.strftime("%Y%m%d"),
                    "DTEND;VALUE=DATE:"
                    + (
                        datum + timedelta(days=1)
                    ).strftime("%Y%m%d"),
                ]

                statistik["Ganztag"] += 1

            if r["wm"]:
                statistik["WM-Einträge"] += 1

            zeilen.extend([
                "BEGIN:VEVENT",
                "UID:" + uid,
                "DTSTAMP:" + utc_format(JETZT),
                *zeitzeilen,
                "SUMMARY:" + ics_text(titel),
                "DESCRIPTION:" + ics_text(
                    beschreibung
                ),
                "END:VEVENT",
            ])

    zeilen.append("END:VCALENDAR")

    inhalt = (
        "\r\n".join(
            zeilen_falten(zeilen)
        )
        + "\r\n"
    )

    KALENDER.write_bytes(
        inhalt.encode("utf-8")
    )

    gesamt = (
        statistik["ORF"]
        + statistik["Rennstart"]
        + statistik["Ganztag"]
    )

    print("Kalendereinträge:", gesamt)

    for name, anzahl in statistik.items():
        print(name + ":", anzahl)

    print("FERTIG")


if __name__ == "__main__":
    print(
        "Erstelle Weltcup- und "
        "Ski-WM-Kalender 2026/27"
    )

    rennen = fis_rennen()

    print(
        "FIS-Weltcuprennen gefunden:",
        len(rennen),
    )

    startzeiten_ergaenzen(rennen)
    wm_ergaenzen(rennen)
    epg_ergaenzen(rennen)
    offizieller_orf_ergaenzen(rennen)
    soelden_absichern(rennen)
    kalender_schreiben(rennen)
