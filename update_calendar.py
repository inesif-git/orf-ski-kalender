
import hashlib
import html
import json
import re
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Vienna')
NOW = datetime.now(timezone.utc)
TODAY = NOW.astimezone(TZ).date()
OUTPUT = Path('ski-weltcup.ics')
START_FILE = Path('rennstarts.json')
FIS = ('https://www.fis-ski.com/DB/services/public/'
       'icalendar-feed-fis-events.html?seasoncode=2027&sectorcode=AL&categorycode=WC')
ORF = 'https://sport.orf.at/'
WM = [
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

# Sicherheitswerte für die bestätigten Sölden-Übertragungen.
# Nur verwenden, wenn das Rennen vorhanden ist.
SOELDEN = {
    ('2026-10-24', 'Damen', 1): '09:30',
    ('2026-10-24', 'Damen', 2): '12:45',
    ('2026-10-25', 'Herren', 1): '09:25',
    ('2026-10-25', 'Herren', 2): '12:35',
}

MONTHS = dict(zip(
    ('janner', 'januar', 'februar', 'marz', 'april', 'mai',
     'juni', 'juli', 'august', 'september', 'oktober',
     'november', 'dezember'),
    (1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
))


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read().decode(
            'utf-8-sig', errors='replace'
        )


def norm(s):
    s = unicodedata.normalize('NFKD', str(s).casefold())
    s = ''.join(
        c for c in s
        if not unicodedata.combining(c)
    )
    s = (
        s.replace('ß', 'ss')
        .replace('oe', 'o')
        .replace('ae', 'a')
        .replace('ue', 'u')
    )
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def discipline(s):
    s = norm(s)

    if 'team kombination' in s or 'team combined' in s:
        return 'Team-Kombination'

    if any(x in s for x in (
        'team parallel', 'mixed team', 'team event'
    )):
        return 'Team-Parallel Mixed'

    if any(x in s for x in (
        'giant slalom', 'riesentorlauf', 'riesenslalom'
    )):
        return 'Riesentorlauf'

    if 'super g' in s:
        return 'Super-G'

    if 'downhill' in s or 'abfahrt' in s:
        return 'Abfahrt'

    if re.search(r'\bslalom\b', s):
        return 'Slalom'

    return None


def clock(s, day):
    if s is None:
        return None

    s = str(s).strip()

    if re.fullmatch(r'\d{1,2}[:.]\d{2}', s):
        h, m = [
            int(x) for x in re.split('[:.]', s)
        ]

        if h > 23 or m > 59:
            return None

        return datetime.fromisoformat(day).replace(
            hour=h,
            minute=m,
            tzinfo=TZ
        ).astimezone(timezone.utc)

    try:
        t = datetime.fromisoformat(
            s.replace('Z', '+00:00')
        )
        return (
            t if t.tzinfo
            else t.replace(tzinfo=TZ)
        ).astimezone(timezone.utc)

    except ValueError:
        return None


def unfold(text):
    lines = []

    for line in text.replace(
        '\r\n', '\n'
    ).split('\n'):
        if line.startswith((' ', '\t')) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)

    return lines


def vevents(text):
    events = []
    item = None

    for line in unfold(text):
        if line == 'BEGIN:VEVENT':
            item = {}

        elif line == 'END:VEVENT':
            if item is not None:
                events.append(item)
            item = None

        elif item is not None and ':' in line:
            key, val = line.split(':', 1)

            if key.startswith('DTSTART'):
                item['DTSTART'] = val

            elif key in (
                'SUMMARY',
                'DESCRIPTION',
                'UID',
                'X-ORF-RACE-ID'
            ):
                item[key] = (
                    val.replace('\\,', ',')
                    .replace('\\n', ' ')
                )

    return events


def new_race(day, venue, event, gender, wm=False):
    return {
        'datum': day,
        'ort': venue,
        'disziplin': event,
        'geschlecht': gender,
        'wm': wm,
        'starts': [],
        'sendungen': [],
        'uid1': None,
        'uid2': None
    }


def race_id(r):
    return '|'.join((
        'WM' if r['wm'] else 'WC',
        r['datum'],
        r['geschlecht'],
        r['disziplin'],
        norm(r['ort'])
    ))


def old_calendar():
    # Bisherige Einträge und IDs wiederverwenden.
    if not OUTPUT.exists():
        return {}

    previous = {}

    for e in vevents(
        OUTPUT.read_text(encoding='utf-8-sig')
    ):
        title = e.get('SUMMARY', '')

        is_wm = (
            'Ski-WM' in title
            or 'Ski-WM' in e.get('DESCRIPTION', '')
        )

        dayraw = e.get('DTSTART', '')[:8]

        try:
            day = datetime.strptime(
                dayraw, '%Y%m%d'
            ).date().isoformat()
        except ValueError:
            continue

        plain = title.replace('\\,', ',')
        event = discipline(plain)

        if not event:
            continue

        if re.search(r'\bDamen\b', plain, re.I):
            gender = 'Damen'
        elif re.search(r'\bHerren\b', plain, re.I):
            gender = 'Herren'
        else:
            continue

        if is_wm:
            venue = 'Crans-Montana'
        else:
            match = re.match(
                r'🎿\s*(.*?)\s*[–-]\s*',
                plain
            )
            if not match:
                continue
            venue = match.group(1).strip()

        r = new_race(
            day, venue, event, gender,
            wm=is_wm
        )

        key = (
            e.get('X-ORF-RACE-ID')
            or race_id(r)
        )

        item = previous.setdefault(key, r)
        uid = e.get('UID')

        if '2. Durchgang' in plain and uid:
            item['uid2'] = uid
        elif uid:
            item['uid1'] = uid

    return previous


def fis_races():
    raw = fetch(FIS)

    if 'BEGIN:VCALENDAR' not in raw:
        raise RuntimeError(
            'FIS nicht lesbar: '
            'alter Kalender bleibt bestehen'
        )

    races = []

    for e in vevents(raw):
        try:
            day = datetime.strptime(
                e.get('DTSTART', '')[:8],
                '%Y%m%d'
            ).date().isoformat()
        except ValueError:
            continue

        desc = e.get('DESCRIPTION', '')

        gender = (
            'Damen'
            if re.search(
                r'Gender:\s*Women\b',
                desc, re.I
            )
            else 'Herren'
            if re.search(
                r'Gender:\s*Men\b',
                desc, re.I
            )
            else None
        )

        summary = e.get('SUMMARY', '')
        event = discipline(
            summary + ' ' + desc
        )

        if gender is None or event is None:
            continue

        venue = re.split(
            r'\s+[-–]\s+',
            summary
        )[0].strip()

        races.append(
            new_race(day, venue, event, gender)
        )

    if not races:
        raise RuntimeError(
            'Keine FIS-Rennen: '
            'alter Kalender bleibt bestehen'
        )

    return races


def apply_start_file(races):
    if not START_FILE.exists():
        return

    data = json.loads(
        START_FILE.read_text(
            encoding='utf-8'
        )
    )

    for r in races:
        val = data.get(r['datum'], {})

        if (
            not isinstance(val, dict)
            or val.get('geschlecht') != r['geschlecht']
            or val.get('disziplin') != r['disziplin']
        ):
            continue

        for key in (
            'erster_lauf',
            'zweiter_lauf',
            'start',
            'startzeit'
        ):
            t = clock(
                val.get(key),
                r['datum']
            )

            if t and t not in r['starts']:
                r['starts'].append(t)

        r['starts'].sort()


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script'):
            self.hidden += 1

        if tag in (
            'p', 'li', 'div', 'tr',
            'br', 'h2', 'h3', 'h4'
        ):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if (
            tag in ('style', 'script')
            and self.hidden
        ):
            self.hidden -= 1

        if tag in (
            'p', 'li', 'div', 'tr',
            'br', 'h2', 'h3', 'h4'
        ):
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def orf_program():
    # ORF-Sendeplan einlesen.

    parser = TextExtractor()
    parser.feed(fetch(ORF))

    plain = re.sub(
        r'\s+',
        ' ',
        html.unescape(
            ' '.join(parser.parts)
        )
    )

    head = re.compile(
        r'\b(?:Montag|Dienstag|Mittwoch|'
        r'Donnerstag|Freitag|Samstag|Sonntag),\s*'
        r'(\d{1,2})\.\s*'
        r'([A-Za-zÄÖÜäöüß]+)',
        re.I
    )

    rows = re.compile(
        r'(\d{1,2})[.:](\d{2})\s*Uhr'
        r'\s*\|\s*Ski\s*alpin\s*\|'
        r'\s*(.*?)\s*\|\s*'
        r'(ORF\s*1|ORF1|OSP|ORF\s*Sport\s*\+)',
        re.I
    )

    headings = list(
        head.finditer(plain)
    )

    program = []
    year = TODAY.year

    for i, h in enumerate(headings):
        month = MONTHS.get(
            norm(h.group(2))
        )

        if month is None:
            continue

        try:
            d = date(
                year,
                month,
                int(h.group(1))
            )
        except ValueError:
            continue

        if TODAY.month == 12 and month == 1:
            d = d.replace(
                year=year + 1
            )
        elif TODAY.month == 1 and month == 12:
            d = d.replace(
                year=year - 1
            )

        section = plain[
            h.end():
            headings[i + 1].start()
            if i + 1 < len(headings)
            else len(plain)
        ]

        for m in rows.finditer(section):
            desc = m.group(3)

            if re.search(
                r'wiederholung|highlights?|'
                r'zusammenfassung|replay',
                desc,
                re.I
            ):
                continue

            gender = (
                'Damen'
                if re.search(
                    r'\b(damen|frauen)\b',
                    desc, re.I
                )
                else 'Herren'
                if re.search(
                    r'\b(herren|männer)\b',
                    desc, re.I
                )
                else 'Mixed'
                if re.search(
                    r'\bmixed\b',
                    desc, re.I
                )
                else None
            )

            event = discipline(desc)

            if not gender or not event:
                continue

            number_match = re.search(
                r'\b([12])\.\s*'
                r'(?:durchgang|lauf)\b',
                desc,
                re.I
            )

            number = (
                int(number_match.group(1))
                if number_match
                else None
            )

            begin = clock(
                m.group(1) + ':' + m.group(2),
                d.isoformat()
            )

            if begin is None:
                continue

            program.append({
                'datum': d.isoformat(),
                'geschlecht': gender,
                'disziplin': event,
                'text': desc,
                'lauf': number,
                'beginn': begin,
                'sender': (
                    'ORF 1'
                    if '1' in m.group(4)
                    else 'ORF SPORT+'
                )
            })

    covered_dates = set()

    for h in headings:
        month = MONTHS.get(
            norm(h.group(2))
        )

        if month is not None:
            try:
                d = date(
                    year,
                    month,
                    int(h.group(1))
                )

                if TODAY.month == 12 and month == 1:
                    d = d.replace(
                        year=year + 1
                    )

                if TODAY.month == 1 and month == 12:
                    d = d.replace(
                        year=year - 1
                    )

                covered_dates.add(
                    d.isoformat()
                )

            except ValueError:
                pass

    if not headings or not covered_dates:
        raise ValueError(
            'ORF-Programm nicht '
            'zuverlässig lesbar'
        )

    return program, covered_dates


def same_race(r, p):
    if (
        r['datum'],
        r['geschlecht'],
        r['disziplin']
    ) != (
        p['datum'],
        p['geschlecht'],
        p['disziplin']
    ):
        return False

    venue = norm(
        r['ort']
    ).split(' ')[0]

    return (
        not venue
        or venue in norm(p['text'])
        or len(venue) < 4
    )


def attach_orf(races, program):
    hits = 0

    for p in program:
        candidates = [
            r for r in races
            if same_race(r, p)
        ]

        if len(candidates) != 1:
            candidates = [
                r for r in races
                if (
                    r['datum'],
                    r['geschlecht'],
                    r['disziplin']
                ) == (
                    p['datum'],
                    p['geschlecht'],
                    p['disziplin']
                )
            ]

        if len(candidates) != 1:
            continue

        r = candidates[0]

        item = (
            p['beginn'],
            p['beginn'] + timedelta(
                minutes=90
            ),
            p['sender'],
            p['lauf']
        )

        if item not in r['sendungen']:
            r['sendungen'].append(item)
            hits += 1

    return hits


def add_fallback_soelden(races):
    count = 0

    for r in races:
        if (
            r['wm']
            or r['disziplin'] != 'Riesentorlauf'
            or 'solden' not in norm(r['ort'])
        ):
            continue

        for number in (1, 2):
            value = SOELDEN.get((
                r['datum'],
                r['geschlecht'],
                number
            ))

            if (
                not value
                or any(
                    x[3] == number
                    for x in r['sendungen']
                )
            ):
                continue

            begin = clock(
                value,
                r['datum']
            )

            r['sendungen'].append((
                begin,
                begin + timedelta(
                    minutes=90
                ),
                'ORF 1',
                number
            ))

            count += 1

    print(
        'Sölden-Sendezeiten zusätzlich abgesichert:',
        count
    )


def ics(s):
    return (
        str(s)
        .replace('\\', '\\\\')
        .replace('\n', '\\n')
        .replace(',', '\\,')
        .replace(';', '\\;')
    )


def stamp(t):
    return t.astimezone(
        timezone.utc
    ).strftime(
        '%Y%m%dT%H%M%SZ'
    )


def fold(lines):
    output = []

    for line in lines:
        segment = ''

        for char in line:
            if len(
                (segment + char).encode(
                    'utf-8'
                )
            ) > 70:
                output.append(segment)
                segment = ' '

            segment += char

        output.append(segment)

    return output


def legs(r):
    starts = sorted(set(
        x for x in r['starts'] if x
    ))

    if r['disziplin'] in (
        'Slalom',
        'Riesentorlauf',
        'Team-Kombination'
    ):
        result = [(
            1,
            starts[0] if starts else None
        )]

        if len(starts) >= 2:
            result.append((
                2,
                starts[1]
            ))

        return result

    return [(
        None,
        starts[0] if starts else None
    )]


def broadcasts(r, number, all_legs):
    chosen = []

    for s in r['sendungen']:
        if (
            s[3] == number
            or (
                s[3] is None
                and len(all_legs) == 1
            )
        ):
            chosen.append(s)

    return chosen


def write_calendar(races):
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//ORF Ski Kalender//DE',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:ORF Ski-Weltcup LIVE'
    ]

    stats = {
        'ORF': 0,
        'Rennstart': 0,
        'Ganztag': 0,
        'WM': 0
    }

    for r in races:
        key = race_id(r)

        fresh_uid = (
            hashlib.sha256(
                key.encode('utf-8')
            ).hexdigest()[:24]
            + '@orf-ski-kalender'
        )

        base_uid = (
            r.get('uid1')
            or fresh_uid
        )

        all_legs = legs(r)

        if (
            len(all_legs) == 1
            and all_legs[0][0] == 1
            and any(
                s[3] == 2
                for s in r['sendungen']
            )
        ):
            all_legs.append(
                (2, None)
            )

        for number, start in all_legs:
            if number == 2:
                uid = (
                    r.get('uid2')
                    or base_uid.replace(
                        '@orf-ski-kalender',
                        '-lauf2@orf-ski-kalender'
                    )
                )
            else:
                uid = base_uid

            title = (
                '🏆 Ski-WM 2027 – '
                if r['wm']
                else '🎿 ' + r['ort'] + ' – '
            )

            title += (
                r['disziplin']
                + ' '
                + r['geschlecht']
            )

            if number is not None:
                if (
                    r['disziplin']
                    == 'Team-Kombination'
                ):
                    title += (
                        ' | Abfahrt'
                        if number == 1
                        else ' | Slalom'
                    )
                else:
                    title += (
                        ' | '
                        + str(number)
                        + '. Durchgang'
                    )

            desc = (
                'Alpine Ski-WM '
                'Crans-Montana 2027.'
                if r['wm']
                else 'FIS Ski-Weltcup 2026/27.'
            )

            if start:
                desc += (
                    '\nRennstart: '
                    + start.astimezone(TZ)
                    .strftime('%H:%M')
                    + ' Uhr'
                )

            tv = broadcasts(
                r, number, all_legs
            )

            if tv:
                begin = min(
                    x[0] for x in tv
                )

                end = max(
                    x[1] for x in tv
                )

                title += ' | ORF LIVE'

                desc += (
                    '\nORF-Sendebeginn: '
                    + begin.astimezone(TZ)
                    .strftime('%H:%M')
                    + ' Uhr'
                )

                desc += (
                    '\nSender: '
                    + ', '.join(
                        sorted(set(
                            x[2] for x in tv
                        ))
                    )
                )

                times = [
                    'DTSTART:' + stamp(begin),
                    'DTEND:' + stamp(end)
                ]

                stats['ORF'] += 1

            elif start:
                title += (
                    ' | Start '
                    + start.astimezone(TZ)
                    .strftime('%H:%M')
                    + ' Uhr'
                )

                desc += (
                    '\nORF-Sendezeit noch '
                    'nicht erkannt; '
                    'Dauer vorläufig.'
                )

                times = [
                    'DTSTART:' + stamp(start),
                    'DTEND:' + stamp(
                        start + timedelta(
                            minutes=90
                        )
                    )
                ]

                stats['Rennstart'] += 1

            else:
                title += ' | vorläufig'

                desc += (
                    '\nNoch keine '
                    'bestätigte Startzeit.'
                )

                d = date.fromisoformat(
                    r['datum']
                )

                times = [
                    'DTSTART;VALUE=DATE:'
                    + d.strftime('%Y%m%d'),
                    'DTEND;VALUE=DATE:'
                    + (
                        d + timedelta(days=1)
                    ).strftime('%Y%m%d')
                ]

                stats['Ganztag'] += 1

            if r['wm']:
                stats['WM'] += 1

            lines.extend([
                'BEGIN:VEVENT',
                'UID:' + uid,
                'DTSTAMP:' + stamp(NOW),
                'X-ORF-RACE-ID:' + ics(key),
                *times,
                'SUMMARY:' + ics(title),
                'DESCRIPTION:' + ics(desc),
                'END:VEVENT'
            ])

    lines.append('END:VCALENDAR')

    OUTPUT.write_bytes((
        '\r\n'.join(fold(lines))
        + '\r\n'
    ).encode('utf-8'))

    print(
        'Kalendereinträge:',
        sum(stats[x] for x in (
            'ORF',
            'Rennstart',
            'Ganztag'
        ))
    )

    for name, value in stats.items():
        print(name + ':', value)

    print('FERTIG')


