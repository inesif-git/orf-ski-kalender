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

FIS_URL = (
    "https://www.fis-ski.com/DB/services/public/"
    "icalendar-feed-fis-events.html?"
    "seasoncode=2027&sectorcode=AL&categorycode=WC"
)

SENDER = {
    "ORF 1": "438442",
    "ORF SPORT+": "76756",
}

SKI_MUSTER = re.compile(
    r"\b(?:ski(?:[- ]?alpin|[- ]?weltcup)?|"
    r"weltcup|riesentorlauf|riesenslalom|"
    r"slalom|abfahrt|super[- ]?g|"
    r"giant slalom|downhill)\b",
    re.I,
)

AUSSCHLUSS = re.compile(
    r"\b(?:wiederholung|highlights?|"
    r"zusammenfassung|rückblick|rueckblick|"
    r"silent sports|best of|replay)\b",
    re.I,
)

LIVE = re.compile(
    r"\b(?:live|liveübertragung|"
    r"live-übertragung|direktübertragung|"
    r"direkt)\b",
    re.I,
)

DAMEN = re.compile(
    r"\b(?:damen|frauen|women|ladies)\b", re.I
)
HERREN = re.compile(
    r"\b(?:herren|männer|maenner|men)\b", re.I
)

VORBERICHT = re.compile(
    r"\b(?:vorbericht|vorberichterstattung|"
    r"vorschau|studio)\b",
    re.I,
)

ERSTER = re.compile(
    r"\b(?:1\.\s*(?:lauf|durchgang)|"
    r"erster\s+(?:lauf|durchgang)|first run)\b",
    re.I,
)

ZWEITER = re.compile(
    r"\b(?:2\.\s*(?:lauf|durchgang)|"
    r"zweiter\s+(?:lauf|durchgang)|second run)\b",
    re.I,
)


def abrufen(url):
    anfrage = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(
        anfrage, timeout=30
    ) as antwort:
        return antwort.read().decode(
            "utf-8-sig", errors="replace"
        )


def entfalte(inhalt):
    zeilen = inhalt.replace("\r\n", "\n").split("\n")
    ergebnis = []
    for zeile in zeilen:
        if zeile.startswith((" ", "\t")) and ergebnis:
            ergebnis[-1] += zeile[1:]
        else:
            ergebnis.append(zeile)
    return ergebnis


def fis_lesen():
    inhalt = abrufen(FIS_URL)
    if "BEGIN:VCALENDAR" not in inhalt:
        raise ValueError("FIS-Kalender nicht erkannt")

    termine = []
    eintrag = None

    for zeile in entfalte(inhalt):
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
        rohdatum = eintrag.get("datum", "")
        if not re.fullmatch(r"\d{8}", rohdatum):
            continue

        datum = (
            rohdatum[:4] + "-"
            + rohdatum[4:6] + "-"
            + rohdatum[6:8]
        )

        beschreibung = eintrag.get(
            "beschreibung", ""
        ).replace("\\n", " ")

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

        titel = eintrag.get("titel", "")
        text = (titel + " " + beschreibung).lower()

        if "giant slalom" in text:
            disziplin = "Riesentorlauf"
        elif "super-g" in text or "super g" in text:
            disziplin = "Super-G"
        elif "downhill" in text:
            disziplin = "Abfahrt"
        elif "slalom" in text:
            disziplin = "Slalom"
        else:
            continue

        ort = re.split(r"\s+[-–]\s+", titel)[0].strip()

        rennen.setdefault(datum, []).append({
            "ort": ort,
            "disziplin": disziplin,
            "geschlecht": geschlecht,
            "erster_lauf": None,
            "zweiter_lauf": None,
        })

    if not rennen:
        raise ValueError("Keine FIS-Rennen erkannt")

    return rennen, len(termine)


def startzeiten_ergaenzen(rennen):
    datei = Path("rennstarts.json")
    if not datei.exists():
        return

    lokal = json.loads(datei.read_text(encoding="utf-8"))

    for datum, daten in lokal.items():
        for renn in rennen.get(datum, []):
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

    print("Hinterlegte Startzeit-Datensaetze:", len(lokal))


def disziplin_erkennen(text):
    text = text.lower()

    if any(w in text for w in (
        "riesentorlauf", "riesenslalom",
        "giant slalom"
    )):
        return "Riesentorlauf"
    if "super-g" in text or "super g" in text:
        return "Super-G"
    if "abfahrt" in text or "downhill" in text:
        return "Abfahrt"
    if re.search(r"\bslalom\b", text):
        return "Slalom"

    return None


def rennen_zuordnen(titel, beschreibung, datum, rennen):
    text = titel + " " + beschreibung
    kandidaten = list(rennen.get(datum, []))

    if not kandidaten:
        return None

    # Damen und Herren nicht miteinander verwechseln.
    damen = bool(DAMEN.search(text))
    herren = bool(HERREN.search(text))

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

    disziplin = disziplin_erkennen(text)
    if disziplin:
        kandidaten = [
            r for r in kandidaten
            if r["disziplin"] == disziplin
        ]

    # Ortsnamen aus der FIS als zusätzliche Hilfe.
    orte = [
        r for r in kandidaten
        if r["ort"].split(" (")[0].lower() in text.lower()
    ]
    if orte:
        kandidaten = orte

    # Nur eindeutig zuordenbare Sendungen übernehmen.
    if len(kandidaten) != 1:
        return None

    return kandidaten[0]


