
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WIEN = ZoneInfo('Europe/Vienna')
JETZT = datetime.now(timezone.utc)

FIS_URL = (
    'https://www.fis-ski.com/DB/services/public/'
    'icalendar-feed-fis-events.html?'
    'seasoncode=2027&sectorcode=AL&categorycode=WC'
)

SENDER = {
    'ORF 1': '438442',
    'ORF SPORT+': '76756'
}

KALENDER = Path('ski-weltcup.ics')
STARTZEITEN = Path('rennstarts.json')

# Alpine Ski-WM Crans-Montana 2027
# Offizielles Rennprogramm
# Uhrzeiten in Österreich und der Schweiz: MEZ

WM_PLAN = [
    ('2027-02-01', 'Team-Parallel Mixed', 'Mixed', ['11:15']),
    ('2027-02-04', 'Super-G', 'Damen', ['11:15']),
    ('2027-02-05', 'Super-G', 'Herren', ['11:15']),
    ('2027-02-06', 'Abfahrt', 'Damen', ['11:15']),
    ('2027-02-07', 'Abfahrt', 'Herren', ['11:15']),
    ('2027-02-09', 'Team-Kombination', 'Damen', ['10:00', '13:30']),
    ('2027-02-10', 'Team-Kombination', 'Herren', ['10:00', '13:30']),
    ('2027-02-11', 'Riesentorlauf', 'Damen', ['10:00', '13:30']),
    ('2027-02-12', 'Riesentorlauf', 'Herren', ['10:00', '13:30']),
    ('2027-02-13', 'Slalom', 'Damen', ['10:00', '13:30']),
    ('2027-02-14', 'Slalom', 'Herren', ['10:00', '13:30']),
]


def laden(url):
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0'}
    )

    with urllib.request.urlopen(
        req, timeout=30
    ) as response:
        return response.read().decode(
            'utf-8-sig', errors='replace'
        )


def entfalten(text):
    lines = []

    for line in text.replace('\r\n', '\n').split('\n'):
        if line.startswith((' ', '\t')) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)

    return lines


def bereinigen(text):
    return (
        str(text)
        .replace('\\n', ' ')
        .replace('\\,', ',')
        .replace('\\;', ';')
        .strip()
    )


def disziplin(text):
    text = text.lower()

    if any(w in text for w in (
        'giant slalom',
        'riesentorlauf',
        'riesenslalom'
    )):
        return 'Riesentorlauf'

    if 'super-g' in text or 'super g' in text:
        return 'Super-G'

    if 'downhill' in text or 'abfahrt' in text:
        return 'Abfahrt'

    if re.search(r'\bslalom\b', text):
        return 'Slalom'

    return None


def fis_datum_und_zeit(feld, wert):
    wert = wert.strip()

    if (
        'VALUE=DATE' in feld
        or re.fullmatch(r'\d{8}', wert)
    ):
        return (
            datetime.strptime(
                wert[:8], '%Y%m%d'
            ).date(),
            None
        )

    try:
        if wert.endswith('Z'):
            zeit = datetime.strptime(
                wert, '%Y%m%dT%H%M%SZ'
            ).replace(tzinfo=timezone.utc)
        else:
            zeit = datetime.strptime(
                wert[:15], '%Y%m%dT%H%M%S'
            ).replace(tzinfo=WIEN)

        return (
            zeit.astimezone(WIEN).date(),
            zeit.astimezone(timezone.utc)
        )

    except ValueError:
        return None, None


