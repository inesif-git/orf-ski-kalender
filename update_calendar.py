
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ORF Ski-Weltcup-Kalender 2026/27
# Zuerst ALLE FIS-Rennen eintragen.
# Danach verfuegbare ORF-Livezeiten ergaenzen.

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
    with urllib.request.urlopen(
        anfrage, timeout=30
    ) as antwort:
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
        "giant slalom", "riesentorlauf",
        "riesenslalom"
    )):
        return "Riesentorlauf"
    if "super-g" in text or "super g" in text:
        return "Super-G"
    if "downhill" in text or "abfahrt" in text:
        return "Abfahrt"
    if re.search(r"\bslalom\b", text):
        return "Slalom"
    return None


def fis_rennen():
    inhalt = laden(FIS_URL)

    if "BEGIN:VCALENDAR" not in inhalt:
        raise RuntimeError("FIS-Kalender nicht lesbar")

    eintraege = []
    block = None

    for zeile in entfalten(inhalt):
        if zeile == "BEGIN:VEVENT":
            block = {}
        elif zeile == "END:VEVENT":
            if block is not None:
                eintraege.append(block)
            block = None
        elif block is not None and ":" in zeile:
            feld, wert = zeile.split(":", 1)

            if feld.startswith("DTSTART"):
                block["datum"] = wert[:8]
            elif feld == "SUMMARY":
                block["titel"] = bereinigen(wert)
            elif feld == "DESCRIPTION":
                block["beschreibung"] = bereinigen(wert)

    rennen = []

    for eintrag in eintraege:
        datum = eintrag.get("datum", "")
        if not re.fullmatch(r"\d{8}", datum):
            continue

        beschreibung = eintrag.get("beschreibung", "")
        titel = eintrag.get("titel", "")
        text = titel + " " + beschreibung

        if re.search(
            r"Gender:\s*Women\b", beschreibung, re.I
        ):
            geschlecht = "Damen"
        elif re.search(
            r"Gender:\s*Men\b", beschreibung, re.I
        ):
            geschlecht = "Herren"
        else:
            continue

        art = disziplin(text)
        if not art:
            continue

        ort = re.split(
            r"\s+[-–]\s+", titel
        )[0].strip()

        rennen.append({
            "datum": (
                datum[:4] + "-"
                + datum[4:6] + "-"
                + datum[6:8]
            ),
            "ort": ort,
            "disziplin": art,
            "geschlecht": geschlecht,
            "sendungen": [],
            "rennstarts": [],
        })

    if not rennen:
        raise RuntimeError(
            "Keine FIS-Rennen erkannt. "
            "Bestehender Kalender bleibt erhalten."
        )

    return rennen


def startzeiten_ergaenzen(rennen):
    if not STARTZEITEN.exists():
        return

    daten = json.loads(
        STARTZEITEN.read_text(encoding="utf-8")
    )

    for renn in rennen:
        zusatz = daten.get(renn["datum"], {})

        if (
            zusatz.get("geschlecht") != renn["geschlecht"]
            or zusatz.get("disziplin") != renn["disziplin"]
        ):
            continue

        for schluessel in (
            "erster_lauf", "zweiter_lauf"
        ):
            zeit = zusatz.get(schluessel)
            if zeit:
                renn["rennstarts"].append(zeit)


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

    if re.search(
        r"\b(?:live|direkt|"
        r"liveübertragung|direktübertragung)\b",
        text,
        re.I
    ):
        return True

    # ORF bezeichnet Vorberichte oft als Countdown.
    # Nur als Teil einer eindeutig passenden
    # Ski-Weltcup-Sendung zulassen.
    return bool(re.search(
        r"\bcountdown\b", titel, re.I
    ))


def zuordnen(titel, beschreibung, datum, rennen):
    text = titel + " " + beschreibung

    kandidaten = [
        r for r in rennen
        if r["datum"] == datum
    ]

    if not kandidaten:
        return None

    damen = bool(re.search(
        r"\b(?:damen|frauen|women|ladies)\b",
        text, re.I
    ))
    herren = bool(re.search(
        r"\b(?:herren|männer|maenner|men)\b",
        text, re.I
    ))

    if damen and herren:
        return None

    if damen:
        kandidaten = [
            r for r in kandidaten
            if r["geschlecht"] == "Damen"
        ]
    elif herren:
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

    # Ortsnamen verwenden, falls sie
    # in der ORF-Sendung genannt werden.
    mit_ort = [
        r for r in kandidaten
        if r["ort"].lower() in text.lower()
    ]

    if mit_ort:
        kandidaten = mit_ort

    # Bei Mehrdeutigkeit nichts raten.
    if len(kandidaten) != 1:
        return None

    return kandidaten[0]


