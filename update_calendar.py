import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WIEN = ZoneInfo("Europe/Vienna")
JETZT = datetime.now(timezone.utc)

KALENDER = Path("ski-weltcup.ics")
RENNSTARTS = Path("rennstarts.json")

FIS_URL = (
    "https://www.fis-ski.com/DB/services/public/"
    "icalendar-feed-fis-events.html?"
    "seasoncode=2027&sectorcode=AL&categorycode=WC"
)

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

def abrufen(url):
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

def entfalte_ical(inhalt):
    zeilen = inhalt.replace(
        "\r\n", "\n"
    ).split("\n")
    ergebnis = []
    for zeile in zeilen:
        if zeile.startswith((" ", "\t")) and ergebnis:
            ergebnis[-1] += zeile[1:]
        else:
            ergebnis.append(zeile)
    return ergebnis

def fis_rennen_lesen():
    inhalt = abrufen(FIS_URL)
    if "BEGIN:VCALENDAR" not in inhalt:
        raise ValueError("FIS liefert keinen Kalender")

    termine = []
    eintrag = None

    for zeile in entfalte_ical(inhalt):
        if zeile == "BEGIN:VEVENT":
            eintrag = {}
        elif zeile == "END:VEVENT":
            if eintrag:
                termine.append(eintrag)
            eintrag = None
        elif eintrag is not None and ":" in zeile:
            feld, wert = zeile.split(":", 1)
            if feld.startswith("DTSTART"):
                eintrag["datum"] = wert[:8]
            elif feld.startswith("SUMMARY"):
                eintrag["titel"] = wert
            elif feld.startswith("DESCRIPTION"):
                eintrag["beschreibung"] = wert

    rennen = {}
    for eintrag in termine:
        datum = eintrag.get("datum", "")
        if not re.fullmatch(r"\d{8}", datum):
            continue

        datum = (
            datum[:4] + "-" + datum[4:6]
            + "-" + datum[6:8]
        )

        beschreibung = eintrag.get(
            "beschreibung", ""
        ).replace("\\n", " ")

        geschlecht = None
        if re.search(
            r"Gender:\s*Women\b",
            beschreibung, re.I
        ):
            geschlecht = "Damen"
        elif re.search(
            r"Gender:\s*Men\b",
            beschreibung, re.I
        ):
            geschlecht = "Herren"

        if not geschlecht:
            continue

        text = (
            eintrag.get("titel", "")
            + " " + beschreibung
        ).lower()

        disziplin = None
        if "giant slalom" in text:
            disziplin = "Riesentorlauf"
        elif "super-g" in text or "super g" in text:
            disziplin = "Super-G"
        elif "downhill" in text:
            disziplin = "Abfahrt"
        elif "slalom" in text:
            disziplin = "Slalom"

        if not disziplin:
            continue

        ort = eintrag.get(
            "titel", ""
        ).split(" - ")[0].split(" – ")[0].strip()

        rennen.setdefault(datum, []).append({
            "ort": ort,
            "disziplin": disziplin,
            "geschlecht": geschlecht,
            "erster_lauf": None,
            "zweiter_lauf": None,
            "quelle": "FIS",
        })

    if not rennen:
        raise ValueError("Keine FIS-Rennen erkannt")

    return rennen, len(termine)

def lokale_startzeiten_lesen():
    if not RENNSTARTS.exists():
        return {}

    with RENNSTARTS.open(
        encoding="utf-8"
    ) as datei:
        return json.load(datei)

def startzeiten_ergaenzen(rennen, lokal):
    for datum, daten in lokal.items():
        kandidaten = rennen.get(datum, [])

        for renn in kandidaten:
            if (
                renn["geschlecht"].lower()
                == daten.get("geschlecht", "").lower()
                and renn["disziplin"].lower()
                == daten.get("disziplin", "").lower()
            ):
                renn["erster_lauf"] = daten.get(
                    "erster_lauf"
                )
                renn["zweiter_lauf"] = daten.get(
                    "zweiter_lauf"
                )