def fis_rennen():
    inhalt = laden(FIS_URL)

    if 'BEGIN:VCALENDAR' not in inhalt:
        raise RuntimeError(
            'FIS-Kalender nicht lesbar; '
            'alte Datei bleibt erhalten'
        )

    bloecke = []
    block = None

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
                block['startfeld'] = feld
                block['startwert'] = wert

            elif feld == 'SUMMARY':
                block['titel'] = bereinigen(wert)

            elif feld == 'DESCRIPTION':
                block['beschreibung'] = bereinigen(wert)

    rennen = []

    for e in bloecke:
        datum, fis_zeit = fis_datum_und_zeit(
            e.get('startfeld', ''),
            e.get('startwert', '')
        )

        if datum is None:
            continue

        titel = e.get('titel', '')
        beschreibung = e.get('beschreibung', '')

        if re.search(
            r'Gender:\s*Women\b',
            beschreibung,
            re.I
        ):
            geschlecht = 'Damen'

        elif re.search(
            r'Gender:\s*Men\b',
            beschreibung,
            re.I
        ):
            geschlecht = 'Herren'

        else:
            continue

        art = disziplin(
            titel + ' ' + beschreibung
        )

        if not art:
            continue

        ort = re.split(
            r'\s+[-–]\s+', titel
        )[0].strip()

        rennen.append({
            'datum': datum.isoformat(),
            'ort': ort,
            'disziplin': art,
            'geschlecht': geschlecht,
            'fis_zeit': fis_zeit,
            'rennstarts': [],
            'sendungen': [],
            'wm': False
        })

    if not rennen:
        raise RuntimeError(
            'Keine FIS-Weltcuprennen gefunden; '
            'alte Datei bleibt erhalten'
        )

    return rennen


def uhrzeit_lesen(wert, datum):
    if not wert:
        return None

    wert = str(wert).strip()

    if re.fullmatch(r'\d{1,2}:\d{2}', wert):
        hh, mm = map(int, wert.split(':'))

        if hh > 23 or mm > 59:
            return None

        return datetime.fromisoformat(
            datum
        ).replace(
            hour=hh,
            minute=mm,
            tzinfo=WIEN
        ).astimezone(timezone.utc)

    try:
        zeit = datetime.fromisoformat(
            wert.replace('Z', '+00:00')
        )

        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=WIEN)

        return zeit.astimezone(timezone.utc)

    except ValueError:
        return None


def startzeiten_ergaenzen(rennen):
    if not STARTZEITEN.exists():
        return

    daten = json.loads(
        STARTZEITEN.read_text(
            encoding='utf-8'
        )
    )

    for renn in rennen:
        zusatz = daten.get(
            renn['datum'], {}
        )

        if not isinstance(zusatz, dict):
            continue

        if (
            zusatz.get('geschlecht')
            != renn['geschlecht']
            or zusatz.get('disziplin')
            != renn['disziplin']
        ):
            continue

        for key in (
            'erster_lauf',
            'zweiter_lauf',
            'start',
            'startzeit'
        ):
            zeit = uhrzeit_lesen(
                zusatz.get(key),
                renn['datum']
            )

            if (
                zeit
                and zeit not in renn['rennstarts']
            ):
                renn['rennstarts'].append(zeit)

        renn['rennstarts'].sort()


def wm_ergaenzen(rennen):
    for (
        datum,
        art,
        geschlecht,
        uhrzeiten
    ) in WM_PLAN:

        rennen.append({
            'datum': datum,
            'ort': 'Crans-Montana',
            'disziplin': art,
            'geschlecht': geschlecht,
            'fis_zeit': None,
            'rennstarts': [
                uhrzeit_lesen(z, datum)
                for z in uhrzeiten
            ],
            'sendungen': [],
            'wm': True
        })


def programmzeit(wert):
    try:
        zeit = datetime.fromisoformat(
            str(wert).replace(
                'Z', '+00:00'
            )
        )

        if zeit.tzinfo is None:
            zeit = zeit.replace(
                tzinfo=timezone.utc
            )

        return zeit.astimezone(timezone.utc)

    except (TypeError, ValueError):
        return None


def ist_ski(titel):
    return bool(re.search(
        r'\b(?:ski(?:[- ]?alpin|[- ]?weltcup)?|'
        r'riesentorlauf|riesenslalom|'
        r'slalom|abfahrt|super[- ]?g|'
        r'team[- ]?kombination|'
        r'team[- ]?parallel)\b',
        titel,
        re.I
    ))


