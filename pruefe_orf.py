import json
import urllib.request

SENDER = {
    "ORF 1": "438442",
    "ORF SPORT+": "76756",
}

BEGRIFFE = (
    "ski", "weltcup", "sölden", "soelden",
    "slalom", "abfahrt", "super-g",
    "riesentorlauf", "vorbericht",
    "vorberichterstattung",
)

for sender, nummer in SENDER.items():
    print()
    print("SENDER:", sender)

    url = (
        "https://epg.pw/api/epg.json?"
        "channel_id=" + nummer
    )

    anfrage = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(
        anfrage, timeout=30
    ) as antwort:
        daten = json.load(antwort)

    sendungen = daten.get("epg_list", [])
    print("Programmpunkte:", len(sendungen))

    treffer = 0

    for sendung in sendungen:
        titel = str(sendung.get("title") or "")
        beschreibung = str(
            sendung.get("desc") or ""
        )

        # Erst einmal nur den Titel durchsuchen,
        # damit unpassende Treffer seltener sind.
        if not any(
            begriff in titel.lower()
            for begriff in BEGRIFFE
        ):
            continue

        treffer += 1

        print()
        print("Titel:", titel)
        print(
            "Beginn:",
            sendung.get("start_date")
        )
        print(
            "Beschreibung:",
            beschreibung[:300]
        )

    print("Gefundene Ski-Sendungen:", treffer)

print()
print("PRUEFUNG ABGESCHLOSSEN")