def passendes_rennen(titel, beschreibung, datum, rennen):
    text = (titel + " " + beschreibung).lower()

    if re.search(
        r"\b(damen|frauen|women|ladies)\b", text
    ):
        geschlecht = "Damen"
    elif re.search(
        r"\b(herren|männer|maenner|men)\b", text
    ):
        geschlecht = "Herren"
    else:
        return None

    if any(w in text for w in (
        "riesentorlauf", "riesenslalom",
        "giant slalom"
    )):
        disziplin = "Riesentorlauf"
    elif "super-g" in text or "super g" in text:
        disziplin = "Super-G"
    elif "abfahrt" in text or "downhill" in text:
        disziplin = "Abfahrt"
    elif "slalom" in text:
        disziplin = "Slalom"
    else:
        return None

    kandidaten = [
        r for r in rennen.get(datum, [])
        if r["geschlecht"] == geschlecht
        and r["disziplin"] == disziplin
    ]

    if len(kandidaten) != 1:
        return None

    return kandidaten[0]

def rennstart_bestimmen(titel, beschreibung, renn):
    text = (titel + " " + beschreibung).lower()

    zweiter = any(w in text for w in (
        "2. durchgang", "zweiter durchgang",
        "2. lauf", "zweiter lauf",
        "second run"
    ))

    erster = any(w in text for w in (
        "1. durchgang", "erster durchgang",
        "1. lauf", "erster lauf",
        "first run"
    ))

    if zweiter:
        return renn.get("zweiter_lauf")
    if erster:
        return renn.get("erster_lauf")

    # Ohne eindeutige Laufzuordnung keine
    # vermeintlich genaue Startzeit behaupten.
    return None

def uid_lesen(zeilen):
    for zeile in zeilen:
        if zeile.startswith("UID:"):
            return zeile[4:]
    return None

def alte_events_lesen():
    if not KALENDER.exists():
        return {}

    inhalt = KALENDER.read_text(
        encoding="utf-8-sig"
    )
    zeilen = entfalte_ical(inhalt)

    events = {}
    block = None

    for zeile in zeilen:
        if zeile == "BEGIN:VEVENT":
            block = [zeile]
        elif block is not None:
            block.append(zeile)

            if zeile == "END:VEVENT":
                uid = uid_lesen(block)
                start = next(
                    (
                        z.split(":", 1)[1]
                        for z in block
                        if z.startswith("DTSTART:")
                    ),
                    None
                )

                if (
                    uid
                    and uid.endswith("@orf-ski-kalender")
                    and start
                ):
                    try:
                        beginn = datetime.strptime(
                            start, "%Y%m%dT%H%M%SZ"
                        ).replace(tzinfo=timezone.utc)
                        if beginn >= JETZT:
                            events[uid] = block
                    except ValueError:
                        pass

                block = None

    return events

def event_erstellen(
    sender, titel, beschreibung,
    beginn, ende, renn, rennstart
):
    uid = hashlib.sha256(
        (
            sender + "|" + titel + "|"
            + beginn.isoformat()
        ).encode("utf-8")
    ).hexdigest()[:24] + "@orf-ski-kalender"

    zusammenfassung = (
        "🎿 " + renn["ort"] + " – "
        + renn["disziplin"] + " "
        + renn["geschlecht"]
    )

    if rennstart:
        zusammenfassung += (
            " | Rennstart " + rennstart + " Uhr"
        )
    else:
        zusammenfassung += (
            " | Rennstartzeit noch offen"
        )

    beschr = (
        "ORF-Sendebeginn: "
        + beginn.astimezone(WIEN).strftime(
            "%d.%m.%Y %H:%M"
        )
        + " Uhr\nSender: " + sender
        + "\nFIS-Rennen: " + renn["ort"]
        + ", " + renn["disziplin"]
        + ", " + renn["geschlecht"]
        + "\nRennstart: "
        + (
            rennstart + " Uhr"
            if rennstart
            else "Noch nicht eindeutig bestaetigt"
        )
        + "\nORF-Sendung: " + titel
        + "\n" + beschreibung[:500]
    )

    return [
        "BEGIN:VEVENT",
        "UID:" + uid,
        "DTSTAMP:" + ics_zeit(JETZT),
        "DTSTART:" + ics_zeit(beginn),
        "DTEND:" + ics_zeit(ende),
        "SUMMARY:" + ics_text(zusammenfassung),
        "DESCRIPTION:" + ics_text(beschr),
        "LOCATION:" + ics_text(sender),
        "END:VEVENT",
    ]

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

