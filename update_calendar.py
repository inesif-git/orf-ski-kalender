import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DATEI = Path("ski-weltcup.ics")
WIEN = ZoneInfo("Europe/Vienna")
JETZT = datetime.now(timezone.utc)

SENDER = {
    "ORF 1": "438442",
    "ORF SPORT+": "76756",
}

SKI_TITEL = (
    "ski alpin", "ski-alpin", "skiweltcup",
    "ski-weltcup", "alpiner ski",
    "slalom", "riesentorlauf", "riesenslalom",
    "abfahrt", "super-g", "super g",
)

AUSSCHLUSS = (
    "wiederholung", "zusammenfassung",
    "highlights", "rückblick", "rueckblick",
    "sport 20", "silent sports",
)

def zeit_lesen(wert):
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

def esc(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )

def utc(zeit):
    return zeit.strftime("%Y%m%dT%H%M%SZ")

def event_bauen(sender, titel, beschreibung, start, ende):
    kennung = hashlib.sha256(
        (sender + titel + start.isoformat()).encode()
    ).hexdigest()[:24]

    lokale_zeit = start.astimezone(WIEN)
    beschr = (
        "ORF-Liveuebertragung (vorlaeufig erkannt)\\n"
        + "Sender: " + sender + "\\n"
        + "ORF-Sendebeginn: "
        + lokale_zeit.strftime("%d.%m.%Y %H:%M")
        + " Uhr\\n"
        + "Tatsaechlicher Rennstart: noch nicht bestaetigt\\n"
        + "Originaltitel: " + titel + "\\n"
        + "Programmbeschreibung: " + beschreibung[:600]
    )

    return [
        "BEGIN:VEVENT",
        "UID:" + kennung + "@orf-ski-kalender",
        "DTSTAMP:" + utc(JETZT),
        "DTSTART:" + utc(start),
        "DTEND:" + utc(ende),
        "SUMMARY:" + esc(
            "🎿 " + titel + " | Rennstart offen"
        ),
        "DESCRIPTION:" + esc(beschr),
        "LOCATION:" + esc(sender),
        "END:VEVENT",
    ]

print("ORF Ski-Kalender erstellen")
alle_events = []
abrufe_ok = 0

for sender, nummer in SENDER.items():
    print("Pruefe:", sender)
    url = (
        "https://epg.pw/api/epg.json?channel_id="
        + nummer
    )

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(
            request, timeout=30
        ) as response:
            daten = json.load(response)

        if not isinstance(daten.get("epg_list"), list):
            raise ValueError("Keine gueltige Programmliste")

        if daten.get("name", "").strip().lower() != sender.lower().replace("+", " +").strip():
            print("Sendername pruefen:", daten.get("name"))

        sendungen = []
        for eintrag in daten["epg_list"]:
            start = zeit_lesen(eintrag.get("start_date"))
            if start:
                sendungen.append((start, eintrag))

        sendungen.sort(key=lambda item: item[0])
        abrufe_ok += 1
        treffer = 0

        for i, (start, eintrag) in enumerate(sendungen):
            if start < JETZT:
                continue

            titel = str(eintrag.get("title") or "").strip()
            beschreibung = str(
                eintrag.get("desc") or ""
            ).strip()
            text = (titel + " " + beschreibung).lower()
            titel_klein = titel.lower()

            if not any(w in titel_klein for w in SKI_TITEL):
                continue
            if any(w in text for w in AUSSCHLUSS):
                continue

            # Ohne erkennbare Live-Kennzeichnung
            # keine unbestaetigte Sendung eintragen.
            if not any(w in text for w in (
                "live", "direkt", "1. durchgang",
                "2. durchgang", "1. lauf", "2. lauf"
            )):
                print("Live-Status unklar:", titel)
                continue

            # Die naechste Sendung begrenzt den Slot.
            if i + 1 >= len(sendungen):
                print("Endzeit unklar:", titel)
                continue

            ende = sendungen[i + 1][0]
            if ende <= start:
                continue

            alle_events.extend(
                event_bauen(
                    sender, titel, beschreibung,
                    start, ende
                )
            )
            treffer += 1

        print("Neue sichere Kandidaten:", treffer)

    except Exception as fehler:
        print("Abruf fehlgeschlagen:", repr(fehler))

print("Erfolgreiche Senderabrufe:", abrufe_ok)

# Vorhandene automatisch erzeugte Zukunftstermine
# beibehalten, wenn sie heute noch nicht im EPG stehen.
alte_events = []
if DATEI.exists():
    inhalt = DATEI.read_text(encoding="utf-8-sig")
    for block in inhalt.split("BEGIN:VEVENT")[1:]:
        block = "BEGIN:VEVENT" + block.split(
            "END:VEVENT", 1
        )[0] + "END:VEVENT"
        if "@orf-ski-kalender" not in block:
            continue
        match = re.search(
            r"^DTSTART:(\d{8}T\d{6}Z)$",
            block, re.MULTILINE
        )
        if match:
            beginn = datetime.strptime(
                match.group(1), "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc)
            if beginn >= JETZT:
                alte_events.append(block.splitlines())

def uid_aus_event(zeilen):
    for zeile in zeilen:
        if zeile.startswith("UID:"):
            return zeile
    return ""

events = {}
for block in alte_events:
    events[uid_aus_event(block)] = block

for block in [
    alle_events[i:j]
    for i, j in []
]:
    pass

# Neue Events liegen als zusammenhaengende Zeilen vor.
block = []
for zeile in alle_events:
    if zeile == "BEGIN:VEVENT":
        block = [zeile]
    elif block:
        block.append(zeile)
        if zeile == "END:VEVENT":
            events[uid_aus_event(block)] = block
            block = []

print("Kalendereintraege insgesamt:", len(events))

if abrufe_ok == 0:
    raise RuntimeError(
        "Beide Senderabrufe fehlgeschlagen; "
        "bestehender Kalender bleibt erhalten"
    )

# Leere Ergebnisse loeschen den vorhandenen
# Testkalender vorerst nicht.
if not events:
    print("Noch keine bestaetigten Live-Termine.")
    print("Kalenderdatei bleibt unveraendert.")
else:
    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ORF Ski Kalender//DE",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:ORF Ski-Weltcup LIVE",
    ]
    for eintrag in events.values():
        zeilen.extend(eintrag)
    zeilen.append("END:VCALENDAR")

    # Lange ICS-Zeilen falten.
    ausgabe = []
    for zeile in zeilen:
        while len(zeile.encode("utf-8")) > 70:
            grenze = 65
            while len(zeile[:grenze].encode("utf-8")) > 65:
                grenze -= 1
            ausgabe.append(zeile[:grenze])
            zeile = " " + zeile[grenze:]
        ausgabe.append(zeile)

    DATEI.write_bytes(
        ("\r\n".join(ausgabe) + "\r\n").encode("utf-8")
    )
    print("Kalenderdatei aktualisiert.")

print("FERTIG")
