import json
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

URL = "https://epg.pw/api/epg.json?channel_id=438442"

SKI_BEGRIFFE = [
    "ski", "alpin", "weltcup", "slalom",
    "riesentorlauf", "riesenslalom",
    "abfahrt", "super-g", "super g"
]

AUSSCHLUSS = [
    "highlights", "zusammenfassung",
    "wiederholung", "rückblick", "rueckblick"
]

print("ORF 1 - Ski-Programm pruefen")

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

    if (
        any(wort in titel_klein for wort in SKI_BEGRIFFE)
        and not any(wort in titel_klein for wort in AUSSCHLUSS)
    ):
        treffer.append(sendung)

print("Moegliche Ski-Sendungen:", len(treffer))

for sendung in treffer[:20]:
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
    print("Sendebeginn (Wien):", zeit)
    print("Titel:", sendung.get("title"))
    print("Beschreibung:",
          str(sendung.get("desc") or "")[:200])

print("TEST BEENDET - Kalender unveraendert")
