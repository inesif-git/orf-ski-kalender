import json
import urllib.request

URL = "https://epg.pw/api/epg.json?channel_id=76756"

print("ORF Ski-Kalender: Verbindungstest")

try:
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0 ORF-Ski-Kalender-Test"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read()
        print("HTTP-Status:", response.status)
        print("Datenmenge:", len(content), "Bytes")
        data = json.loads(content)
        print("JSON erfolgreich gelesen")
        print("Datentyp:", type(data).__name__)
        if isinstance(data, dict):
            print("Feldnamen:", list(data.keys())[:15])
        elif isinstance(data, list):
            print("Anzahl Eintraege:", len(data))
except Exception as error:
    print("Verbindungstest fehlgeschlagen:", repr(error))
    raise

print("Test abgeschlossen. Kalenderdatei unveraendert.")
