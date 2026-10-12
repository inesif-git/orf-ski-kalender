import json
import urllib.request

URL = "https://epg.pw/api/epg.json?channel_id=76756"

print("ORF SPORT+ - Sendungsdaten pruefen")

request = urllib.request.Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urllib.request.urlopen(request, timeout=30) as response:
    data = json.load(response)

print("Fehlercode:", data.get("error_code"))
print("Fehlermeldung:", data.get("error_message"))
print("Sender:", data.get("name"))
print("Zeitzone:", data.get("timezone"))

sendungen = data.get("epg_list", [])

if not isinstance(sendungen, list):
    raise ValueError("epg_list ist keine Liste")

print("Anzahl Sendungen:", len(sendungen))

if not sendungen:
    print("Keine Sendungen in der Antwort gefunden.")
else:
    print("Felder der ersten Sendung:")
    print(list(sendungen[0].keys()))

    print("Erste 5 Sendungen:")
    for nummer, sendung in enumerate(sendungen[:5], 1):
        print("Sendung", nummer)
        print(json.dumps(
            sendung,
            ensure_ascii=False,
            indent=2
        )[:1200])

print("TEST BEENDET - Kalender unveraendert")
