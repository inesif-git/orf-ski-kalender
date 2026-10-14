
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# FIS-Rennen 2026/27: Uhrzeiten vor Ganztag; ORF LIVE hat Vorrang.
WIEN = ZoneInfo('Europe/Vienna')
JETZT = datetime.now(timezone.utc)
FIS_URL = ('https://www.fis-ski.com/DB/services/public/'
           'icalendar-feed-fis-events.html?seasoncode=2027&sectorcode=AL&categorycode=WC')
SENDER = {'ORF 1': '438442', 'ORF SPORT+': '76756'}
KALENDER = Path('ski-weltcup.ics')
STARTZEITEN = Path('rennstarts.json')


def laden(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode('utf-8-sig', errors='replace')


def entfalten(text):
    result = []
    for line in text.replace('\r\n', '\n').split('\n'):
        if line.startswith((' ', '\t')) and result:
            result[-1] += line[1:]
        else:
            result.append(line)
    return result


def bereinigen(text):
    return str(text).replace('\\n', ' ').replace('\\,', ',').replace('\\;', ';').strip()


def disziplin(text):
    text = text.lower()
    if any(w in text for w in ('giant slalom', 'riesentorlauf', 'riesenslalom')):
        return 'Riesentorlauf'
    if 'super-g' in text or 'super g' in text:
        return 'Super-G'
    if 'downhill' in text or 'abfahrt' in text:
        return 'Abfahrt'
    if re.search(r'\bslalom\b', text):
        return 'Slalom'
    return None


def fis_datum_und_zeit(feld, wert):
    """FIS iCal: DATE bleibt ganztägig; DATE-TIME wird übernommen."""
    raw = wert.strip()
    if 'VALUE=DATE' in feld or re.fullmatch(r'\d{8}', raw):
        return datetime.strptime(raw[:8], '%Y%m%d').date(), None
    try:
        if raw.endswith('Z'):
            zeit = datetime.strptime(raw, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        else:
            zeit = datetime.strptime(raw[:15], '%Y%m%dT%H%M%S').replace(tzinfo=WIEN)
        return zeit.astimezone(WIEN).date(), zeit.astimezone(timezone.utc)
    except ValueError:
        return None, None


def fis_rennen():
    inhalt = laden(FIS_URL)
    if 'BEGIN:VCALENDAR' not in inhalt:
        raise RuntimeError('FIS-Kalender nicht lesbar; bestehende Datei bleibt erhalten')
    bloecke, block = [], None
    for zeile in entfalten(inhalt):
        if zeile == 'BEGIN:VEVENT':
            block = {}
        elif zeile == 'END:VEVENT':
            if block is not None:
                bloecke.append(block)
            block = None
        elif block is not None and ':' in zeile:
            feld, wert = zeile.split(':', 1)
            if feld.startswith('DTSTART'):
                block['startfeld'], block['startwert'] = feld, wert
            elif feld == 'SUMMARY':
                block['titel'] = bereinigen(wert)
            elif feld == 'DESCRIPTION':
                block['beschreibung'] = bereinigen(wert)
    rennen = []
    for eintrag in bloecke:
        datum, fis_zeit = fis_datum_und_zeit(
            eintrag.get('startfeld', ''), eintrag.get('startwert', ''))
        if datum is None:
            continue
        titel = eintrag.get('titel', '')
        beschreibung = eintrag.get('beschreibung', '')
        text = titel + ' ' + beschreibung
        if re.search(r'Gender:\s*Women\b', beschreibung, re.I):
            geschlecht = 'Damen'
        elif re.search(r'Gender:\s*Men\b', beschreibung, re.I):
            geschlecht = 'Herren'
        else:
            continue
        art = disziplin(text)
        if not art:
            continue
        ort = re.split(r'\s+[-–]\s+', titel)[0].strip()
        rennen.append({
            'datum': datum.isoformat(), 'ort': ort, 'disziplin': art,
            'geschlecht': geschlecht, 'fis_zeit': fis_zeit,
            'rennstarts': [], 'sendungen': []})
    if not rennen:
        raise RuntimeError('Keine FIS-Rennen gefunden; bestehende Datei bleibt erhalten')
    return rennen


def uhrzeit_lesen(wert, datum):
    """Erlaubt HH:MM (Wien), ISO-8601 oder Zeit mit Z."""
    if not wert:
        return None
    wert = str(wert).strip()
    if re.fullmatch(r'\d{1,2}:\d{2}', wert):
        hh, mm = map(int, wert.split(':'))
        if hh > 23 or mm > 59:
            return None
        return datetime.fromisoformat(datum).replace(
            hour=hh, minute=mm, tzinfo=WIEN).astimezone(timezone.utc)
    try:
        zeit = datetime.fromisoformat(wert.replace('Z', '+00:00'))
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=WIEN)
        return zeit.astimezone(timezone.utc)
    except ValueError:
        return None


def startzeiten_ergaenzen(rennen):
    """Zusätzliche offiziell geprüfte Zeiten aus rennstarts.json."""
    if not STARTZEITEN.exists():
        return
    daten = json.loads(STARTZEITEN.read_text(encoding='utf-8'))
    for renn in rennen:
        zusatz = daten.get(renn['datum'], {})
        if not isinstance(zusatz, dict):
            continue
        if (zusatz.get('geschlecht') != renn['geschlecht'] or
                zusatz.get('disziplin') != renn['disziplin']):
            continue
        for schluessel in ('erster_lauf', 'zweiter_lauf', 'start', 'startzeit'):
            zeit = uhrzeit_lesen(zusatz.get(schluessel), renn['datum'])
            if zeit and zeit not in renn['rennstarts']:
                renn['rennstarts'].append(zeit)
        renn['rennstarts'].sort()


def programmzeit(wert):
    try:
        zeit = datetime.fromisoformat(str(wert).replace('Z', '+00:00'))
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        return zeit.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def ist_ski(titel):
    return bool(re.search(
        r'\b(?:ski(?:[- ]?alpin|[- ]?weltcup)?|riesentorlauf|'
        r'riesenslalom|slalom|abfahrt|super[- ]?g)\b', titel, re.I))


def ist_live(titel, beschreibung):
    text = titel + ' ' + beschreibung
    if re.search(r'\b(?:wiederholung|highlights?|zusammenfassung|'
                 r'rückblick|rueckblick|replay)\b', text, re.I):
        return False
    return bool(re.search(r'\b(?:live|direkt|liveübertragung|'
                          r'direktübertragung)\b', text, re.I)
                or re.search(r'\bcountdown\b', titel, re.I))


def zuordnen(titel, beschreibung, datum, rennen):
    text = titel + ' ' + beschreibung
    kandidaten = [r for r in rennen if r['datum'] == datum]
    damen = bool(re.search(r'\b(?:damen|frauen|women|ladies)\b', text, re.I))
    herren = bool(re.search(r'\b(?:herren|männer|maenner|men)\b', text, re.I))
    if damen and herren:
        return None
    if damen:
        kandidaten = [r for r in kandidaten if r['geschlecht'] == 'Damen']
    if herren:
        kandidaten = [r for r in kandidaten if r['geschlecht'] == 'Herren']
    art = disziplin(text)
    if art:
        kandidaten = [r for r in kandidaten if r['disziplin'] == art]
    mit_ort = [r for r in kandidaten if r['ort'].lower() in text.lower()]
    if mit_ort:
        kandidaten = mit_ort
    return kandidaten[0] if len(kandidaten) == 1 else None


def orf_ergaenzen(rennen):
    for sender, nummer in SENDER.items():
        try:
            daten = json.loads(laden('https://epg.pw/api/epg.json?channel_id=' + nummer))
            sendungen = daten.get('epg_list')
            if not isinstance(sendungen, list):
                raise ValueError('Programmliste fehlt')
            programm = []
            for sendung in sendungen:
                beginn = programmzeit(sendung.get('start_date'))
                if beginn:
                    programm.append((beginn, sendung))
            programm.sort(key=lambda x: x[0])
            treffer = 0
            for i, (beginn, sendung) in enumerate(programm[:-1]):
                titel = str(sendung.get('title') or '')
                beschreibung = str(sendung.get('desc') or '')
                if not ist_ski(titel) or not ist_live(titel, beschreibung):
                    continue
                datum = beginn.astimezone(WIEN).date().isoformat()
                renn = zuordnen(titel, beschreibung, datum, rennen)
                ende = programm[i + 1][0]
                if renn is None or ende <= beginn:
                    continue
                renn['sendungen'].append({
                    'beginn': beginn, 'ende': ende, 'sender': sender, 'titel': titel})
                treffer += 1
            print(sender, '- passende Sendungen:', treffer)
        except Exception as fehler:
            print('ORF momentan nicht verfügbar:', sender, str(fehler))


def ics_text(wert):
    return (str(wert).replace('\\', '\\\\').replace('\n', '\\n')
            .replace(',', '\\,').replace(';', '\\;'))


def utc_format(zeit):
    return zeit.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def zeilen_falten(zeilen):
    ergebnis = []
    for zeile in zeilen:
        teil = ''
        for zeichen in zeile:
            if len((teil + zeichen).encode('utf-8')) > 70:
                ergebnis.append(teil)
                teil = ' '
            teil += zeichen
        ergebnis.append(teil)
    return ergebnis


def kalender_schreiben(rennen):
    zeilen = [
        'BEGIN:VCALENDAR', 'VERSION:2.0',
        'PRODID:-//ORF Ski Kalender//DE', 'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH', 'X-WR-CALNAME:ORF Ski-Weltcup LIVE',
    ]
    zaehler = {'ORF': 0, 'FIS/Startzeiten': 0, 'Ganztag': 0}
    for nummer, renn in enumerate(rennen):
        datum = datetime.fromisoformat(renn['datum']).date()
        # Gleiche UID-Logik wie in der bisherigen Datei: bestehende
        # Apple-Kalendereinträge werden aktualisiert statt dupliziert.
        identitaet = '|'.join((renn['datum'], renn['geschlecht'],
                               renn['disziplin'], renn['ort'], str(nummer)))
        uid = hashlib.sha256(identitaet.encode('utf-8')).hexdigest()[:24] + '@orf-ski-kalender'
        titel = '🎿 ' + renn['ort'] + ' – ' + renn['disziplin'] + ' ' + renn['geschlecht']
        beschreibung = 'Offizieller FIS-Weltcuptermin 2026/27.'
        starts = renn['rennstarts'][:]
        if renn['fis_zeit'] and renn['fis_zeit'] not in starts:
            starts.append(renn['fis_zeit'])
        starts.sort()
        if starts:
            beschreibung += '\nRennstarts (Wien): ' + ', '.join(
                t.astimezone(WIEN).strftime('%H:%M') + ' Uhr' for t in starts)
        if renn['sendungen']:
            beginn = min(s['beginn'] for s in renn['sendungen'])
            ende = max(s['ende'] for s in renn['sendungen'])
            sender = ', '.join(sorted({s['sender'] for s in renn['sendungen']}))
            titel += ' | ORF LIVE'
            beschreibung += ('\nORF-Sendebeginn: ' + beginn.astimezone(WIEN).strftime('%d.%m.%Y %H:%M')
                             + ' Uhr\nSender: ' + sender)
            zeitzeilen = ['DTSTART:' + utc_format(beginn), 'DTEND:' + utc_format(ende)]
            zaehler['ORF'] += 1
        elif starts:
            beginn = starts[0]
            # Bei mehreren Läufen bis 90 Minuten nach letztem Start;
            # sonst ein vorläufiges 2-Stunden-Fenster.
            ende = max(starts[-1] + timedelta(minutes=90), beginn + timedelta(hours=2))
            titel += ' | Rennstart ' + beginn.astimezone(WIEN).strftime('%H:%M') + ' Uhr'
            beschreibung += '\nORF-Sendezeit noch nicht bekannt. Dauer vorläufig.'
            zeitzeilen = ['DTSTART:' + utc_format(beginn), 'DTEND:' + utc_format(ende)]
            zaehler['FIS/Startzeiten'] += 1
        else:
            titel += ' | vorläufig'
            beschreibung += '\nNoch keine bestätigte Start- oder ORF-Sendezeit.'
            zeitzeilen = ['DTSTART;VALUE=DATE:' + datum.strftime('%Y%m%d'),
                          'DTEND;VALUE=DATE:' + (datum + timedelta(days=1)).strftime('%Y%m%d')]
            zaehler['Ganztag'] += 1
        zeilen.extend(['BEGIN:VEVENT', 'UID:' + uid, 'DTSTAMP:' + utc_format(JETZT),
                       *zeitzeilen, 'SUMMARY:' + ics_text(titel),
                       'DESCRIPTION:' + ics_text(beschreibung), 'END:VEVENT'])
    zeilen.append('END:VCALENDAR')
    KALENDER.write_bytes(('\r\n'.join(zeilen_falten(zeilen)) + '\r\n').encode('utf-8'))
    print('Kalendereinträge:', len(rennen))
    for k, v in zaehler.items():
        print(k + ':', v)
    print('FERTIG')


if __name__ == '__main__':
    print('Erstelle Saisonkalender mit FIS- und ORF-Zeiten')
    rennen = fis_rennen()
    print('FIS-Rennen gefunden:', len(rennen))
    startzeiten_ergaenzen(rennen)
    orf_ergaenzen(rennen)
    kalender_schreiben(rennen)