def main():
    old = old_calendar()
    races = fis_races()

    print(
        'FIS-Weltcuprennen:',
        len(races)
    )

    known = {
        race_id(r): r
        for r in races
    }

    for key, r in known.items():
        if key in old:
            r['uid1'] = old[key]['uid1']
            r['uid2'] = old[key]['uid2']

    # Ski-WM bleibt separat enthalten.
    for day, event, gender, starts in WM:
        r = new_race(
            day,
            'Crans-Montana',
            event,
            gender,
            wm=True
        )

        r['starts'] = [
            clock(s, day)
            for s in starts
        ]

        if race_id(r) in old:
            previous = old[
                race_id(r)
            ]
            r['uid1'] = previous['uid1']
            r['uid2'] = previous['uid2']

        races.append(r)

    # ORF laden, bevor Rennen entfernt werden.
    program_ok = True

    try:
        program, covered = orf_program()

        print(
            'ORF-Ski-Liveübertragungen '
            'im aktuellen Sendeplan:',
            len(program)
        )

    except Exception as exc:
        program_ok = False
        program = []
        covered = set()

        print(
            'ORF vorübergehend '
            'nicht lesbar:',
            exc
        )

    held = 0
    removed = 0

    for key, r in old.items():
        if (
            key in known
            or r['datum'] < TODAY.isoformat()
        ):
            continue

        if (
            not program_ok
            or r['datum'] not in covered
        ):
            # ORF-Programm für den Tag
            # noch nicht verfügbar:
            # Rennen behalten.
            races.append(r)
            held += 1
            continue

        if any(
            same_race(r, p)
            for p in program
        ):
            races.append(r)
            held += 1

        else:
            removed += 1

    # Rennen ergänzen, die nur der ORF listet.
    only_orf = 0

    for p in program:
        if any(
            same_race(r, p)
            for r in races
        ):
            continue

        if re.search(
            r'\b(?:ski[- ]?wm|'
            r'weltmeisterschaft)\b',
            p['text'],
            re.I
        ):
            continue

        venue_match = re.search(
            r',\s*([^,]+)\s*$',
            p['text']
        )

        if not venue_match:
            continue

        venue = (
            venue_match.group(1).strip()
        )

        if not venue or len(venue) > 60:
            continue

        r = new_race(
            p['datum'],
            venue,
            p['disziplin'],
            p['geschlecht']
        )

        k = race_id(r)

        if k in old:
            r['uid1'] = old[k]['uid1']
            r['uid2'] = old[k]['uid2']

        races.append(r)
        only_orf += 1

    apply_start_file(races)

    hits = attach_orf(
        races, program
    )

    print(
        'Nur im ORF gelistete '
        'Rennen ergänzt:',
        only_orf
    )

    add_fallback_soelden(races)

    print(
        'ORF-Sendungen zugeordnet:',
        hits
    )

    print(
        'Fehlende FIS-Rennen '
        'vorsorglich behalten:',
        held
    )

    print(
        'Weder bei FIS noch '
        'im ORF-Programm:',
        removed
    )

    write_calendar(races)


if __name__ == '__main__':
    main()
