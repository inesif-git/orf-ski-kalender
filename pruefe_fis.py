import urllib.request
from datetime import datetime

URL = (
    "https://www.fis-ski.com/DB/services/public/"
    "icalendar-feed-fis-events.html?"
    "seasoncode=2027&sectorcode=AL&categorycode=WC"
)

anfrage = urllib.request.Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urllib.request.urlopen(anfrage, timeout=30) as antwort:
    inhalt = antwort.read().decode("utf-8-sig", errors="replace")
    print("HTTP-Status:", antwort.status)
    print("Inhaltstyp:", antwort.headers.get("Content-Type"))

zeilen = inhalt.replace("\r\n", "\n").split("\n")

# Mehrzeilige iCal-Felder zusammensetzen.
verbunden = []
for zeile in zeilen:
    if zeile.startswith((" ", "\t")) and verbunden:
        verbunden[-1] += zeile[1:]
    else:
        verbunden.append(zeile)

termine = []
termin = None

for zeile in verbunden:
    if zeile == "BEGIN:VEVENT":
        termin = {}
    elif zeile == "END:VEVENT" and termin is not None:
        termine.append(termin)
        termin = None
    elif termin is not None and ":" in zeile:
        schluessel, wert = zeile.split(":", 1)
        if schluessel.startswith("DTSTART"):
            termin["Start"] = wert
            termin["Startfeld"] = schluessel
        elif schluessel.startswith("SUMMARY"):
            termin["Titel"] = wert
        elif schluessel.startswith("DESCRIPTION"):
            termin["Beschreibung"] = wert[:160]

print("FIS-Termine insgesamt:", len(termine))
print()
print("ERSTE 12 TERMINE:")

for nummer, termin in enumerate(termine[:12], 1):
    print()
    print("Termin", nummer)
    print("Titel:", termin.get("Titel", "FEHLT"))
    print("Startfeld:", termin.get("Startfeld", "FEHLT"))
    print("Startwert:", termin.get("Start", "FEHLT"))
    print("Beschreibung:", termin.get("Beschreibung", ""))

print()
print("PRUEFUNG ABGESCHLOSSEN")
