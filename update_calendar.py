import json
import re
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

URL = "https://epg.pw/api/epg.json?channel_id=76756"

SUCHBEGRIFFE = [
    "ski", "alpin", "weltcup", "slalom",
    "abfahrt", "super-g", "riesentorlauf",
    "riesenslalom", "skiweltcup"
]

print("ORF SPORT+ - Ski-Sendungen suchen")

request = urllib.request.Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urllib.request.urlopen(request, timeout=30) as response:
    data = json.load(response)

print("Sender:", data.get("name"))
print("API-Fehlercode:", data.get("error_code"))

sendungen = data.get("epg_list", [])
print("Sendungen insgesamt:", len(sendungen))

treffer = []

for sendung in sendungen:
    titel = str(sendung.get("title") or "")
    beschreibung = str(sendung.get("desc") or "")
    text = (titel + " " + beschreibung).lower()

    if any(wort in text for wort in SUCHBEGRIFFE):
        treffer.append(sendung)

print("Moegliche Ski-Sendungen:", len(treffer))

for sendung in treffer[:30]:
    zeit = str(sendung.get("start_date") or "")
    try:
        dt = datetime.fromisoformat(zeit.replace("Z", "+00:00"))
        zeit = dt.astimezone(
            ZoneInfo("Europe/Vienna")
        ).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        pass

    print("-------------------------")
    print("Beginn (Wien):", zeit)
    print("Titel:", sendung.get("title"))
    print("Beschreibung:",
          str(sendung.get("desc") or "")[:200])

print("TEST BEENDET - Kalender unveraendert")
