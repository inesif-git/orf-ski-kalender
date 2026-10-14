
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WIEN = ZoneInfo("Europe/Vienna")
JETZT = datetime.now(timezone.utc)

FIS_URL = (
    "https://www.fis-ski.com/DB/services/public/"
    "icalendar-feed-fis-events.html?"
    "seasoncode=2027&sectorcode=AL&categorycode=WC"
)

SENDER = {
    "ORF 1": "438442",
    "ORF SPORT+": "76756",
}

KALENDER = Path("ski-weltcup.ics")
STARTZEITEN = Path("rennstarts.json")


def laden(url):
    anfrage = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(anfrage, timeout=30) as antwort:
        return antwort.read().decode(
            "utf-8-sig", errors="replace"
        )


def entfalten(text):
    ergebnis = []
    for zeile in text.replace("\r\n", "\n").split("\n"):
        if zeile.startswith((" ", "\t")) and ergebnis:
            ergebnis[-1] += zeile[1:]
        else:
            ergebnis.append(zeile)
    return ergebnis


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

    if any(w in text for w in (
        "giant slalom", "riesentorlauf", "riesenslalom"
    )):
        return "Riesentorlauf"

    if "super-g" in text or "super g" in text:
        return "Super-G"

    if "downhill" in text or "abfahrt" in text:
        return "Abfahrt"

    if re.search(r"\bslalom\b", text):
        return "Slalom"

    return None


def fis_datum_und_zeit(feld, wert):
    wert = wert.strip()

    if "VALUE=DATE" in feld or re.fullmatch(r"\d{8}", wert):
        datum = datetime.strptime(wert[:8], "%Y%m%d").date()
        return datum, None

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
            zeit.astimezone(timezone.utc)
        )
    except ValueError:
        return None, None


def fis_rennen():
    inhalt = laden(FIS_URL)

    if "BEGIN:VCALENDAR" not in inhalt:
        raise RuntimeError("FIS-Kalender nicht lesbar")

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

    for eintrag in bloecke:
        datum, fis_zeit = fis_datum_und_zeit(
            eintrag.get("startfeld", ""),
            eintrag.get("startwert", "")
        )

        if datum is None:
            continue

        titel = eintrag.get("titel", "")
        beschreibung = eintrag.get("beschreibung", "")
        text = titel + " " + beschreibung

        if re.search(r"Gender:\s*Women\b", beschreibung, re.I):
            geschlecht = "Damen"

        elif re.search(r"Gender:\s*Men\b", beschreibung, re.I):
            geschlecht = "Herren"

        else:
            continue

        art = disziplin(text)

        if not art:
            continue

        ort = re.split(r"\s+[-–]\s+", titel)[0].strip()

        rennen.append({
            "datum": datum.isoformat(),
            "ort": ort,
            "disziplin": art,
            "geschlecht": geschlecht,
            "fis_zeit": fis_zeit,
            "rennstarts": [],
            "sendungen": [],
        })

    if not rennen:
        raise RuntimeError(
            "Keine FIS-Rennen gefunden. "
            "Bestehender Kalender bleibt erhalten."
        )

    return rennen


def uhrzeit_lesen(wert, datum):
    if not wert:
        return None

    wert = str(wert).strip()

    if re.fullmatch(r"\d{1,2}:\d{2}", wert):
        stunde, minute = map(int, wert.split(":"))

        if stunde > 23 or minute > 59:
            return None

        return datetime.fromisoformat(datum).replace(
            hour=stunde,
            minute=minute,
            tzinfo=WIEN
        ).astimezone(timezone.utc)

    try:
        zeit = datetime.fromisoformat(
            wert.replace("Z", "+00:00")
        )

        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=WIEN)

        return zeit.astimezone(timezone.utc)

    except ValueError:
        return None


def startzeiten_ergaenzen(rennen):
    if not STARTZEITEN.exists():
        return

    daten = json.loads(
        STARTZEITEN.read_text(encoding="utf-8")
    )

    for renn in rennen:
        zusatz = daten.get(renn["datum"], {})

        if not isinstance(zusatz, dict):
            continue

        if (
            zusatz.get("geschlecht") != renn["geschlecht"]
            or zusatz.get("disziplin") != renn["disziplin"]
        ):
            continue

        for schluessel in (
            "erster_lauf",
            "zweiter_lauf",
            "start",
            "startzeit",
        ):
            zeit = uhrzeit_lesen(
                zusatz.get(schluessel),
                renn["datum"]
            )

            if zeit and zeit not in renn["rennstarts"]:
                renn["rennstarts"].append(zeit)

        renn["rennstarts"].sort()


def programmzeit(wert):
    try:
        zeit = datetime.fromisoformat(
            str(wert).replace("Z", "+00:00")
        )

        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)

        return zeit.astimezone(timezone.utc)

    except (TypeError, ValueError):
        return None