def ist_live(titel, beschreibung):
    text = titel + ' ' + beschreibung

    if re.search(
        r'\b(?:wiederholung|highlights?|'
        r'zusammenfassung|rückblick|'
        r'rueckblick|replay)\b',
        text,
        re.I
    ):
        return False

    return bool(
        re.search(
            r'\b(?:live|direkt|'
            r'liveübertragung|'
            r'direktübertragung)\b',
            text,
            re.I
        )
        or re.search(
            r'\bcountdown\b',
            titel,
            re.I
        )
        or re.search(
            r'\b(?:1\.|2\.)\s*'
            r'(?:durchgang|lauf)\b',
            titel,
            re.I
        )
    )


def durchgang_erkennen(text):
    if re.search(
        r'\b(?:1\.|erster|erste)\s*'
        r'(?:durchgang|lauf)\b',
        text,
        re.I
    ):
        return 1

    if re.search(
        r'\b(?:2\.|zweiter|zweite)\s*'
        r'(?:durchgang|lauf)\b',
        text,
        re.I
    ):
        return 2

    return None


def zuordnen(
    titel,
    beschreibung,
    datum,
    rennen
):
    text = titel + ' ' + beschreibung

    kandidaten = [
        r for r in rennen
        if r['datum'] == datum
    ]

    damen = bool(re.search(
        r'\b(?:damen|frauen|'
        r'women|ladies)\b',
        text,
        re.I
    ))

    herren = bool(re.search(
        r'\b(?:herren|männer|'
        r'maenner|men)\b',
        text,
        re.I
    ))

    if damen and herren:
        return None

    if damen:
        kandidaten = [
            r for r in kandidaten
            if r['geschlecht'] == 'Damen'
        ]

    if herren:
        kandidaten = [
            r for r in kandidaten
            if r['geschlecht'] == 'Herren'
        ]

    art = disziplin(text)

    if re.search(
        r'team[- ]?kombination|'
        r'team combined',
        text,
        re.I
    ):
        art = 'Team-Kombination'

    elif re.search(
        r'team[- ]?parallel|'
        r'mixed team|team event',
        text,
        re.I
    ):
        art = 'Team-Parallel Mixed'

    if art:
        kandidaten = [
            r for r in kandidaten
            if r['disziplin'] == art
        ]

    mit_ort = [
        r for r in kandidaten
        if r['ort'].lower()
        in text.lower()
    ]

    if mit_ort:
        kandidaten = mit_ort

    return (
        kandidaten[0]
        if len(kandidaten) == 1
        else None
    )


def orf_ergaenzen(rennen):
    for sender, nummer in SENDER.items():
        try:
            daten = json.loads(laden(
                'https://epg.pw/api/epg.json?'
                'channel_id=' + nummer
            ))

            sendungen = daten.get(
                'epg_list'
            )

            if not isinstance(
                sendungen, list
            ):
                raise ValueError(
                    'Programmliste fehlt'
                )

            programm = []

            for sendung in sendungen:
                beginn = programmzeit(
                    sendung.get('start_date')
                )

                if beginn:
                    programm.append(
                        (beginn, sendung)
                    )

            programm.sort(
                key=lambda x: x[0]
            )

            treffer = 0

            for i, (
                beginn, sendung
            ) in enumerate(
                programm[:-1]
            ):
                titel = str(
                    sendung.get('title') or ''
                )

                beschreibung = str(
                    sendung.get('desc') or ''
                )

                if not ist_ski(titel):
                    continue

                if not ist_live(
                    titel, beschreibung
                ):
                    continue

                datum = beginn.astimezone(
                    WIEN
                ).date().isoformat()

                renn = zuordnen(
                    titel,
                    beschreibung,
                    datum,
                    rennen
                )

                ende = programm[i + 1][0]

                if (
                    renn is None
                    or ende <= beginn
                ):
                    continue

                renn['sendungen'].append({
                    'beginn': beginn,
                    'ende': ende,
                    'sender': sender,
                    'titel': titel,
                    'durchgang': (
                        durchgang_erkennen(
                            titel + ' '
                            + beschreibung
                        )
                    )
                })

                treffer += 1

            print(
                sender,
                '- passende Sendungen:',
                treffer
            )

        except Exception as fehler:
            print(
                'ORF momentan nicht verfügbar:',
                sender,
                str(fehler)
            )


