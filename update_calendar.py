import json
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

SENDER = {
    "ORF 1": "438442",
    "ORF SPORT+": "76756",
}

def wiener_zeit(wert):
    if not wert:
        return "nicht vorhanden"

    try:
        zeit = datetime.fromisoformat(
            str(wert).replace("Z", "+00:00")
        )
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=ZoneInfo("UTC"))

        return zeit.astimezone(
            ZoneInfo("Europe/Vienna")
        ).strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return str(wert)

print("ORF - Programmzeitraum pruefen")

for sendername, sendernummer in SENDER.items():
    print("============================")
    print("Pruefe:", sendername)

    url = (
        "https://epg.pw/api/epg.json"
        "?channel_id=" + sendernummer
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

        sendungen = daten.get("epg_list", [])
        print("Sender laut API:", daten.get("name"))
        print("Fehlercode:", daten.get("error_code"))
        print("Anzahl Sendungen:", len(sendungen))
        print("API-Start:", daten.get("start_date"))
        print("API-Ende:", daten.get("end_date"))

        zeiten = []

        for sendung in sendungen:
            wert = sendung.get("start_date")
            if not wert:
                continue

            try:
                zeit = datetime.fromisoformat(
                    str(wert).replace("Z", "+00:00")
                )
                if zeit.tzinfo is None:
                    zeit = zeit.replace(
                        tzinfo=ZoneInfo("UTC")
                    )
                zeiten.append(zeit)
            except ValueError:
                pass

        if zeiten:
            print(
                "Erste Sendung (Wien):",
                wiener_zeit(min(zeiten).isoformat())
            )
            print(
                "Letzter Sendungsbeginn (Wien):",
                wiener_zeit(max(zeiten).isoformat())
            )
        else:
            print("Keine gueltigen Sendezeiten")

    except Exception as fehler:
        print("ABRUF FEHLGESCHLAGEN:", repr(fehler))

print("============================")
print("TEST BEENDET - Kalender unveraendert")
