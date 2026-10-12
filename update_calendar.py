import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WIEN = ZoneInfo("Europe/Vienna")
JETZT = datetime.now(timezone.utc)
KALENDER = Path("ski-weltcup.ics")

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

    if any(w in text for w in gegenmerkmale):
        return None
    if not any(w in text for w in merkmale):
        return None

    if "riesentorlauf" in daten["disziplin"].lower():
        if not any(w in text for w in (
            "riesentorlauf", "riesenslalom",
            "giant slalom"
        )):
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

def event_erstellen(sender, titel, beschreibung,
                    beginn, ende, renndaten, rennstart):
    uid = hashlib.sha256(
        (sender + titel + beginn.isoformat()).encode()
    ).hexdigest()[:24] + "@orf-ski-kalender"

    titel_kalender = (
        "🎿 " + renndaten["ort"] + " – "
        + renndaten["disziplin"] + " "
        + renndaten["geschlecht"]
        + " | Rennstart " + rennstart + " Uhr"
    )

    beschr = (
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
        "DESCRIPTION:" + ics_text(beschr),
        "LOCATION:" + ics_text(sender),
        "END:VEVENT",
    ]

def uid_lesen(event):
    for zeile in event:
        if zeile.startswith("UID:"):
            return zeile[4:]
    return None

def alte_events_lesen():
    if not KALENDER.exists():
        return {}

    inhalt = KALENDER.read_text(
        encoding="utf-8-sig"
    )

    # Gefaltete ICS-Zeilen wieder verbinden.
    inhalt = re.sub(
        r"\r?\n[ \t]", "", inhalt
    )

    ergebnis = {}

    for teil in inhalt.split("BEGIN:VEVENT")[1:]:
        if "END:VEVENT" not in teil:
            continue

        block = (
            "BEGIN:VEVENT" +
            teil.split("END:VEVENT", 1)[0] +
            "END:VEVENT"
        )
        zeilen = block.splitlines()
        uid = uid_lesen(zeilen)

        # Nur von unserem Programm erzeugte
        # Eintraege uebernehmen.
        if not uid or not uid.endswith(
            "@orf-ski-kalender"
        ):
            continue

        match = re.search(
            r"^DTSTART:(\d{8}T\d{6}Z)$",
            block, re.MULTILINE
        )
        if not match:
            continue

        beginn = datetime.strptime(
            match.group(1),
            "%Y%m%dT%H%M%SZ"
        ).replace(tzinfo=timezone.utc)

        # Vergangene Termine entfernen.
        if beginn >= JETZT:
            ergebnis[uid] = zeilen

    return ergebnis

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

print("ORF Ski-Kalender - Termine bewahren")

with open("rennstarts.json", encoding="utf-8") as datei:
    rennen = json.load(datei)

print("Hinterlegte Renntage:", len(rennen))

events = alte_events_lesen()
print("Bisherige Zukunftstermine:", len(events))

erfolgreiche_abrufe = 0
neue_treffer = 0

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
                print("Zuordnung unklar:", titel)
                continue

            if index + 1 >= len(programm):
                continue

            ende = programm[index + 1][0]
            if ende <= beginn:
                continue

            renndaten, rennstart = zuordnung
            event = event_erstellen(
                sender, titel, beschreibung,
                beginn, ende, renndaten, rennstart
            )

            uid = uid_lesen(event)
            if uid not in events:
                neue_treffer += 1
            events[uid] = event

    except Exception as fehler:
        print("Abruf fehlgeschlagen:", repr(fehler))

print("Erfolgreiche Senderabrufe:", erfolgreiche_abrufe)
print("Neue Live-Termine:", neue_treffer)
print("Kalendereintraege insgesamt:", len(events))

if erfolgreiche_abrufe != len(SENDER):
    raise RuntimeError(
        "Senderabruf unvollstaendig. "
        "Kalender bleibt unveraendert."
    )

if not events:
    print("Noch keine passenden Live-Termine.")
    print("Kalenderdatei bleibt unveraendert.")
else:
    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ORF Ski Kalender//DE",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:ORF Ski-Weltcup LIVE",
    ]

    for event in sorted(
        events.values(),
        key=lambda e: next(
            (z for z in e if z.startswith("DTSTART:")),
            ""
        )
    ):
        zeilen.extend(event)

    zeilen.append("END:VCALENDAR")

    inhalt = "\r\n".join(
        zeilen_falten(zeilen)
    ) + "\r\n"

    KALENDER.write_bytes(
        inhalt.encode("utf-8")
    )
    print("Kalenderdatei aktualisiert.")

print("FERTIG")