print("ORF Ski-Kalender mit FIS-Weltcupdaten")

rennen, anzahl_fis = fis_rennen_lesen()

print("FIS-Termine insgesamt:", anzahl_fis)
print("Renntage:", len(rennen))
print(
    "Erkannte Rennen:",
    sum(len(eintraege) for eintraege in rennen.values())
)

lokale_startzeiten = lokale_startzeiten_lesen()
startzeiten_ergaenzen(
    rennen, lokale_startzeiten
)

print(
    "Hinterlegte Startzeit-Datensaetze:",
    len(lokale_startzeiten)
)

events = alte_events_lesen()
print(
    "Bisherige Zukunftstermine:",
    len(events)
)

erfolgreiche_abrufe = 0
neue_treffer = 0

for sender, nummer in SENDER.items():
    print("Pruefe:", sender)

    url = (
        "https://epg.pw/api/epg.json?"
        "channel_id=" + nummer
    )

    try:
        daten = json.loads(abrufen(url))
        sendungen = daten.get("epg_list")

        if not isinstance(sendungen, list):
            raise ValueError("Keine Programmliste")

        programm = []

        for sendung in sendungen:
            beginn = zeit_lesen(
                sendung.get("start_date")
            )
            if beginn:
                programm.append(
                    (beginn, sendung)
                )

        programm.sort(
            key=lambda eintrag: eintrag[0]
        )

        erfolgreiche_abrufe += 1

        for index, (beginn, sendung) in enumerate(
            programm
        ):
            if beginn < JETZT:
                continue

            titel = str(
                sendung.get("title") or ""
            )
            beschreibung = str(
                sendung.get("desc") or ""
            )
            text = (
                titel + " " + beschreibung
            ).lower()

            if not any(
                wort in titel.lower()
                for wort in SKI_WOERTER
            ):
                continue

            if any(
                wort in text
                for wort in AUSSCHLUSS
            ):
                continue

            if not re.search(
                r"\b(live|direkt)\b", text
            ):
                continue

            datum = beginn.astimezone(
                WIEN
            ).strftime("%Y-%m-%d")

            renn = passendes_rennen(
                titel, beschreibung,
                datum, rennen
            )

            if not renn:
                print(
                    "Keine eindeutige Zuordnung:",
                    titel
                )
                continue

            if index + 1 >= len(programm):
                continue

            ende = programm[index + 1][0]

            if ende <= beginn:
                continue

            rennstart = rennstart_bestimmen(
                titel, beschreibung, renn
            )

            event = event_erstellen(
                sender, titel, beschreibung,
                beginn, ende, renn, rennstart
            )

            uid = uid_lesen(event)

            if uid not in events:
                neue_treffer += 1

            events[uid] = event

    except Exception as fehler:
        print(
            "Senderabruf fehlgeschlagen:",
            sender, repr(fehler)
        )

print(
    "Erfolgreiche Senderabrufe:",
    erfolgreiche_abrufe
)
print("Neue Live-Termine:", neue_treffer)
print(
    "Kalendereintraege insgesamt:",
    len(events)
)

if erfolgreiche_abrufe != len(SENDER):
    raise RuntimeError(
        "Nicht alle ORF-Sender erreichbar. "
        "Kalender bleibt unveraendert."
    )

if not events:
    print(
        "Noch keine passenden "
        "ORF-Liveuebertragungen."
    )
    print(
        "Kalenderdatei bleibt unveraendert."
    )
else:
    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ORF Ski Kalender//DE",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:ORF Ski-Weltcup LIVE",
    ]

    sortierte_events = sorted(
        events.values(),
        key=lambda event: next(
            (
                z for z in event
                if z.startswith("DTSTART:")
            ),
            ""
        )
    )

    for event in sortierte_events:
        zeilen.extend(event)

    zeilen.append("END:VCALENDAR")

    inhalt = "\r\n".join(
        zeilen_falten(zeilen)
    ) + "\r\n"

    KALENDER.write_bytes(
        inhalt.encode("utf-8")
    )

    print(
        "Kalenderdatei aktualisiert."
    )

print("FERTIG")
