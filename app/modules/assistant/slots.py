# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""What a question is about, read by code before any model sees it.

The router is a 9B model on a 6k context; every detail code can settle
exactly is one fewer thing for it to guess. This reads, without a model:

  * the period: "на прошлой неделе", "в марте", "с 5 по 12 марта",
    "3 месяца назад", "летом", "в последнее время", a date in any format;
  * the people it names — known ones in any case form ("с Машей" is Маша),
    and relation words ("мама", "начальник") even before the diary knows them;
  * the activities it names, from the ones the diary already has;
  * the feelings it names, with the words to widen a search by.

Everything here is pure: no DB, no clock — `today` and the known names are
passed in, so the evaluation set (tools/assistant_eval) can pin them.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta


# ── periods ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Period:
    start: date
    end: date            # inclusive
    kind: str            # day | week | month | year | range | season | recent | anniversary
    label: str

    def as_dict(self) -> dict:
        return {'start': self.start.isoformat(), 'end': self.end.isoformat(),
                'kind': self.kind, 'label': self.label}


# Month stems in every case the questions use: "март", "марта", "марте".
_MONTH_STEMS = [
    (1, r'январ[ьяею]'), (2, r'феврал[ьяею]'), (3, r'март[ае]?'),
    (4, r'апрел[ьяею]'), (5, r'ма[йяею]'), (6, r'июн[ьяею]'),
    (7, r'июл[ьяею]'), (8, r'август[ае]?'), (9, r'сентябр[ьяею]'),
    (10, r'октябр[ьяею]'), (11, r'ноябр[ьяею]'), (12, r'декабр[ьяею]'),
]
_MONTH_RE = '(' + '|'.join(p for _, p in _MONTH_STEMS) + ')'
_MONTH_NAMES_NOM = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
                    'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

_NUM_WORDS = {
    'один': 1, 'одну': 1, 'одна': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4,
    'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9, 'десять': 10,
    'пару': 2, 'пара': 2, 'несколько': 3, 'полгода': 6,
}

_SEASONS = {
    'зим': (12, 2), 'весн': (3, 5), 'лет': (6, 8), 'осен': (9, 11),
}


def _month_of(word: str) -> int | None:
    w = word.lower()
    for num, pat in _MONTH_STEMS:
        if re.fullmatch(pat, w):
            return num
    return None


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _shift_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _last_month_named(month: int, today: date) -> int:
    """The year of the most recent such month that is not in the future."""
    return today.year if month <= today.month else today.year - 1


def _num(tok: str | None) -> int | None:
    if not tok:
        return 1
    tok = tok.lower()
    if tok.isdigit():
        return int(tok)
    return _NUM_WORDS.get(tok)


def _year_word(text: str, today: date) -> int | None:
    """"прошлого года", "этого года", "2025", "в 2025 году" near a month."""
    if re.search(r'\bпрошл\w* год', text):
        return today.year - 1
    if re.search(r'\bпозапрошл\w* год', text):
        return today.year - 2
    if re.search(r'\b(эт\w*|текущ\w*) год', text):
        return today.year
    m = re.search(r'\b(19|20)(\d{2})\b', text)
    return int(m.group(0)) if m else None


def _season(stem: str, qualifier: str, today: date) -> Period:
    """The latest such season that has begun; "прошлым" steps one back.

    In September "этим летом" is the summer just gone and "прошлым летом"
    the one before it. Winter runs December to February and is named by
    both years.
    """
    first, last = _SEASONS[stem]
    starts = []
    for y in range(today.year + 1, today.year - 4, -1):
        start = date(y - 1, 12, 1) if stem == 'зим' else date(y, first, 1)
        if start <= today:
            starts.append((start, y))
    back = 2 if qualifier.startswith('позапрошл') else 1 if qualifier.startswith('прошл') else 0
    start, y = starts[min(back, len(starts) - 1)]
    if stem == 'зим':
        end = date(y, 2, calendar.monthrange(y, 2)[1])
        label = f'зима {y - 1}/{y}'
    else:
        end = _month_bounds(y, last)[1]
        label = {'весн': 'весна', 'лет': 'лето', 'осен': 'осень'}[stem] + f' {y}'
    return Period(start, min(end, today), 'season', label)


