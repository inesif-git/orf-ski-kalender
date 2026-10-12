import json
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

URL = "https://epg.pw/api/epg.json?channel_id=76756"

SKI_BEGRIFFE = [
    "ski alpin", "ski-alpin", "skiweltcup",
    "ski-weltcup", "alpiner weltcup",
    "slalom", "riesentorlauf", "riesenslalom",
    "abfahrt", "super-g", "super g",
    "ski: weltcup", "ski weltcup"
]

AUSSCHLUSS = [
    "silent sports", "sport 20",
    "sport aktuell", "sportbild",
    "wiederholung", "highlights",
    "zusammenfassung", "rueckblick", "rückblick"
]

print("ORF SPORT+ - gezielte Ski-Suche")

request = urllib.request.Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urllib.request.urlopen(request, timeout=30) as response:
    data = json.load(response)

sendungen = data.get("epg_list", [])

print("Sender:", data.get("name"))
print("API-Fehlercode:", data.get("error_code"))
print("Sendungen insgesamt:", len(sendungen))

treffer = []

for sendung in sendungen:
    titel = str(sendung.get("title") or "")
    titel_klein = titel.lower()

    ist_ski = any(
        wort in titel_klein for wort in SKI_BEGRIFFE
    )
    ist_ausgeschlossen = any(
        wort in titel_klein for wort in AUSSCHLUSS
    )

    if ist_ski and not ist_ausgeschlossen:
        treffer.append(sendung)

print("Moegliche Ski-Rennsendungen:", len(treffer))

for sendung in treffer:
    zeit = str(sendung.get("start_date") or "")
    try:
        dt = datetime.fromisoformat(
            zeit.replace("Z", "+00:00")
        )
        zeit = dt.astimezone(
            ZoneInfo("Europe/Vienna")
        ).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        pass

    print("-------------------------")
    print("ORF-Sendebeginn (Wien):", zeit)
    print("Titel:", sendung.get("title"))
    print(
        "Beschreibung:",
        str(sendung.get("desc") or "")[:250]
    )

print("TEST BEENDET - Kalender unveraendert")