def ics_text(wert):
    return (
        str(wert)
        .replace('\\', '\\\\')
        .replace('\n', '\\n')
        .replace(',', '\\,')
        .replace(';', '\\;')
    )


def utc_format(zeit):
    return zeit.astimezone(
        timezone.utc
    ).strftime('%Y%m%dT%H%M%SZ')


def zeilen_falten(zeilen):
    ergebnis = []

    for zeile in zeilen:
        teil = ''

        for zeichen in zeile:
            if len(
                (teil + zeichen).encode(
                    'utf-8'
                )
            ) > 70:
                ergebnis.append(teil)
                teil = ' '

            teil += zeichen

        ergebnis.append(teil)

    return ergebnis


def uid_fuer_rennen(renn, nummer):
    if renn['wm']:
        identitaet = '|'.join((
            'WM2027',
            renn['datum'],
            renn['geschlecht'],
            renn['disziplin']
        ))

    else:
        # Bestehende Weltcup-UIDs
        # bleiben unverändert.
        identitaet = '|'.join((
            renn['datum'],
            renn['geschlecht'],
            renn['disziplin'],
            renn['ort'],
            str(nummer)
        ))

    return (
        hashlib.sha256(
            identitaet.encode('utf-8')
        ).hexdigest()[:24]
        + '@orf-ski-kalender'
    )


def rennlaeufe(renn):
    starts = sorted(set(
        renn['rennstarts']
    ))

    if (
        not starts
        and renn['fis_zeit']
    ):
        starts = [
            renn['fis_zeit']
        ]

    if renn['disziplin'] in (
        'Slalom',
        'Riesentorlauf',
        'Team-Kombination'
    ):
        if len(starts) >= 2:
            return [
                {
                    'nummer': 1,
                    'start': starts[0]
                },
                {
                    'nummer': 2,
                    'start': starts[1]
                }
            ]

        if starts:
            return [{
                'nummer': 1,
                'start': starts[0]
            }]

        return [{
            'nummer': 1,
            'start': None
        }]

    return [{
        'nummer': None,
        'start': (
            starts[0]
            if starts
            else None
        )
    }]


def sendungen_aufteilen(
    renn,
    laeufe
):
    zuordnung = {
        lauf['nummer']: []
        for lauf in laeufe
    }

    for sendung in renn['sendungen']:
        nummer = sendung['durchgang']

        if nummer in zuordnung:
            zuordnung[nummer].append(
                sendung
            )
            continue

        if len(laeufe) == 1:
            zuordnung[
                laeufe[0]['nummer']
            ].append(sendung)
            continue

        kandidaten = []

        for lauf in laeufe:
            if lauf['start'] is None:
                continue

            abstand = (
                lauf['start']
                - sendung['beginn']
            ).total_seconds() / 60

            if -30 <= abstand <= 90:
                kandidaten.append((
                    abs(abstand),
                    lauf['nummer']
                ))

        kandidaten.sort()

        if kandidaten and (
            len(kandidaten) == 1
            or kandidaten[0][0]
            != kandidaten[1][0]
        ):
            zuordnung[
                kandidaten[0][1]
            ].append(sendung)

    return zuordnung