def rennstart_ermitteln(text, renn):
    if ZWEITER.search(text):
        return renn.get("zweiter_lauf")
    if ERSTER.search(text):
        return renn.get("erster_lauf")

    # Ein allgemeiner Vorbericht kann sich auf
    # mehrere Läufe beziehen.
    return None


def zeit_lesen(wert):
    try:
        zeit = datetime.fromisoformat(
            str(wert).replace("Z", "+00:00")
        )
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        return zeit.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def ics_zeit(zeit):
    return zeit.strftime("%Y%m%dT%H%M%SZ")


def ics_text(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def uid_lesen(event):
    return next(
        (
            z[4:] for z in event
            if z.startswith("UID:")
        ),
        None
    )


def bisherige_events():
    if not KALENDER.exists():
        return {}

    events = {}
    block = None

    for zeile in entfalte(
        KALENDER.read_text(encoding="utf-8-sig")
    ):
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
            " | Rennstartzeit offen"
        )

    beschr = (
        "Sender: " + sender
        + "\nORF-Sendebeginn: "
        + beginn.astimezone(WIEN).strftime(
            "%d.%m.%Y %H:%M"
        )
        + " Uhr\nRennstart: "
        + (
            rennstart + " Uhr"
            if rennstart
            else "Noch nicht eindeutig bestätigt"
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


def falten(zeilen):
    ausgabe = []

    for zeile in zeilen:
        teil = ""
        for zeichen in zeile:
            if len(
                (teil + zeichen).encode("utf-8")
            ) > 70:
                ausgabe.append(teil)
                teil = " "
            teil += zeichen
        ausgabe.append(teil)

    return ausgabe


print("ORF Ski-Kalender - verbesserte Erkennung")

rennen, anzahl = fis_lesen()
print("FIS-Termine insgesamt:", anzahl)
print("Renntage:", len(rennen))
print(
    "Erkannte Rennen:",
    sum(len(wert) for wert in rennen.values())
)

startzeiten_ergaenzen(rennen)

events = bisherige_events()
print("Bisherige Zukunftstermine:", len(events))

erfolgreich = 0
neue_termine = 0

for sender, nummer in SENDER.items():
    print("Pruefe:", sender)

    try:
        daten = json.loads(abrufen(
            "https://epg.pw/api/epg.json?"
            "channel_id=" + nummer
        ))

        sendungen = daten.get("epg_list")
        if not isinstance(sendungen, list):
            raise ValueError("Keine Programmliste")

        programm = []

        for sendung in sendungen:
            beginn = zeit_lesen(
                sendung.get("start_date")
            )
            if beginn:
                programm.append((beginn, sendung))

        programm.sort(key=lambda e: e[0])
        erfolgreich += 1
        treffer = 0

        for index, (beginn, sendung) in enumerate(
            programm
        ):
            if beginn < JETZT:
                continue

            titel = str(sendung.get("title") or "")
            beschreibung = str(
                sendung.get("desc") or ""
            )
            text = titel + " " + beschreibung

            # Nur erkennbare Ski-Sendungen.
            # "Traiskirchen" ist KEIN Ski-Treffer.
            if not SKI_MUSTER.search(titel):
                continue

            if AUSSCHLUSS.search(text):
                continue

            # Ohne ausdrücklichen Live-Hinweis
            # keine automatische Übernahme.
            if not LIVE.search(text):
                continue

            datum = beginn.astimezone(
                WIEN
            ).strftime("%Y-%m-%d")

            renn = rennen_zuordnen(
                titel, beschreibung,
                datum, rennen
            )

            if not renn:
                print("Zuordnung unklar:", titel)
                continue

            if index + 1 >= len(programm):
                continue

            ende = programm[index + 1][0]
            if ende <= beginn:
                continue

            rennstart = rennstart_ermitteln(
                text, renn
            )

            event = event_erstellen(
                sender, titel, beschreibung,
                beginn, ende, renn, rennstart
            )

            uid = uid_lesen(event)
            if uid not in events:
                neue_termine += 1

            events[uid] = event
            treffer += 1

            print("Live-Kandidat:", titel)

        print("Zugeordnete Live-Sendungen:", treffer)

    except Exception as fehler:
        print(
            "Senderabruf fehlgeschlagen:",
            sender, repr(fehler)
        )

print("Erfolgreiche Senderabrufe:", erfolgreich)
print("Neue Live-Termine:", neue_termine)
print("Kalendereintraege insgesamt:", len(events))

if erfolgreich != len(SENDER):
    raise RuntimeError(
        "ORF-Abfrage unvollstaendig. "
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
            (
                z for z in e
                if z.startswith("DTSTART:")
            ),
            ""
        )
    ):
        zeilen.extend(event)

    zeilen.append("END:VCALENDAR")

    inhalt = "\r\n".join(
        falten(zeilen)
    ) + "\r\n"

    KALENDER.write_bytes(
        inhalt.encode("utf-8")
    )

    print("Kalenderdatei aktualisiert.")

print("FERTIG")