def ist_ski(titel):
    return bool(re.search(
        r"\b(?:ski(?:[- ]?alpin|[- ]?weltcup)?|"
        r"riesentorlauf|riesenslalom|"
        r"slalom|abfahrt|super[- ]?g)\b",
        titel,
        re.I
    ))


def ist_live(titel, beschreibung):
    text = titel + " " + beschreibung

    if re.search(
        r"\b(?:wiederholung|highlights?|"
        r"zusammenfassung|rückblick|"
        r"rueckblick|replay)\b",
        text,
        re.I
    ):
        return False

    return bool(
        re.search(
            r"\b(?:live|direkt|liveübertragung|"
            r"direktübertragung)\b",
            text,
            re.I
        )
        or re.search(r"\bcountdown\b", titel, re.I)
        or re.search(
            r"\b(?:1\.|2\.)\s*(?:durchgang|lauf)\b",
            titel,
            re.I
        )
    )


def durchgang_erkennen(text):
    if re.search(
        r"\b(?:1\.|erster|erste)\s*"
        r"(?:durchgang|lauf)\b",
        text,
        re.I
    ):
        return 1

    if re.search(
        r"\b(?:2\.|zweiter|zweite)\s*"
        r"(?:durchgang|lauf)\b",
        text,
        re.I
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
        re.I
    ))

    herren = bool(re.search(
        r"\b(?:herren|männer|maenner|men)\b",
        text,
        re.I
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

    if len(kandidaten) != 1:
        return None

    return kandidaten[0]


def orf_ergaenzen(rennen):
    for sender, nummer in SENDER.items():
        try:
            daten = json.loads(laden(
                "https://epg.pw/api/epg.json?"
                "channel_id=" + nummer
            ))

            sendungen = daten.get("epg_list")

            if not isinstance(sendungen, list):
                raise ValueError("Programmliste fehlt")

            programm = []

            for sendung in sendungen:
                beginn = programmzeit(
                    sendung.get("start_date")
                )

                if beginn:
                    programm.append((beginn, sendung))

            programm.sort(key=lambda x: x[0])
            treffer = 0

            for i, (beginn, sendung) in enumerate(
                programm[:-1]
            ):
                titel = str(sendung.get("title") or "")
                beschreibung = str(sendung.get("desc") or "")

                if not ist_ski(titel):
                    continue

                if not ist_live(titel, beschreibung):
                    continue

                datum = beginn.astimezone(
                    WIEN
                ).date().isoformat()

                renn = zuordnen(
                    titel,
                    beschreibung,
                    datum,
                    rennen
                )

                if renn is None:
                    continue

                ende = programm[i + 1][0]

                if ende <= beginn:
                    continue

                renn["sendungen"].append({
                    "beginn": beginn,
                    "ende": ende,
                    "sender": sender,
                    "titel": titel,
                    "durchgang": durchgang_erkennen(
                        titel + " " + beschreibung
                    ),
                    "countdown": bool(re.search(
                        r"\bcountdown\b",
                        titel,
                        re.I
                    )),
                })

                treffer += 1

            print(
                sender,
                "- passende Sendungen:",
                treffer
            )

        except Exception as fehler:
            print(
                "ORF momentan nicht verfügbar:",
                sender,
                str(fehler)
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
    return zeit.astimezone(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")


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


def uid_fuer_rennen(renn, nummer):
    # Absichtlich dieselbe UID wie bisher.
    # Sie wird für den ersten Durchgang weiterverwendet.
    identitaet = "|".join((
        renn["datum"],
        renn["geschlecht"],
        renn["disziplin"],
        renn["ort"],
        str(nummer),
    ))

    return (
        hashlib.sha256(
            identitaet.encode("utf-8")
        ).hexdigest()[:24]
        + "@orf-ski-kalender"
    )


def rennlaeufe(renn):
    starts = sorted(set(renn["rennstarts"]))

    if not starts and renn["fis_zeit"]:
        starts = [renn["fis_zeit"]]

    if renn["disziplin"] in ("Slalom", "Riesentorlauf"):
        if len(starts) >= 2:
            return [
                {"nummer": 1, "start": starts[0]},
                {"nummer": 2, "start": starts[1]},
            ]

        if len(starts) == 1:
            return [
                {"nummer": 1, "start": starts[0]}
            ]

        return [
            {"nummer": 1, "start": None}
        ]

    return [
        {
            "nummer": None,
            "start": starts[0] if starts else None
        }
    ]


def sendungen_aufteilen(renn, laeufe):
    """
    ORF-Sendungen nach explizitem Durchgang zuordnen.
    Countdown ohne Nummer dem nächsten Rennstart
    zuordnen, wenn dieser eindeutig feststeht.
    """
    zuordnung = {
        lauf["nummer"]: []
        for lauf in laeufe
    }

    for sendung in renn["sendungen"]:
        nummer = sendung["durchgang"]

        if nummer in zuordnung:
            zuordnung[nummer].append(sendung)
            continue

        if len(laeufe) == 1:
            zuordnung[laeufe[0]["nummer"]].append(sendung)
            continue

        bekannte = [
            lauf for lauf in laeufe
            if lauf["start"] is not None
        ]

        if len(bekannte) < 2:
            continue

        # Nur zuordnen, wenn die Sendung in einem
        # plausiblen Zeitfenster vor dem Lauf beginnt.
        kandidaten = []

        for lauf in bekannte:
            abstand = (
                lauf["start"] - sendung["beginn"]
            ).total_seconds() / 60

            if -30 <= abstand <= 90:
                kandidaten.append((
                    abs(abstand),
                    lauf["nummer"]
                ))

        if len(kandidaten) == 1:
            zuordnung[kandidaten[0][1]].append(sendung)

        elif len(kandidaten) > 1:
            kandidaten.sort()

            if kandidaten[0][0] != kandidaten[1][0]:
                zuordnung[kandidaten[0][1]].append(sendung)

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
    }

    for nummer, renn in enumerate(rennen):
        datum = datetime.fromisoformat(
            renn["datum"]
        ).date()

        basis_uid = uid_fuer_rennen(renn, nummer)
        laeufe = rennlaeufe(renn)
        sendungen = sendungen_aufteilen(renn, laeufe)

        for lauf in laeufe:
            laufnummer = lauf["nummer"]
            start = lauf["start"]

            # Der 1. Durchgang behält die bisherige UID.
            # Nur der 2. Durchgang erhält eine neue UID.
            if laufnummer == 2:
                uid = basis_uid.replace(
                    "@orf-ski-kalender",
                    "-lauf2@orf-ski-kalender"
                )
            else:
                uid = basis_uid

            titel = (
                "🎿 " + renn["ort"]
                + " – " + renn["disziplin"]
                + " " + renn["geschlecht"]
            )

            if laufnummer is not None:
                titel += " | " + str(laufnummer) + ". Durchgang"

            beschreibung = (
                "FIS Ski-Weltcup 2026/27."
            )

            if start:
                beschreibung += (
                    "\nOffizieller Rennstart: "
                    + start.astimezone(WIEN).strftime("%H:%M")
                    + " Uhr"
                )

            passende_sendungen = sendungen.get(
                laufnummer, []
            )

            if passende_sendungen:
                beginn = min(
                    s["beginn"]
                    for s in passende_sendungen
                )

                ende = max(
                    s["ende"]
                    for s in passende_sendungen
                )

                sender = ", ".join(sorted({
                    s["sender"]
                    for s in passende_sendungen
                }))

                titel += " | ORF LIVE"

                beschreibung += (
                    "\nORF-Sendebeginn: "
                    + beginn.astimezone(WIEN).strftime("%H:%M")
                    + " Uhr"
                    + "\nSender: " + sender
                )

                zeitzeilen = [
                    "DTSTART:" + utc_format(beginn),
                    "DTEND:" + utc_format(ende),
                ]

                statistik["ORF"] += 1

            elif start:
                # Vorläufige Dauer pro Durchgang.
                ende = start + timedelta(minutes=90)

                titel += (
                    " | Start "
                    + start.astimezone(WIEN).strftime("%H:%M")
                    + " Uhr"
                )

                beschreibung += (
                    "\nORF-Sendezeit noch nicht erkannt."
                    "\nDauer vorläufig."
                )

                zeitzeilen = [
                    "DTSTART:" + utc_format(start),
                    "DTEND:" + utc_format(ende),
                ]

                statistik["Rennstart"] += 1

            else:
                titel += " | vorläufig"

                beschreibung += (
                    "\nNoch keine bestätigte Startzeit."
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

            zeilen.extend([
                "BEGIN:VEVENT",
                "UID:" + uid,
                "DTSTAMP:" + utc_format(JETZT),
                *zeitzeilen,
                "SUMMARY:" + ics_text(titel),
                "DESCRIPTION:" + ics_text(beschreibung),
                "END:VEVENT",
            ])

    zeilen.append("END:VCALENDAR")

    inhalt = "\r\n".join(
        zeilen_falten(zeilen)
    ) + "\r\n"

    KALENDER.write_bytes(
        inhalt.encode("utf-8")
    )

    gesamt = sum(statistik.values())

    print("Kalendereinträge:", gesamt)

    for name, anzahl in statistik.items():
        print(name + ":", anzahl)

    print("FERTIG")


if __name__ == "__main__":
    print("Erstelle Kalender mit einzelnen Durchgängen")

    rennen = fis_rennen()
    print("FIS-Rennen gefunden:", len(rennen))

    startzeiten_ergaenzen(rennen)
    orf_ergaenzen(rennen)
    kalender_schreiben(rennen)