def parse_period(text: str, today: date) -> Period | None:
    """The period a question points at, or None.

    Checked from the most specific form to the loosest, so "12 марта" is a
    day and not the month of March, and "с 5 по 12 марта" a range.
    """
    t = ' ' + (text or '').lower().replace('ё', 'е') + ' '

    # Ranges: "с 5 по 12 марта", "с 5 марта по 2 апреля"
    m = re.search(r'\bс\s+(\d{1,2})\s*(?:' + _MONTH_RE + r')?\s+по\s+(\d{1,2})\s+' + _MONTH_RE, t)
    if m:
        d1, mon1, d2, mon2 = m.group(1), m.group(2), m.group(3), m.group(4)
        month2 = _month_of(mon2)
        month1 = _month_of(mon1) if mon1 else month2
        year = _year_word(t, today) or _last_month_named(month2, today)
        try:
            start = date(year, month1, int(d1))
            end = date(year, month2, int(d2))
            if start <= end:
                return Period(start, end, 'range', f'{start.isoformat()} — {end.isoformat()}')
        except ValueError:
            pass

    # One day: ISO, dotted, "12 марта (2025)"
    m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', t)
    if m:
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
            return Period(d, d, 'day', d.isoformat())
        except ValueError:
            pass
    # A two-digit month, or "оценка 7.5" would be the 7th of May.
    m = re.search(r'\b(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?\b', t)
    if m:
        year = int(m[3]) if m[3] else None
        if year is not None and year < 100:
            year += 2000
        try:
            d = date(year or today.year, int(m[2]), int(m[1]))
            if year is None and d > today:
                d = d.replace(year=today.year - 1)
            return Period(d, d, 'day', d.isoformat())
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})\s+' + _MONTH_RE + r'(?:\s+(\d{4}))?', t)
    if m:
        month = _month_of(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        try:
            d = date(year or today.year, month, int(m.group(1)))
            if year is None and d > today:
                d = d.replace(year=today.year - 1)
            return Period(d, d, 'day', d.isoformat())
        except ValueError:
            pass

    # Named days
    for word, back in (('позавчера', 2), ('вчера', 1), ('сегодня', 0)):
        if re.search(r'\b' + word + r'\b', t):
            d = today - timedelta(days=back)
            return Period(d, d, 'day', d.isoformat())

    # "год назад", "в это время год назад" — the same day a year back
    if re.search(r'\b(год назад|в прошлом году в эт\w* (же )?(врем|день|дат)'
                 r'|в эт\w* (же )?(день|дат\w*) (в )?прошл\w* год)', t):
        d = today.replace(year=today.year - 1) if not (today.month == 2 and today.day == 29) \
            else date(today.year - 1, 2, 28)
        return Period(d - timedelta(days=3), d + timedelta(days=3), 'anniversary',
                      f'около {d.isoformat()}')

    # Weeks
    monday = today - timedelta(days=today.weekday())
    if re.search(r'\bпозапрошл\w* недел', t):
        s = monday - timedelta(days=14)
        return Period(s, s + timedelta(days=6), 'week', 'позапрошлая неделя')
    if re.search(r'\bпрошл\w* недел', t):
        s = monday - timedelta(days=7)
        return Period(s, s + timedelta(days=6), 'week', 'прошлая неделя')
    if re.search(r'\b(эт\w*|текущ\w*) недел', t):
        return Period(monday, today, 'week', 'эта неделя')

    # "последние N дней/недель/месяцев", "за последний месяц", "в последнее время"
    m = re.search(r'\bпоследн\w*\s+(\d+|\w+)?\s*(дн|день|дня|недел|месяц|год|лет)', t)
    if m:
        n = _num(m.group(1)) if m.group(1) and not m.group(1).startswith('недел') else 1
        unit = m.group(2)
        if n:
            days = n * (7 if unit.startswith('недел') else 30 if unit.startswith('месяц')
                        else 365 if unit in ('год', 'лет') else 1)
            return Period(today - timedelta(days=days - 1), today, 'recent',
                          f'последние {days} дн.')
    if re.search(r'\b(в последнее время|последнее время|последнее врем|в последние дни|недавно)\b', t):
        return Period(today - timedelta(days=29), today, 'recent', 'последние 30 дн.')

    if re.search(r'\bполгода назад', t):
        s6 = _shift_months(today.replace(day=1), -6)
        a, b = _month_bounds(s6.year, s6.month)
        return Period(a, b, 'month', f'{_MONTH_NAMES_NOM[s6.month]} {s6.year}')

    # "N дней/недель/месяцев/лет назад" — the unit that far back
    m = re.search(r'\b(\d+|\w+)?\s*(дн\w*|день|недел\w*|месяц\w*|год\w*|лет)\s+назад', t)
    if m and _num(m.group(1)):
        n = _num(m.group(1))
        unit = m.group(2)
        if unit.startswith('недел'):
            s = monday - timedelta(days=7 * n)
            return Period(s, s + timedelta(days=6), 'week', f'{n} нед. назад')
        if unit.startswith('месяц'):
            s = _shift_months(today.replace(day=1), -n)
            a, b = _month_bounds(s.year, s.month)
            return Period(a, b, 'month', f'{_MONTH_NAMES_NOM[s.month]} {s.year}')
        if unit.startswith('год') or unit == 'лет':
            y = today.year - n
            return Period(date(y, 1, 1), date(y, 12, 31), 'year', str(y))
        d = today - timedelta(days=n)
        return Period(d, d, 'day', d.isoformat())

    # Months: "в марте", "в марте 2025", "в прошлом/этом месяце"
    if re.search(r'\bпозапрошл\w* месяц', t):
        s = _shift_months(today.replace(day=1), -2)
        a, b = _month_bounds(s.year, s.month)
        return Period(a, b, 'month', f'{_MONTH_NAMES_NOM[s.month]} {s.year}')
    if re.search(r'\bпрошл\w* месяц', t):
        s = _shift_months(today.replace(day=1), -1)
        a, b = _month_bounds(s.year, s.month)
        return Period(a, b, 'month', f'{_MONTH_NAMES_NOM[s.month]} {s.year}')
    if re.search(r'\b(эт\w*|текущ\w*) месяц', t):
        return Period(today.replace(day=1), today, 'month',
                      f'{_MONTH_NAMES_NOM[today.month]} {today.year}')
    m = re.search(r'\b' + _MONTH_RE + r'\b', t)
    if m:
        month = _month_of(m.group(1))
        year = _year_word(t, today) or _last_month_named(month, today)
        a, b = _month_bounds(year, month)
        return Period(a, b, 'month', f'{_MONTH_NAMES_NOM[month]} {year}')

    # Seasons: "летом", "прошлой зимой", "этой осенью", "прошлого лета"
    m = re.search(r'\b(прошл\w*\s+|эт\w*\s+|позапрошл\w*\s+)?(зим|весн|лет|осен)'
                  r'(ой|ом|у|а|е|ы|о|ью|ь)\b', t)
    if m and not re.search(r'\bлет\s+назад', t):
        return _season(m.group(2), (m.group(1) or '').strip(), today)

    # "в начале года", "в конце прошлого года" — a quarter of it
    m = re.search(r'\b(начал|конц|конец|середин)\w*\s+(прошл\w*\s+|эт\w*\s+)?год', t)
    if m:
        y = today.year - 1 if (m.group(2) or '').startswith('прошл') else today.year
        if m.group(1).startswith('начал'):
            a, b = date(y, 1, 1), date(y, 3, 31)
        elif m.group(1).startswith('середин'):
            a, b = date(y, 5, 1), date(y, 8, 31)
        else:
            a, b = date(y, 10, 1), date(y, 12, 31)
        if a <= today:
            return Period(a, min(b, today), 'range', f'{a.isoformat()} — {min(b, today).isoformat()}')

    # Years: "в этом году", "в прошлом году", "в 2025"
    if re.search(r'\bпозапрошл\w* год', t):
        y = today.year - 2
        return Period(date(y, 1, 1), date(y, 12, 31), 'year', str(y))
    if re.search(r'\bпрошл\w* год', t):
        y = today.year - 1
        return Period(date(y, 1, 1), date(y, 12, 31), 'year', str(y))
    if re.search(r'\b(эт\w*|текущ\w*|мо\w*|нынешн\w*) год|\bитог\w* год', t):
        return Period(date(today.year, 1, 1), today, 'year', str(today.year))
    m = re.search(r'\b(20\d{2})\b', t)
    if m:
        y = int(m.group(1))
        return Period(date(y, 1, 1), min(date(y, 12, 31), today), 'year', str(y))
    return None


def previous_period(p: Period) -> Period:
    """The period of the same kind just before `p`: the month before a
    month, the same season a year earlier, the N days before "the last N
    days". What a question like "стало хуже?" is measured against."""
    if p.kind == 'month':
        s = _shift_months(p.start.replace(day=1), -1)
        a, b = _month_bounds(s.year, s.month)
        return Period(a, b, 'month', f'{_MONTH_NAMES_NOM[s.month]} {s.year}')
    if p.kind == 'year':
        y = p.start.year - 1
        return Period(date(y, 1, 1), date(y, 12, 31), 'year', str(y))
    if p.kind == 'week':
        s = p.start - timedelta(days=7)
        return Period(s, s + timedelta(days=6), 'week', f'неделя с {s.isoformat()}')
    if p.kind == 'season':
        a = p.start.replace(year=p.start.year - 1)
        b = _month_bounds(p.start.year - 1 + (1 if p.start.month == 12 else 0),
                          (p.start.month + 2 - 1) % 12 + 1)[1]
        return Period(a, b, 'season', p.label.split(' ')[0] + f' {b.year}'
                      if p.start.month != 12 else f'зима {a.year}/{b.year}')
    days = (p.end - p.start).days + 1
    b = p.start - timedelta(days=1)
    a = b - timedelta(days=days - 1)
    return Period(a, b, 'range', f'{a.isoformat()} — {b.isoformat()}')


# What separates the two sides of a comparison: "март и апрель", "лучше,
# чем в прошлом", "август от июля", "лето лучше зимы".
_COMPARE_SPLIT = re.compile(
    r',|\s(?:и|чем|от|или|против|vs|лучше|хуже|счастливее|спокойнее|веселее|'
    r'грустнее|тяжелее|легче|отличается|отличался|отличалась|отличалось)\s', re.I)


def compare_pair(text: str, today: date) -> tuple[Period, Period] | None:
    """The two periods a comparison question names, earlier first.

    One named period is compared with the one before it ("этот месяц лучше
    прошлого?"); "сейчас vs год назад" compares the last thirty days with
    the same days a year earlier. None when the question names no period.
    """
    found = []
    for part in _COMPARE_SPLIT.split(' ' + (text or '') + ' '):
        p = parse_period(part, today)
        if p and all((p.start, p.end) != (q.start, q.end) for q in found):
            found.append(p)
    if len(found) >= 2:
        a, b = sorted(found[:2], key=lambda p: p.start)
        return a, b
    if not found:
        return None
    p = found[0]
    if p.kind == 'anniversary':
        now = Period(today - timedelta(days=29), today, 'recent', 'последние 30 дн.')
        a = now.start.replace(year=now.start.year - 1)
        b = today.replace(year=today.year - 1) if not (today.month == 2 and today.day == 29) \
            else date(today.year - 1, 2, 28)
        return Period(a, b, 'range', f'{a.isoformat()} — {b.isoformat()}'), now
    return previous_period(p), p


# ── people, activities, feelings ──────────────────────────────

# Relation words that point at a person even before the diary has them as a
# named mention. Lemmas.
RELATION_WORDS = {
    'мама', 'мать', 'папа', 'отец', 'брат', 'сестра', 'бабушка', 'дедушка',
    'сын', 'дочь', 'дочка', 'муж', 'жена', 'парень', 'девушка', 'друг',
    'подруга', 'начальник', 'начальница', 'босс', 'коллега', 'тётя', 'тетя',
    'дядя', 'партнёр', 'партнер', 'психолог', 'терапевт', 'родитель',
}

# Canonical feeling → lemmas that name it, the most telling first: a search
# takes the first few, the rest only recognise the feeling in a question.
EMOTIONS = {
    'тревога': ('тревога', 'тревожность', 'беспокойство', 'паника', 'тревожный',
                'тревожно', 'тревожиться', 'беспокоиться', 'волнение', 'волноваться',
                'панический', 'нервничать', 'нервы'),
    'грусть': ('грусть', 'тоска', 'печаль', 'грустно', 'грустный', 'печально',
               'тоскливо', 'уныние', 'хандра', 'плакать'),
    'одиночество': ('одиночество', 'одиноко', 'одинокий'),
    'злость': ('злость', 'раздражение', 'гнев', 'злиться', 'злой', 'раздражать',
               'раздражительный', 'раздражительность', 'бесить', 'ярость'),
    'усталость': ('усталость', 'выгорание', 'истощение', 'устать', 'уставать',
                  'усталый', 'выгореть', 'вымотанный', 'измотанный'),
    'страх': ('страх', 'бояться', 'боязнь', 'испуг', 'страшно'),
    'радость': ('радость', 'счастье', 'радостно', 'радоваться', 'счастливый',
                'счастлив', 'кайф'),
    'вина': ('вина', 'стыд', 'виноватый', 'стыдно'),
    'апатия': ('апатия', 'безразличие', 'пустота', 'бессмысленность'),
    'спокойствие': ('спокойствие', 'умиротворение', 'покой', 'спокойно'),
    'обида': ('обида', 'обидно', 'обидеть', 'обижаться'),
    'стресс': ('стресс', 'напряжение', 'перегрузка', 'давление'),
    'мотивация': ('мотивация', 'прокрастинация', 'лень', 'откладывать'),
    'сон': ('сон', 'бессонница', 'недосып', 'спать', 'выспаться', 'уснуть',
            'заснуть', 'засыпать'),
}


def _lemmas(text: str) -> list[str]:
    """Lemmas of the words, in order. Falls back to lowercased words when the
    morphology dictionary is unavailable."""
    from app import people_match
    words = re.findall(r'\w+', (text or '').lower().replace('ё', 'е'))
    return [people_match._lemma(w) for w in words]


def find_people(text: str, known: list[str] | tuple = ()) -> list[str]:
    """People the question names: known diary names in any case form, then
    relation words. In order of appearance, without repeats."""
    from app import people_match
    lemmas = _lemmas(text)
    words = re.findall(r'\w+', (text or '').lower().replace('ё', 'е'))
    found = []
    for name in known:
        # Declined forms of the name itself, as "My people" matches them —
        # lemmatising the question would turn "Лену" into "лён".
        positions = []
        for part in re.findall(r'\w+', name.lower()):
            forms = {f.replace('ё', 'е') for f in people_match.name_forms(part)}
            forms.add(part.replace('ё', 'е'))
            hits = [i for i, w in enumerate(words) if w in forms]
            if not hits:
                break
            positions.append(hits[0])
        else:
            if positions:
                found.append((min(positions), name))
    named_at = {pos for pos, _ in found}
    for i, lem in enumerate(lemmas):
        if lem not in RELATION_WORDS or any(n.lower() == lem for _, n in found):
            continue
        # "брат Илья" is one person, already found by name.
        if named_at & {i - 1, i + 1}:
            continue
        found.append((i, lem))
    seen, out = set(), []
    for _, name in sorted(found):
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def find_activities(text: str, known: list[str] | tuple = ()) -> list[str]:
    """Activities from the diary's own labels that the question names."""
    from app import people_match
    lemma_set = set(_lemmas(text))
    out = []
    for label in known:
        forms = {people_match._lemma(w) for w in re.findall(r'\w+', label.lower())}
        if forms and forms <= lemma_set:
            out.append(label)
    return out


def find_emotions(text: str) -> list[str]:
    """Canonical feelings the question names."""
    lemma_set = set(_lemmas(text))
    return [canon for canon, words in EMOTIONS.items() if lemma_set.intersection(words)]


def emotion_synonyms(canonical: str) -> list[str]:
    return list(EMOTIONS.get(canonical, ()))


# ── filters: which days ───────────────────────────────────────

_BAD_DAYS = re.compile(r'\b(плох\w*|тяж[её]л\w*|худш\w*|грустн\w*|паршив\w*)\s+(дн\w*|день)', re.I)
_GOOD_DAYS = re.compile(r'\b(хорош\w*|лучш\w*|светл\w*|счастлив\w*|радостн\w*)\s+(дн\w*|день)', re.I)

# Recurring weekdays only: "по понедельникам", "понедельники". A single "в
# пятницу" is usually a date ("что было в пятницу"), not a pattern.
_WEEKDAY_STEMS = ['понедельник', 'вторник', 'сред', 'четверг', 'пятниц', 'суббот', 'воскресень']
_WEEKDAY_RE = re.compile(
    r'\b(?:по\s+(' + '|'.join(_WEEKDAY_STEMS) + r')\w*|(' + '|'.join(_WEEKDAY_STEMS)
    + r')(?:и|ы|ам|ах)\b)', re.I)

_WEATHER_WORDS = [
    (re.compile(r'\bдожд\w*|\bливн\w*', re.I), 'Rain'),
    (re.compile(r'\bснег\w*|\bснеж\w*|\bснегопад', re.I), 'Snow'),
    (re.compile(r'\bгроз\w*', re.I), 'Thunderstorm'),
    (re.compile(r'\bтуман\w*', re.I), 'Fog'),
    (re.compile(r'\bпасмурн\w*|\bоблачн\w*', re.I), 'Clouds'),
    (re.compile(r'\bсолнечн\w*|\bясн\w*\s+(?:дн|погод|день)', re.I), 'Clear'),
]


def find_rating(text: str) -> tuple[str, int] | None:
    """("max", 4) for "плохие дни", ("min", 7) for "хорошие дни"."""
    t = (text or '').replace('ё', 'е')
    bad, good = _BAD_DAYS.search(t), _GOOD_DAYS.search(t)
    # "Чем хорошие дни отличаются от плохих?" compares them; it filters nothing.
    if bad and good or re.search(r'\bот\s+плох|\bот\s+хорош|\bи\s+плох|\bи\s+хорош', t, re.I):
        return None
    if bad:
        return ('max', 4)
    if good:
        return ('min', 7)
    return None


def find_weekday(text: str) -> int | None:
    m = _WEEKDAY_RE.search(text or '')
    if not m:
        return None
    stem = (m.group(1) or m.group(2)).lower()
    return next(i for i, s in enumerate(_WEEKDAY_STEMS) if stem.startswith(s))


def find_weather(text: str) -> str | None:
    """The weather condition a question names, as signals store it."""
    for pattern, key in _WEATHER_WORDS:
        if pattern.search(text or ''):
            return key
    return None


# ── all of it ─────────────────────────────────────────────────

@dataclass
class Slots:
    period: Period | None = None
    people: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    emotions: list[str] = field(default_factory=list)
    rating: tuple[str, int] | None = None
    weekday: int | None = None
    weather: str | None = None

    def as_dict(self) -> dict:
        return {'period': self.period.as_dict() if self.period else None,
                'people': self.people, 'activities': self.activities,
                'emotions': self.emotions, 'rating': self.rating,
                'weekday': self.weekday, 'weather': self.weather}

    def filters(self) -> dict:
        """entries_query arguments for the day filters found."""
        out = {}
        if self.rating:
            out['max_rating' if self.rating[0] == 'max' else 'min_rating'] = self.rating[1]
        if self.weekday is not None:
            out['weekday'] = self.weekday
        if self.weather:
            out['weather'] = self.weather
        return out

    def describe(self) -> str:
        """One line per detected detail, for the router prompt."""
        lines = []
        if self.period:
            lines.append(f'- период: {self.period.label} ({self.period.start} — {self.period.end})')
        if self.people:
            lines.append('- люди: ' + ', '.join(self.people))
        if self.activities:
            lines.append('- занятия: ' + ', '.join(self.activities))
        if self.emotions:
            lines.append('- чувства: ' + ', '.join(self.emotions))
        if self.rating:
            lines.append('- дни: ' + ('плохие' if self.rating[0] == 'max' else 'хорошие'))
        if self.weekday is not None:
            lines.append('- день недели: ' + _WEEKDAY_STEMS[self.weekday])
        if self.weather:
            lines.append('- погода: ' + self.weather)
        return '\n'.join(lines)


def extract_slots(text: str, today: date, known_people=(), known_activities=()) -> Slots:
    return Slots(
        period=parse_period(text, today),
        people=find_people(text, known_people),
        activities=find_activities(text, known_activities),
        emotions=find_emotions(text),
        rating=find_rating(text),
        weekday=find_weekday(text),
        weather=find_weather(text),
    )