def orf_ergaenzen(rennen):
    erfolgreiche_sender = 0

    for sender, nummer in SENDER.items():
        url = (
            "https://epg.pw/api/epg.json?"
            "channel_id=" + nummer
        )

        try:
            daten = json.loads(laden(url))
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
            erfolgreiche_sender += 1
            treffer = 0

            for i, (beginn, sendung) in enumerate(
                programm
            ):
                titel = str(
                    sendung.get("title") or ""
                )
                beschreibung = str(
                    sendung.get("desc") or ""
                )

                if not ist_ski(titel):
                    continue

                if not ist_live(
                    titel, beschreibung
                ):
                    continue

                datum = beginn.astimezone(
                    WIEN
                ).strftime("%Y-%m-%d")

                renn = zuordnen(
                    titel, beschreibung,
                    datum, rennen
                )

                if renn is None:
                    continue

                # Ende aus Beginn der naechsten
                # ORF-Sendung bestimmen.
                if i + 1 >= len(programm):
                    continue

                ende = programm[i + 1][0]
                if ende <= beginn:
                    continue

                renn["sendungen"].append({
                    "beginn": beginn,
                    "ende": ende,
                    "sender": sender,
                    "titel": titel,
                })

                treffer += 1

            print(
                sender,
                "- passende Sendungen:",
                treffer
            )

        except Exception as fehler:
            print(
                "ORF momentan nicht verfuegbar:",
                sender, str(fehler)
            )

    print(
        "Erfolgreiche ORF-Abfragen:",
        erfolgreiche_sender
    )

    # FIS-Saisonkalender wird auch dann erstellt,
    # wenn ORF voruebergehend nicht erreichbar ist.


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


def kalender_schreiben(rennen):
    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ORF Ski Kalender//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:ORF Ski-Weltcup LIVE",
    ]

    zeitlich = 0
    vorlaeufig = 0

    for nummer, renn in enumerate(rennen):
        datum = datetime.strptime(
            renn["datum"], "%Y-%m-%d"
        ).date()

        identitaet = (
            renn["datum"] + "|"
            + renn["geschlecht"] + "|"
            + renn["disziplin"] + "|"
            + renn["ort"] + "|"
            + str(nummer)
        )

        uid = hashlib.sha256(
            identitaet.encode("utf-8")
        ).hexdigest()[:24] + "@orf-ski-kalender"

        titel = (
            "🎿 " + renn["ort"] + " – "
            + renn["disziplin"] + " "
            + renn["geschlecht"]
        )

        beschreibung = (
            "Offizieller FIS-Weltcuptermin 2026/27."
        )

        sendungen = renn["sendungen"]

        if sendungen:
            beginn = min(
                s["beginn"] for s in sendungen
            )
            ende = max(
                s["ende"] for s in sendungen
            )

            sender = ", ".join(sorted(set(
                s["sender"] for s in sendungen
            )))

            titel += " | ORF LIVE"

            beschreibung += (
                "\nORF-Sendebeginn: "
                + beginn.astimezone(WIEN).strftime(
                    "%d.%m.%Y %H:%M"
                )
                + " Uhr"
                + "\nSender: " + sender
            )

            zeitzeilen = [
                "DTSTART:" + utc_format(beginn),
                "DTEND:" + utc_format(ende),
            ]

            zeitlich += 1

        else:
            titel += " | vorläufig"

            beschreibung += (
                "\nORF-Sendezeit noch nicht "
                "veröffentlicht oder erkannt."
                "\nGanztägiger Platzhalter, "
                "keine bestätigte Uhrzeit."
            )

            zeitzeilen = [
                "DTSTART;VALUE=DATE:"
                + datum.strftime("%Y%m%d"),
                "DTEND;VALUE=DATE:"
                + (
                    datum + timedelta(days=1)
                ).strftime("%Y%m%d"),
            ]

            vorlaeufig += 1

        if renn["rennstarts"]:
            starts = ", ".join(
                zeit + " Uhr"
                for zeit in renn["rennstarts"]
            )
            beschreibung += (
                "\nHinterlegte Rennstarts: "
                + starts
            )

            if sendungen:
                titel += " | Rennstarts " + starts

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

    inhalt = "\r\n".join(
        zeilen_falten(zeilen)
    ) + "\r\n"

    KALENDER.write_bytes(
        inhalt.encode("utf-8")
    )

    print("Kalendereintraege:", len(rennen))
    print("Mit ORF-Sendezeit:", zeitlich)
    print("Vorlaeufig:", vorlaeufig)
    print("Kalenderdatei aktualisiert.")
    print("FERTIG")


print("Erstelle vollstaendigen Saisonkalender")

rennen = fis_rennen()
print("FIS-Rennen gefunden:", len(rennen))

startzeiten_ergaenzen(rennen)
orf_ergaenzen(rennen)
kalender_schreiben(rennen)
