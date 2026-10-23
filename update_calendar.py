
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

TZ = ZoneInfo("Europe/Vienna")
NOW = datetime.now(timezone.utc)
TODAY = NOW.astimezone(TZ).date()

OUTPUT = Path("ski-weltcup.ics")
START_FILE = Path("rennstarts.json")

FIS_URL = (
    "https://www.fis-ski.com/DB/services/public/"
    "icalendar-feed-fis-events.html?"
    "seasoncode=2027&sectorcode=AL&categorycode=WC"
)

ORF_URL = "https://sport.orf.at/"

EPG = {
    "ORF 1": "438442",
    "ORF SPORT+": "76756",
}

WM = [
    ("2027-02-01", "Team-Parallel Mixed", "Mixed", ["11:15"]),
    ("2027-02-04", "Super-G", "Damen", ["11:15"]),
    ("2027-02-05", "Super-G", "Herren", ["11:15"]),
    ("2027-02-06", "Abfahrt", "Damen", ["11:15"]),
    ("2027-02-07", "Abfahrt", "Herren", ["11:15"]),
    ("2027-02-09", "Team-Kombination", "Damen", ["10:00", "13:30"]),
    ("2027-02-10", "Team-Kombination", "Herren", ["10:00", "13:30"]),
    ("2027-02-11", "Riesentorlauf", "Damen", ["10:00", "13:30"]),
    ("2027-02-12", "Riesentorlauf", "Herren", ["10:00", "13:30"]),
    ("2027-02-13", "Slalom", "Damen", ["10:00", "13:30"]),
    ("2027-02-14", "Slalom", "Herren", ["10:00", "13:30"]),
]

SOELDEN = {
    ("2026-10-24", "Damen", 1): "09:30",
    ("2026-10-24", "Damen", 2): "12:45",
    ("2026-10-25", "Herren", 1): "09:25",
    ("2026-10-25", "Herren", 2): "12:35",
}

