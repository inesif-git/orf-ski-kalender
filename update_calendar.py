import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WIEN = ZoneInfo("Europe/Vienna")
JETZT = datetime.now(timezone.utc)

SENDER = {
    "ORF 1": "438442",
    "ORF SPORT+": "76756",
}

SKI_WOERTER = (
    "ski alpin", "ski-alpin", "skiweltcup",
    "ski-weltcup", "riesentorlauf",
    "riesenslalom", "slalom", "abfahrt",
    "super-g", "super g",
)

AUSSCHLUSS = (
    "wiederholung", "highlights",
    "zusammenfassung", "rueckblick",
    "rückblick", "silent sports",
)

def lese_zeit(wert):
    if not wert:
        return None
    try:
        zeit = datetime.fromisoformat(
            str(wert).replace("Z", "+00:00")
        )
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        return zeit.astimezone(timezone.utc)
    except ValueError:
        return None

def ics_zeit(zeit):
    return zeit.strftime("%Y%m%dT%H%M%SZ")

def ics_text(wert):
    return (
        str(wert)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )

def rennstart_finden(titel, beschreibung, datum, rennen):
    daten = rennen.get(datum)
    if not daten:
        return None

    text = (titel + " " + beschreibung).lower()

    geschlecht = daten["geschlecht"].lower()
    if geschlecht == "damen":
        merkmale = ("damen", "frauen", "women", "ladies")
        gegenmerkmale = ("herren", "maenner", "männer", "men")
    else:
        merkmale = ("herren", "maenner", "männer", "men")
        gegenmerkmale = ("damen", "frauen", "women", "ladies")

    if any(wort in text for wort in gegenmerkmale):
        return None

    # Ohne eindeutige Zuordnung kein Rennstart.
    if not any(wort in text for wort in merkmale):
        return None

    disziplin = daten["disziplin"].lower()
    if "riesentorlauf" in disziplin:
        if not any(w in text for w in (
            "riesentorlauf", "riesenslalom",
            "giant slalom"
        )):
            return None
    elif disziplin not in text:
        return None

    if any(w in text for w in (
        "2. durchgang", "zweiter durchgang",
        "2. lauf", "zweiter lauf"
    )):
        uhrzeit = daten.get("zweiter_lauf")
    else:
        uhrzeit = daten.get("erster_lauf")

    if not uhrzeit:
        return None

    return daten, uhrzeit

def baue_event(sender, titel, beschreibung,
                beginn, ende, daten, rennstart):
    uid = hashlib.sha256(
        (sender + titel + beginn.isoformat()).encode()
    ).hexdigest()[:24] + "@orf-ski-kalender"

    titel_kalender = (
        "🎿 " + daten["ort"] + " – "
        + daten["disziplin"] + " "
        + daten["geschlecht"]
        + " | Rennstart " + rennstart + " Uhr"
    )

    beschreibung_kalender = (
        "ORF-Liveuebertragung\n"
        + "Sender: " + sender + "\n"
        + "ORF-Sendebeginn: "
        + beginn.astimezone(WIEN).strftime(
            "%d.%m.%Y %H:%M"
        ) + " Uhr\n"
        + "Rennstart: " + rennstart + " Uhr\n"
        + "Originalsendung: " + titel + "\n"
        + beschreibung[:500]
    )

    return [
        "BEGIN:VEVENT",
        "UID:" + uid,
        "DTSTAMP:" + ics_zeit(JETZT),
        "DTSTART:" + ics_zeit(beginn),
        "DTEND:" + ics_zeit(ende),
        "SUMMARY:" + ics_text(titel_kalender),
        "DESCRIPTION:" + ics_text(beschreibung_kalender),
        "LOCATION:" + ics_text(sender),
        "END:VEVENT",
    ]

def zeilen_falten(zeilen):
    ergebnis = []
    for zeile in zeilen:
        teil = ""
        for zeichen in zeile:
            if len((teil + zeichen).encode("utf-8")) > 70:
                ergebnis.append(teil)
                teil = " "
            teil += zeichen
        ergebnis.append(teil)
    return ergebnis

print("ORF Ski-Kalender mit Rennstarts")

with open("rennstarts.json", encoding="utf-8") as datei:
    rennen = json.load(datei)

print("Hinterlegte Renntage:", len(rennen))

events = []
erfolgreiche_abrufe = 0

for sender, nummer in SENDER.items():
    print("Pruefe:", sender)

    url = (
        "https://epg.pw/api/epg.json?channel_id="
        + nummer
    )

    try:
        anfrage = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(
            anfrage, timeout=30
        ) as antwort:
            daten = json.load(antwort)

        sendungen = daten.get("epg_list")
        if not isinstance(sendungen, list):
            raise ValueError("Keine Programmliste")

        programm = []
        for sendung in sendungen:
            beginn = lese_zeit(sendung.get("start_date"))
            if beginn:
                programm.append((beginn, sendung))

        programm.sort(key=lambda x: x[0])
        erfolgreiche_abrufe += 1
        treffer = 0

        for index, (beginn, sendung) in enumerate(programm):
            if beginn < JETZT:
                continue

            titel = str(sendung.get("title") or "")
            beschreibung = str(
                sendung.get("desc") or ""
            )
            text = (titel + " " + beschreibung).lower()

            if not any(w in titel.lower() for w in SKI_WOERTER):
                continue
            if any(w in text for w in AUSSCHLUSS):
                continue
            if "live" not in text and "direkt" not in text:
                continue

            datum = beginn.astimezone(WIEN).strftime(
                "%Y-%m-%d"
            )
            zuordnung = rennstart_finden(
                titel, beschreibung, datum, rennen
            )

            if not zuordnung:
                print("Noch keine sichere Zuordnung:", titel)
                continue

            if index + 1 >= len(programm):
                continue

            ende = programm[index + 1][0]
            if ende <= beginn:
                continue

            renndaten, rennstart = zuordnung

            events.append(
                baue_event(
                    sender, titel, beschreibung,
                    beginn, ende, renndaten, rennstart
                )
            )
            treffer += 1

        print("Zugeordnete Live-Sendungen:", treffer)

    except Exception as fehler:
        print("Senderabruf fehlgeschlagen:", repr(fehler))

print("Erfolgreiche Abrufe:", erfolgreiche_abrufe)
print("Neue Kalendereintraege:", len(events))

if erfolgreiche_abrufe != len(SENDER):
    raise RuntimeError(
        "Nicht alle Sender erreichbar. "
        "Kalender bleibt unveraendert."
    )

if not events:
    print("Noch keine passenden ORF-Live-Sendungen.")
    print("Kalenderdatei bleibt unveraendert.")
else:
    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ORF Ski Kalender//DE",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:ORF Ski-Weltcup LIVE",
    ]

    for event in events:
        zeilen.extend(event)

    zeilen.append("END:VCALENDAR")

    inhalt = "\r\n".join(
        zeilen_falten(zeilen)
    ) + "\r\n"

    Path("ski-weltcup.ics").write_bytes(
        inhalt.encode("utf-8")
    )
    print("Kalenderdatei geschrieben.")

print("FERTIG")