def kalender_schreiben(rennen):
    zeilen = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//ORF Ski Kalender//DE',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:ORF Ski-Weltcup LIVE'
    ]

    statistik = {
        'ORF': 0,
        'Rennstart': 0,
        'Ganztag': 0,
        'WM-Einträge': 0
    }

    for nummer, renn in enumerate(
        rennen
    ):
        datum = datetime.fromisoformat(
            renn['datum']
        ).date()

        basis_uid = uid_fuer_rennen(
            renn,
            nummer
        )

        laeufe = rennlaeufe(renn)

        sendungen = sendungen_aufteilen(
            renn,
            laeufe
        )

        for lauf in laeufe:
            laufnummer = lauf['nummer']
            start = lauf['start']

            if laufnummer == 2:
                uid = basis_uid.replace(
                    '@orf-ski-kalender',
                    '-lauf2@orf-ski-kalender'
                )
            else:
                uid = basis_uid

            titel = (
                '🏆 Ski-WM 2027 – '
                if renn['wm']
                else (
                    '🎿 '
                    + renn['ort']
                    + ' – '
                )
            )

            titel += (
                renn['disziplin']
                + ' '
                + renn['geschlecht']
            )

            if laufnummer is not None:
                if (
                    renn['disziplin']
                    == 'Team-Kombination'
                ):
                    titel += (
                        ' | Abfahrt'
                        if laufnummer == 1
                        else ' | Slalom'
                    )
                else:
                    titel += (
                        ' | '
                        + str(laufnummer)
                        + '. Durchgang'
                    )

            beschreibung = (
                'Alpine Ski-WM '
                'Crans-Montana 2027.'
                if renn['wm']
                else (
                    'FIS Ski-Weltcup '
                    '2026/27.'
                )
            )

            if start:
                beschreibung += (
                    '\nOffizieller Rennstart: '
                    + start.astimezone(
                        WIEN
                    ).strftime('%H:%M')
                    + ' Uhr'
                )

            passende = sendungen.get(
                laufnummer,
                []
            )

            if passende:
                beginn = min(
                    s['beginn']
                    for s in passende
                )

                ende = max(
                    s['ende']
                    for s in passende
                )

                sender = ', '.join(sorted({
                    s['sender']
                    for s in passende
                }))

                titel += ' | ORF LIVE'

                beschreibung += (
                    '\nORF-Sendebeginn: '
                    + beginn.astimezone(
                        WIEN
                    ).strftime('%H:%M')
                    + ' Uhr'
                    + '\nSender: '
                    + sender
                )

                zeitzeilen = [
                    'DTSTART:'
                    + utc_format(beginn),
                    'DTEND:'
                    + utc_format(ende)
                ]

                statistik['ORF'] += 1

            elif start:
                ende = (
                    start
                    + timedelta(minutes=90)
                )

                titel += (
                    ' | Start '
                    + start.astimezone(
                        WIEN
                    ).strftime('%H:%M')
                    + ' Uhr'
                )

                beschreibung += (
                    '\nORF-Sendezeit '
                    'noch nicht erkannt. '
                    'Dauer vorläufig.'
                )

                zeitzeilen = [
                    'DTSTART:'
                    + utc_format(start),
                    'DTEND:'
                    + utc_format(ende)
                ]

                statistik['Rennstart'] += 1

            else:
                titel += ' | vorläufig'

                beschreibung += (
                    '\nNoch keine '
                    'bestätigte Startzeit.'
                )

                zeitzeilen = [
                    'DTSTART;VALUE=DATE:'
                    + datum.strftime(
                        '%Y%m%d'
                    ),
                    'DTEND;VALUE=DATE:'
                    + (
                        datum
                        + timedelta(days=1)
                    ).strftime('%Y%m%d')
                ]

                statistik['Ganztag'] += 1

            if renn['wm']:
                statistik['WM-Einträge'] += 1

            zeilen.extend([
                'BEGIN:VEVENT',
                'UID:' + uid,
                'DTSTAMP:'
                + utc_format(JETZT),
                *zeitzeilen,
                'SUMMARY:'
                + ics_text(titel),
                'DESCRIPTION:'
                + ics_text(
                    beschreibung
                ),
                'END:VEVENT'
            ])

    zeilen.append(
        'END:VCALENDAR'
    )

    inhalt = (
        '\r\n'.join(
            zeilen_falten(zeilen)
        )
        + '\r\n'
    )

    KALENDER.write_bytes(
        inhalt.encode('utf-8')
    )

    gesamt = (
        statistik['ORF']
        + statistik['Rennstart']
        + statistik['Ganztag']
    )

    print(
        'Kalendereinträge:',
        gesamt
    )

    for key, value in statistik.items():
        print(
            key + ':',
            value
        )

    print('FERTIG')


if __name__ == '__main__':
    print(
        'Erstelle Weltcup- und '
        'Ski-WM-Kalender 2026/27'
    )

    rennen = fis_rennen()

    print(
        'FIS-Weltcuprennen gefunden:',
        len(rennen)
    )

    startzeiten_ergaenzen(rennen)
    wm_ergaenzen(rennen)
    orf_ergaenzen(rennen)
    kalender_schreiben(rennen)