MONTHS = {
    "janner": 1, "januar": 1, "februar": 2,
    "marz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}


def fetch(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(
        request, timeout=25
    ) as response:
        return response.read().decode(
            "utf-8-sig", errors="replace"
        )


def norm(value):
    text = unicodedata.normalize(
        "NFKD", str(value).casefold()
    )
    text = "".join(
        c for c in text
        if not unicodedata.combining(c)
    )
    text = (
        text.replace("ß", "ss")
        .replace("oe", "o")
        .replace("ae", "a")
        .replace("ue", "u")
    )
    return re.sub(
        r"[^a-z0-9]+", " ", text
    ).strip()


def discipline(value):
    text = norm(value)

    if (
        "team kombination" in text
        or "team combined" in text
    ):
        return "Team-Kombination"

    if any(x in text for x in (
        "team parallel",
        "mixed team",
        "team event",
    )):
        return "Team-Parallel Mixed"

    if any(x in text for x in (
        "giant slalom",
        "riesentorlauf",
        "riesenslalom",
    )):
        return "Riesentorlauf"

    if "super g" in text:
        return "Super-G"

    if (
        "downhill" in text
        or "abfahrt" in text
    ):
        return "Abfahrt"

    if re.search(r"\bslalom\b", text):
        return "Slalom"

    return None


def clock(value, day=None):
    if value is None:
        return None

    text = str(value).strip()

    if day and re.fullmatch(
        r"\d{1,2}[:.]\d{2}", text
    ):
        hour, minute = map(
            int, re.split(r"[:.]", text)
        )

        if hour > 23 or minute > 59:
            return None

        return datetime.combine(
            date.fromisoformat(day),
            datetime.min.time(),
            TZ,
        ).replace(
            hour=hour,
            minute=minute,
        ).astimezone(timezone.utc)

    try:
        dt = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(timezone.utc)

    except ValueError:
        return None


def unfold(raw):
    lines = []

    for line in raw.replace(
        "\r\n", "\n"
    ).split("\n"):
        if line.startswith(
            (" ", "\t")
        ) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)

    return lines


def vevents(raw):
    events = []
    current = None

    for line in unfold(raw):
        if line == "BEGIN:VEVENT":
            current = {}

        elif line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None

        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            base = key.split(";", 1)[0]

            if base in (
                "DTSTART", "DTEND", "UID",
                "SUMMARY", "DESCRIPTION",
                "X-ORF-RACE-ID",
            ):
                current[base] = (
                    value.replace("\\,", ",")
                    .replace("\\n", "\n")
                )
                if base in ("DTSTART", "DTEND"):
                    current[base + "_FIELD"] = key

    return events


def event_day(event):
    value = event.get("DTSTART", "")

    if not re.match(r"^\d{8}", value):
        return None

    try:
        if (
            "VALUE=DATE" in event.get(
                "DTSTART_FIELD", ""
            )
            or len(value) == 8
        ):
            return datetime.strptime(
                value[:8], "%Y%m%d"
            ).date().isoformat()

        if value.endswith("Z"):
            dt = datetime.strptime(
                value, "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.strptime(
                value[:15], "%Y%m%dT%H%M%S"
            ).replace(tzinfo=TZ)

        return dt.astimezone(
            TZ
        ).date().isoformat()

    except ValueError:
        return None


def new_race(day, venue, event, gender, wm=False):
    return {
        "datum": day,
        "ort": venue,
        "disziplin": event,
        "geschlecht": gender,
        "wm": wm,
        "starts": [],
        "tv": [],
        "uids": {},
    }


def race_key(race):
    # Gleicher Schlüssel trotz
    # wechselnder Schreibweise des Rennortes.
    return "|".join((
        "WM" if race["wm"] else "WC",
        race["datum"],
        race["geschlecht"],
        race["disziplin"],
    ))


def old_races():
    if not OUTPUT.exists():
        return {}

    result = {}

    for event in vevents(
        OUTPUT.read_text(
            encoding="utf-8-sig"
        )
    ):
        title = event.get("SUMMARY", "")
        desc = event.get("DESCRIPTION", "")

        is_wm = (
            "Ski-WM" in title
            or "Ski-WM" in desc
        )

        day = event_day(event)
        kind = discipline(title)

        if not day or not kind:
            continue

        gender = next((
            g for g in (
                "Damen", "Herren", "Mixed"
            )
            if re.search(
                r"\b" + g + r"\b",
                title, re.I
            )
        ), None)

        if not gender:
            continue

        if is_wm:
            venue = "Crans-Montana"
        else:
            match = re.match(
                r"🎿\s*(.*?)\s*[–-]\s*",
                title
            )
            if not match:
                continue
            venue = match.group(1).strip()

        race = new_race(
            day, venue, kind, gender, is_wm
        )

        key = race_key(race)
        previous = result.setdefault(
            key, race
        )

        uid = event.get("UID")

        if uid:
            second = (
                bool(re.search(
                    r"2\.\s*Durchgang",
                    title
                ))
                or (
                    kind == "Team-Kombination"
                    and "| Slalom" in title
                )
            )
            previous["uids"][
                2 if second else 1
            ] = uid

    return result


def fis_races():
    raw = fetch(FIS_URL)

    if "BEGIN:VCALENDAR" not in raw:
        raise RuntimeError(
            "FIS-Kalender nicht lesbar. "
            "Bestehende Datei bleibt erhalten."
        )

    races = []

    for event in vevents(raw):
        day = event_day(event)
        desc = event.get(
            "DESCRIPTION", ""
        )

        if re.search(
            r"Gender:\s*Women\b",
            desc, re.I
        ):
            gender = "Damen"

        elif re.search(
            r"Gender:\s*Men\b",
            desc, re.I
        ):
            gender = "Herren"

        else:
            continue

        summary = event.get(
            "SUMMARY", ""
        )
        kind = discipline(
            summary + " " + desc
        )

        if not day or not kind:
            continue

        venue = re.split(
            r"\s+[-–]\s+",
            summary
        )[0].strip()

        races.append(new_race(
            day, venue, kind, gender
        ))

    if not races:
        raise RuntimeError(
            "Keine FIS-Rennen gefunden. "
            "Bestehende Datei bleibt erhalten."
        )

    return races


def add_starts(races):
    if not START_FILE.exists():
        return

    data = json.loads(
        START_FILE.read_text(
            encoding="utf-8"
        )
    )

    for race in races:
        value = data.get(
            race["datum"], {}
        )

        if (
            not isinstance(value, dict)
            or value.get("geschlecht")
            != race["geschlecht"]
            or value.get("disziplin")
            != race["disziplin"]
        ):
            continue

        for key in (
            "erster_lauf",
            "zweiter_lauf",
            "start",
            "startzeit",
        ):
            t = clock(
                value.get(key),
                race["datum"]
            )

            if (
                t
                and t not in race["starts"]
            ):
                race["starts"].append(t)

        race["starts"].sort()


def number_of_leg(text):
    match = re.search(
        r"\b([12]|erster|erste|"
        r"zweiter|zweite)\s*"
        r"(?:durchgang|lauf)\b",
        norm(text)
    )

    if not match:
        return None

    return (
        1 if match.group(1) in (
            "1", "erster", "erste"
        )
        else 2
    )


def is_live(text):
    value = norm(text)

    if re.search(
        r"\b(wiederholung|highlight|"
        r"highlights|zusammenfassung|"
        r"replay|ruckblick)\b",
        value
    ):
        return False

    return bool(re.search(
        r"\b(live|direkt|countdown|"
        r"durchgang|lauf)\b",
        value
    ))


def match_race(program, races):
    candidates = [
        r for r in races
        if r["datum"] == program["datum"]
    ]

    if program.get("geschlecht"):
        candidates = [
            r for r in candidates
            if r["geschlecht"]
            == program["geschlecht"]
        ]

    if program.get("disziplin"):
        candidates = [
            r for r in candidates
            if r["disziplin"]
            == program["disziplin"]
        ]

    text = norm(
        program.get("text", "")
    )

    if "weltcup" in text:
        candidates = [
            r for r in candidates
            if not r["wm"]
        ]

    elif any(x in text for x in (
        "weltmeisterschaft",
        "ski wm",
        "crans montana",
    )):
        candidates = [
            r for r in candidates
            if r["wm"]
        ]

    if len(candidates) > 1:
        venues = [
            r for r in candidates
            if (
                norm(r["ort"])
                and norm(r["ort"]) in text
            )
        ]
        if venues:
            candidates = venues

    return (
        candidates[0]
        if len(candidates) == 1
        else None
    )


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

        if tag in (
            "p", "li", "div", "tr",
            "br", "h2", "h3", "h4"
        ):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if (
            tag in ("script", "style")
            and self.hidden
        ):
            self.hidden -= 1

        if tag in (
            "p", "li", "div", "tr",
            "br", "h2", "h3", "h4"
        ):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def orf_official():
    parser = VisibleText()
    parser.feed(fetch(ORF_URL))

    text = html.unescape(
        "".join(parser.parts)
    )

    heading = re.compile(
        r"\b(?:Montag|Dienstag|Mittwoch|"
        r"Donnerstag|Freitag|Samstag|"
        r"Sonntag),\s*"
        r"(\d{1,2})\.\s*"
        r"([A-Za-zÄÖÜäöüß]+)",
        re.I
    )

    headings = list(
        heading.finditer(text)
    )

    row = re.compile(
        r"(\d{1,2})[.:](\d{2})\s*Uhr"
        r"\s*\|\s*Ski\s*alpin\s*\|"
        r"\s*(.{4,220}?)\s*\|\s*"
        r"(ORF\s*1|ORF1|OSP|"
        r"ORF\s*Sport\s*\+)",
        re.I
    )

    program = []
    covered = set()

    for i, h in enumerate(headings):
        month = MONTHS.get(
            norm(h.group(2))
        )

        if not month:
            continue

        year = TODAY.year

        if TODAY.month == 12 and month == 1:
            year += 1

        if TODAY.month == 1 and month == 12:
            year -= 1

        try:
            day = date(
                year,
                month,
                int(h.group(1))
            ).isoformat()
        except ValueError:
            continue

        covered.add(day)

        end_position = (
            headings[i + 1].start()
            if i + 1 < len(headings)
            else len(text)
        )

        section = text[
            h.end():end_position
        ]

        for match in row.finditer(section):
            desc = " ".join(
                match.group(3).split()
            )

            if not is_live(desc):
                continue

            kind = discipline(desc)

            if re.search(
                r"\b(damen|frauen|women)\b",
                desc, re.I
            ):
                gender = "Damen"

            elif re.search(
                r"\b(herren|männer|men)\b",
                desc, re.I
            ):
                gender = "Herren"

            elif re.search(
                r"\bmixed\b",
                desc, re.I
            ):
                gender = "Mixed"

            else:
                gender = None

            if not kind or not gender:
                continue

            begin = clock(
                match.group(1)
                + ":"
                + match.group(2),
                day
            )

            if not begin:
                continue

            # Nur ausdrücklich erkennbare
            # Endzeiten werden als bestätigt
            # übernommen.
            end = None

            following = section[
                match.end():
                match.end() + 50
            ]

            explicit = re.search(
                r"(?:bis|–|-)\s*"
                r"(\d{1,2})[.:](\d{2})"
                r"\s*Uhr",
                following, re.I
            )

            if explicit:
                end = clock(
                    explicit.group(1)
                    + ":"
                    + explicit.group(2),
                    day
                )

                if end and end <= begin:
                    end += timedelta(days=1)

            program.append({
                "datum": day,
                "geschlecht": gender,
                "disziplin": kind,
                "text": desc,
                "lauf": number_of_leg(desc),
                "beginn": begin,
                "ende": end,
                "sender": (
                    "ORF 1"
                    if "1" in match.group(4)
                    else "ORF SPORT+"
                ),
                "quelle": "ORF-Sport",
            })

    if not headings:
        raise ValueError(
            "Kein datierter ORF-Sendeplan "
            "gefunden"
        )

    return program, covered


def epg_program():
    program = []
    covered = set()

    for station, channel in EPG.items():
        try:
            data = json.loads(fetch(
                "https://epg.pw/api/epg.json?"
                "channel_id=" + channel
            ))

            entries = data.get(
                "epg_list", []
            )

            if not isinstance(
                entries, list
            ):
                continue

            timeline = []

            for entry in entries:
                begin = clock(
                    entry.get("start_date")
                )
                if begin:
                    timeline.append(
                        (begin, entry)
                    )

            timeline.sort(
                key=lambda x: x[0]
            )

            for begin, entry in timeline:
                covered.add(
                    begin.astimezone(
                        TZ
                    ).date().isoformat()
                )

            hits = 0

            for i, (begin, entry) in enumerate(
                timeline
            ):
                text = (
                    str(entry.get("title") or "")
                    + " "
                    + str(entry.get("desc") or "")
                )

                if (
                    not is_live(text)
                    or not re.search(
                        r"ski|slalom|abfahrt|"
                        r"super[- ]?g",
                        text, re.I
                    )
                ):
                    continue

                kind = discipline(text)

                if re.search(
                    r"\b(damen|frauen|women)\b",
                    text, re.I
                ):
                    gender = "Damen"

                elif re.search(
                    r"\b(herren|männer|men)\b",
                    text, re.I
                ):
                    gender = "Herren"

                elif re.search(
                    r"\bmixed\b",
                    text, re.I
                ):
                    gender = "Mixed"

                else:
                    gender = None

                if not kind or not gender:
                    continue

                # Das Ende der Sendung ist
                # entweder direkt angegeben
                # oder der Beginn der nächsten
                # Sendung desselben Senders.
                end = clock(
                    entry.get("end_date")
                )

                if (
                    end is None
                    and i + 1 < len(timeline)
                ):
                    end = timeline[i + 1][0]

                if end and (
                    end <= begin
                    or end - begin
                    > timedelta(hours=6)
                ):
                    end = None

                program.append({
                    "datum": (
                        begin.astimezone(TZ)
                        .date().isoformat()
                    ),
                    "geschlecht": gender,
                    "disziplin": kind,
                    "text": text,
                    "lauf": number_of_leg(text),
                    "beginn": begin,
                    "ende": end,
                    "sender": station,
                    "quelle": "EPG",
                })

                hits += 1

            print(
                station,
                "- EPG-Sendungen erkannt:",
                hits
            )

        except Exception as exc:
            print(
                station,
                "- EPG nicht lesbar:",
                exc
            )

    return program, covered


def add_broadcast(race, program):
    entry = (
        program["beginn"],
        program["ende"],
        program["sender"],
        program["lauf"],
        program["quelle"],
    )

    if entry not in race["tv"]:
        race["tv"].append(entry)


def add_soelden(races):
    count = 0

    for race in races:
        if (
            race["wm"]
            or race["disziplin"]
            != "Riesentorlauf"
            or "solden" not in norm(
                race["ort"]
            )
        ):
            continue

        for number in (1, 2):
            value = SOELDEN.get((
                race["datum"],
                race["geschlecht"],
                number,
            ))

            if not value:
                continue

            if any(
                s[3] == number
                for s in race["tv"]
            ):
                continue

            begin = clock(
                value, race["datum"]
            )

            # Bestätigter Sendebeginn,
            # aber keine erfundene Endzeit.
            race["tv"].append((
                begin,
                None,
                "ORF 1",
                number,
                "Sölden bestätigt",
            ))

            count += 1

    print(
        "Sölden-Countdown-Zeiten ergänzt:",
        count
    )


def ics(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def stamp(dt):
    return dt.astimezone(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")


def fold(lines):
    result = []

    for line in lines:
        segment = ""

        for char in line:
            if len(
                (segment + char).encode(
                    "utf-8"
                )
            ) > 70:
                result.append(segment)
                segment = " "

            segment += char

        result.append(segment)

    return result


def legs(race):
    starts = sorted(set(
        x for x in race["starts"]
        if x
    ))

    if race["disziplin"] in (
        "Slalom",
        "Riesentorlauf",
        "Team-Kombination",
    ):
        count = (
            2 if (
                len(starts) > 1
                or any(
                    s[3] == 2
                    for s in race["tv"]
                )
            )
            else 1
        )

        return [
            (
                i,
                starts[i - 1]
                if len(starts) >= i
                else None,
            )
            for i in range(
                1, count + 1
            )
        ]

    return [(
        None,
        starts[0] if starts else None,
    )]


def tv_for_leg(race, number, all_legs):
    selected = []

    for sendung in race["tv"]:
        if (
            sendung[3] == number
            or (
                sendung[3] is None
                and len(all_legs) == 1
            )
        ):
            selected.append(sendung)
            continue

        if (
            sendung[3] is None
            and len(all_legs) == 2
        ):
            distances = []

            for n, start in all_legs:
                if not start:
                    continue

                diff = (
                    start - sendung[0]
                ).total_seconds() / 60

                if -30 <= diff <= 90:
                    distances.append((
                        abs(diff), n
                    ))

            distances.sort()

            if distances and (
                len(distances) == 1
                or distances[0][0]
                < distances[1][0]
            ):
                if distances[0][1] == number:
                    selected.append(sendung)

    return selected


def write_calendar(races):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ORF Ski Kalender//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:ORF Ski-Weltcup LIVE",
    ]

    stats = {
        "ORF": 0,
        "Rennstart": 0,
        "Ganztag": 0,
        "WM": 0,
        "Endzeiten bestätigt": 0,
    }

    for race in races:
        key = race_key(race)

        base = (
            race["uids"].get(1)
            or hashlib.sha256(
                key.encode("utf-8")
            ).hexdigest()[:24]
            + "@orf-ski-kalender"
        )

        all_legs = legs(race)

        for number, start in all_legs:
            if number == 2:
                uid = (
                    race["uids"].get(2)
                    or base.replace(
                        "@orf-ski-kalender",
                        "-lauf2@orf-ski-kalender",
                    )
                )
            else:
                uid = base

            title = (
                "🏆 Ski-WM 2027 – "
                if race["wm"]
                else (
                    "🎿 "
                    + race["ort"]
                    + " – "
                )
            )

            title += (
                race["disziplin"]
                + " "
                + race["geschlecht"]
            )

            if number is not None:
                if (
                    race["disziplin"]
                    == "Team-Kombination"
                ):
                    title += (
                        " | Abfahrt"
                        if number == 1
                        else " | Slalom"
                    )
                else:
                    title += (
                        " | "
                        + str(number)
                        + ". Durchgang"
                    )

            desc = (
                "Alpine Ski-WM "
                "Crans-Montana 2027."
                if race["wm"]
                else "FIS Ski-Weltcup 2026/27."
            )

            if start:
                desc += (
                    "\nRennstart: "
                    + start.astimezone(TZ)
                    .strftime("%H:%M")
                    + " Uhr"
                )

            broadcasts = tv_for_leg(
                race,
                number,
                all_legs,
            )

            if broadcasts:
                begin = min(
                    s[0] for s in broadcasts
                )

                known_ends = [
                    s[1]
                    for s in broadcasts
                    if (
                        s[1]
                        and s[1] > begin
                    )
                ]

                if known_ends:
                    end = max(known_ends)

                    desc += (
                        "\nORF-Sendeende: "
                        + end.astimezone(TZ)
                        .strftime("%H:%M")
                        + " Uhr"
                    )

                    stats[
                        "Endzeiten bestätigt"
                    ] += 1

                else:
                    # Vorläufige Dauer.
                    # Nicht als tatsächliches
                    # ORF-Sendeende ausgeben.
                    end = max(
                        begin + timedelta(
                            minutes=90
                        ),
                        (
                            start + timedelta(
                                minutes=60
                            )
                            if start
                            else begin
                        ),
                    )

                    desc += (
                        "\nORF-Sendeende noch "
                        "nicht bekannt. "
                        "Dauer vorläufig."
                    )

                title += " | ORF LIVE"

                desc += (
                    "\nORF-Sendebeginn: "
                    + begin.astimezone(TZ)
                    .strftime("%H:%M")
                    + " Uhr"
                )

                desc += (
                    "\nSender: "
                    + ", ".join(sorted({
                        s[2]
                        for s in broadcasts
                    }))
                )

                fields = [
                    "DTSTART:" + stamp(begin),
                    "DTEND:" + stamp(end),
                ]

                stats["ORF"] += 1

            elif start:
                title += (
                    " | Start "
                    + start.astimezone(TZ)
                    .strftime("%H:%M")
                    + " Uhr"
                )

                desc += (
                    "\nORF-Sendezeit noch "
                    "nicht erkannt. "
                    "Dauer vorläufig."
                )

                fields = [
                    "DTSTART:" + stamp(start),
                    "DTEND:" + stamp(
                        start + timedelta(
                            minutes=90
                        )
                    ),
                ]

                stats["Rennstart"] += 1

            else:
                title += " | vorläufig"

                desc += (
                    "\nNoch keine "
                    "bestätigte Startzeit."
                )

                day = date.fromisoformat(
                    race["datum"]
                )

                fields = [
                    "DTSTART;VALUE=DATE:"
                    + day.strftime("%Y%m%d"),
                    "DTEND;VALUE=DATE:"
                    + (
                        day + timedelta(days=1)
                    ).strftime("%Y%m%d"),
                ]

                stats["Ganztag"] += 1

            if race["wm"]:
                stats["WM"] += 1

            lines.extend([
                "BEGIN:VEVENT",
                "UID:" + uid,
                "DTSTAMP:" + stamp(NOW),
                "X-ORF-RACE-ID:"
                + ics(key),
                *fields,
                "SUMMARY:"
                + ics(title),
                "DESCRIPTION:"
                + ics(desc),
                "END:VEVENT",
            ])

    lines.append("END:VCALENDAR")

    OUTPUT.write_bytes((
        "\r\n".join(fold(lines))
        + "\r\n"
    ).encode("utf-8"))

    total = (
        stats["ORF"]
        + stats["Rennstart"]
        + stats["Ganztag"]
    )

    print(
        "Kalendereinträge:",
        total
    )

    for key, value in stats.items():
        print(key + ":", value)

    print("FERTIG")


def main():
    old = old_races()
    fis = fis_races()

    print(
        "FIS-Weltcuprennen:",
        len(fis)
    )

    races = []
    seen = set()

    # FIS-Rennen ohne Doppelungen.
    for race in fis:
        key = race_key(race)

        if key in seen:
            continue

        seen.add(key)

        if key in old:
            race["uids"] = old[
                key
            ]["uids"].copy()

        races.append(race)

    # WM exakt einmal je Bewerb.
    # Alte WM-Dubletten werden
    # nicht erneut übernommen.
    for day, kind, gender, times in WM:
        race = new_race(
            day,
            "Crans-Montana",
            kind,
            gender,
            True,
        )

        race["starts"] = [
            clock(t, day)
            for t in times
        ]

        key = race_key(race)

        if key in old:
            race["uids"] = old[
                key
            ]["uids"].copy()

        if key not in seen:
            races.append(race)
            seen.add(key)

    program = []
    covered = set()

    try:
        items, days = orf_official()
        program.extend(items)
        covered.update(days)

        print(
            "Offizieller ORF-Sendeplan:",
            len(items)
        )

    except Exception as exc:
        print(
            "Offizieller ORF-Sendeplan "
            "nicht lesbar:",
            exc
        )

    items, days = epg_program()
    program.extend(items)
    covered.update(days)

    # Fehlende FIS-Rennen behalten,
    # wenn ORF noch keine Daten für
    # den Tag hat oder das Rennen
    # dort weiterhin geführt wird.
    held = 0
    removed = 0

    for key, race in old.items():
        if key in seen or race["wm"]:
            continue

        # Vergangene Termine nicht
        # künstlich wieder hinzufügen.
        if race["datum"] < TODAY.isoformat():
            continue

        has_orf = any(
            p["datum"] == race["datum"]
            and p["geschlecht"]
            == race["geschlecht"]
            and p["disziplin"]
            == race["disziplin"]
            for p in program
        )

        if (
            race["datum"] not in covered
            or has_orf
        ):
            races.append(race)
            seen.add(key)
            held += 1
        else:
            removed += 1

    add_starts(races)

    matched = 0

    for item in program:
        race = match_race(
            item, races
        )

        if race:
            add_broadcast(
                race, item
            )
            matched += 1

    add_soelden(races)

    print(
        "ORF-Sendungen zugeordnet:",
        matched
    )

    print(
        "Fehlende FIS-Rennen behalten:",
        held
    )

    print(
        "Fehlende FIS-/ORF-Rennen entfernt:",
        removed
    )

    write_calendar(races)


if __name__ == "__main__":
    main()
