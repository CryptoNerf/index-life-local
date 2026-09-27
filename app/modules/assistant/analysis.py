# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""The AI psychologist's analytic tools, as pure functions over days.

Each takes the list from `daybook.load_days` and returns text for the
model: what changed between two periods, what separates good days from bad,
one person over time, a filtered list of entries, rhythms, themes. No
database and no clock (the caller passes `today`), so the tests plant a
pattern in a made-up diary and check that the tool finds it.

The text is written for the model, compact and with numbers it can cite.
It avoids long dashes: the model copies the formatting it is shown.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from typing import Iterable

from .daybook import Day
from .llm_text import ru_date, ru_span

BAD = 4    # a rating at or below this is a bad day
GOOD = 7   # at or above, a good one

WEEKDAYS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
WEEKDAYS_FULL = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница',
                 'суббота', 'воскресенье']
MONTHS = ['', 'янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен',
          'окт', 'ноя', 'дек']
WEATHER_RU = {'Clear': 'ясно', 'Clouds': 'облачно', 'Fog': 'туман',
              'Rain': 'дождь', 'Snow': 'снег', 'Thunderstorm': 'гроза',
              'Other': 'другая погода'}
TONE_RU = {'positive': 'тепло', 'neutral': 'нейтрально', 'negative': 'негативно'}


# ── small helpers ─────────────────────────────────────────────

def _avg(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _span(a: date, b: date) -> str:
    return ru_span(a, b)


def _in(days: Iterable[Day], start: date, end: date) -> list[Day]:
    return [d for d in days if start <= d.date <= end]


def _tone_score(tones: Iterable[str]) -> float:
    tones = list(tones)
    if not tones:
        return 0.0
    return (tones.count('positive') - tones.count('negative')) / len(tones)


def _features(day: Day, weekday: bool = False) -> set[str]:
    """What a day had, as labels a person can read: 'занятие: бег'."""
    out = {f'занятие: {a}' for a in day.activities}
    out |= {f'человек: {p}' for p in day.people}
    out |= {f'тема: {t}' for t in day.themes}
    if day.weather:
        out.add(f'погода: {WEATHER_RU.get(day.weather, day.weather)}')
    if weekday:
        out.add(f'день недели: {WEEKDAYS_FULL[day.date.weekday()]}')
    return out


def _lifts(days: list[Day], min_days: int = 3) -> dict[str, float]:
    """How much the mood on days with a feature differs from the average."""
    overall = _avg(d.rating for d in days)
    by_feature: dict[str, list[int]] = {}
    for d in days:
        for f in _features(d):
            by_feature.setdefault(f, []).append(d.rating)
    return {f: _avg(r) - overall for f, r in by_feature.items() if len(r) >= min_days}


def _short(day: Day, limit: int = 140) -> str:
    """A day in one line: the summary if there is one, else the note's start."""
    text = day.summary or day.note
    text = ' '.join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip() + '…'
    return f'[{ru_date(day.date)}] {day.rating}/10. {text}'


def _forms(word: str) -> set[str]:
    """Forms a name or word takes in running text."""
    from app import people_match
    w = word.lower().replace('ё', 'е')
    forms = {f.replace('ё', 'е') for f in people_match.name_forms(w)} | {w}
    return {f for f in forms if f}


def _yo(literal: str) -> str:
    """A regex for `literal` that doesn't care whether е is written ё."""
    return ''.join('[её]' if ch in 'её' else re.escape(ch) for ch in literal)


def _stem_re(word: str) -> re.Pattern:
    """A loose match for an ordinary word in any form: 'дождь' finds 'дождём'.
    Lemmatising every note would be slower than it is worth."""
    w = word.lower().replace('ё', 'е').strip()
    stem = w if len(w) <= 4 else w[:max(4, len(w) - 2)]
    return re.compile(r'(?<!\w)' + _yo(stem) + r'\w*', re.I)


def _excerpt(text: str, pattern: re.Pattern, limit: int = 200) -> str:
    """The sentences of `text` that match, or its start."""
    text = ' '.join((text or '').split())
    sentences = re.split(r'(?<=[.!?])\s+', text)
    hits = [s for s in sentences if pattern.search(s)]
    out = ' / '.join(hits[:2]) if hits else text
    if len(out) > limit:
        out = out[:limit].rstrip() + '…'
    return out


def _forms_re(forms: set[str]) -> re.Pattern:
    alts = '|'.join(_yo(f) for f in sorted(forms, key=len, reverse=True))
    return re.compile(r'(?<!\w)(?:' + alts + r')(?!\w)', re.I)


def match_person(name: str, known: Iterable[str]) -> str | None:
    """The diary's canonical name for `name` ("маму" → "Мама"), or None."""
    from app import people_match
    known = list(known)
    target = name.strip().lower().replace('ё', 'е')
    if not target:
        return None
    for k in known:
        if k.lower().replace('ё', 'е') == target:
            return k
    lemma = people_match._lemma(target)
    for k in known:
        kl = k.lower().replace('ё', 'е')
        if target in _forms(kl) or people_match._lemma(kl) == lemma:
            return k
    return None


# ── what changed ──────────────────────────────────────────────

def what_changed(days: list[Day], before: tuple[date, date],
                 after: tuple[date, date]) -> str:
    """The later period against the earlier one: mood, then what appeared,
    disappeared or grew in the days, with each thing's usual effect on mood."""
    a, b = _in(days, *before), _in(days, *after)
    if not b:
        return f'Записей {_span(*after)} нет.'
    if not a:
        return f'Записей {_span(*before)} нет, сравнивать не с чем.'
    ra, rb = [d.rating for d in a], [d.rating for d in b]
    lines = [
        f'Что изменилось. Раньше: {_span(*before)} ({len(a)} записей). '
        f'Теперь: {_span(*after)} ({len(b)} записей).',
        f'- Настроение: {_avg(ra):.1f} → {_avg(rb):.1f} ({_avg(rb) - _avg(ra):+.1f}). '
        f'Плохих дней (≤{BAD}): {_pct(sum(r <= BAD for r in ra), len(ra))}% → '
        f'{_pct(sum(r <= BAD for r in rb), len(rb))}%, хороших (≥{GOOD}): '
        f'{_pct(sum(r >= GOOD for r in ra), len(ra))}% → {_pct(sum(r >= GOOD for r in rb), len(rb))}%.',
    ]

    lifts = _lifts(days)
    ca = Counter(f for d in a for f in _features(d))
    cb = Counter(f for d in b for f in _features(d))
    changes = []
    for f in set(ca) | set(cb):
        sa, sb = ca[f] / len(a), cb[f] / len(b)
        if abs(sb - sa) < 0.15 or max(ca[f], cb[f]) < 2:
            continue
        changes.append((abs(sb - sa), f, sa, sb))
    changes.sort(reverse=True)
    appeared, grew, faded = [], [], []
    for _, f, sa, sb in changes:
        effect = ''
        if f in lifts and abs(lifts[f]) >= 0.3:
            effect = f', обычно {lifts[f]:+.1f} к настроению'
        text = f'{f} ({round(100 * sa)}% дней → {round(100 * sb)}%{effect})'
        if sa == 0:
            appeared.append(text)
        elif sb > sa:
            grew.append(text)
        else:
            faded.append(text)
    for title, items in (('Стало меньше или пропало', faded),
                         ('Появилось', appeared), ('Стало больше', grew)):
        if items:
            lines.append(f'- {title}: ' + '; '.join(items[:4]) + '.')
    if not changes:
        lines.append('- В занятиях, людях, темах и погоде заметных перемен нет.')

    # How people are written about, where both periods have enough of them.
    ta: dict[str, list[str]] = {}
    tb: dict[str, list[str]] = {}
    for d in a:
        for p, tones in d.people.items():
            ta.setdefault(p, []).extend(tones)
    for d in b:
        for p, tones in d.people.items():
            tb.setdefault(p, []).extend(tones)
    tone_lines = []
    for p in set(ta) & set(tb):
        if len(ta[p]) >= 2 and len(tb[p]) >= 2:
            x, y = _tone_score(ta[p]), _tone_score(tb[p])
            if abs(y - x) >= 0.5:
                tone_lines.append(f'{p} ({x:+.1f} → {y:+.1f})')
    if tone_lines:
        lines.append('- Тон упоминаний изменился: ' + ', '.join(tone_lines[:4]) + '.')

    temps_a = [d.temp for d in a if d.temp is not None]
    temps_b = [d.temp for d in b if d.temp is not None]
    if len(temps_a) >= 3 and len(temps_b) >= 3 and abs(_avg(temps_b) - _avg(temps_a)) >= 4:
        lines.append(f'- Средняя температура: {_avg(temps_a):.0f}° → {_avg(temps_b):.0f}°.')

    worst = sorted(b, key=lambda d: (d.rating, d.date))[:2]
    best = sorted(b, key=lambda d: (-d.rating, d.date))[:1]
    lines.append('Самые тяжёлые дни (теперь):')
    lines += [_short(d) for d in worst]
    if best and best[0].rating > worst[-1].rating:
        lines.append('Самый светлый: ' + _short(best[0]))
    return '\n'.join(lines)


# ── good days against bad ─────────────────────────────────────

def contrast_days(days: list[Day], top: int = 7) -> str:
    """What is more common on the user's good days than on their bad ones.

    Good and bad are the top and bottom quarter of this diary's own
    ratings, so someone who rates everything 6 to 8 still gets a contrast.
    """
    if len(days) < 10:
        return 'Записей пока мало для сравнения хороших и плохих дней (нужно хотя бы 10).'
    ratings = sorted(d.rating for d in days)
    low = ratings[len(ratings) // 4]
    high = ratings[(3 * len(ratings)) // 4]
    if low == high:
        return f'Почти все оценки одинаковые ({low}/10), хорошие и плохие дни не различить.'
    good = [d for d in days if d.rating >= high]
    bad = [d for d in days if d.rating <= low]
    if len(good) < 3 or len(bad) < 3:
        return 'Хороших или плохих дней пока слишком мало для сравнения.'

    cg = Counter(f for d in good for f in _features(d, weekday=True))
    cb = Counter(f for d in bad for f in _features(d, weekday=True))
    rows = []
    for f in set(cg) | set(cb):
        sg, sb = cg[f] / len(good), cb[f] / len(bad)
        if abs(sg - sb) < 0.15 or max(cg[f], cb[f]) < 2:
            continue
        rows.append((sg - sb, f))
    rows.sort()
    for_bad = [f for diff, f in rows if diff < 0][:top]
    for_good = [f for diff, f in reversed(rows) if diff > 0][:top]

    lines = [f'Хорошие дни (оценка ≥{high}, {len(good)} дн.) против плохих '
             f'(≤{low}, {len(bad)} дн.), среднее по дневнику {_avg(ratings):.1f}.']

    def describe(f):
        return f'{f} ({cg[f]} из {len(good)} хороших, {cb[f]} из {len(bad)} плохих)'
    lines.append('Чаще в хорошие дни: ' + ('; '.join(map(describe, for_good)) or 'заметных отличий нет') + '.')
    lines.append('Чаще в плохие дни: ' + ('; '.join(map(describe, for_bad)) or 'заметных отличий нет') + '.')
    if not any(d.activities or d.people or d.themes for d in days):
        lines.append('Занятия, люди и темы в записях ещё не размечены, видна только погода и дни недели.')
    lines.append('Примеры хороших дней:')
    lines += [_short(d) for d in sorted(good, key=lambda d: (-d.rating, d.date))[:3]]
    lines.append('Примеры плохих дней:')
    lines += [_short(d) for d in sorted(bad, key=lambda d: (d.rating, d.date))[:3]]
    return '\n'.join(lines)


# ── one person ────────────────────────────────────────────────

def person_deep(days: list[Day], name: str, today: date) -> str:
    """One person across the whole diary: how often, how, and with what."""
    known = Counter(p for d in days for p in d.people)
    if not known:
        return 'Люди в записях ещё не размечены: нужен фоновый разбор записей.'
    key = match_person(name, known)
    if key is None:
        return f'Упоминаний «{name}» в разобранных записях нет.'
    with_p = [d for d in days if key in d.people]
    without = [d for d in days if key not in d.people]
    tones = [t for d in with_p for t in d.people[key]]
    first, last = with_p[0], with_p[-1]
    lines = [
        f'«{key}»: упоминается в {len(with_p)} из {len(days)} записей '
        f'({_pct(len(with_p), len(days))}%). Первое упоминание {ru_date(first.date)}, '
        f'последнее {ru_date(last.date)} ({(today - last.date).days} дн. назад).',
        f'- Тон упоминаний: тепло {tones.count("positive")}, нейтрально '
        f'{tones.count("neutral")}, негативно {tones.count("negative")} '
        f'(итог {_tone_score(tones):+.2f} на шкале от −1 до +1).',
        f'- Настроение в дни с упоминанием {_avg(d.rating for d in with_p):.1f}, '
        f'в остальные {_avg(d.rating for d in without):.1f}.',
    ]

    # Over time: by quarter, or by month for a short history.
    span_days = (last.date - first.date).days
    def bucket(d: date) -> str:
        if span_days > 240:
            return f'{d.year}-Q{(d.month - 1) // 3 + 1}'
        return f'{d.year}-{d.month:02d}'
    buckets: dict[str, list[Day]] = {}
    for d in with_p:
        buckets.setdefault(bucket(d.date), []).append(d)
    parts = []
    for k in list(buckets)[-8:]:
        ds = buckets[k]
        ts = [t for d in ds for t in d.people[key]]
        parts.append(f'{k}: {len(ds)} зап., тон {_tone_score(ts):+.1f}, настроение {_avg(x.rating for x in ds):.1f}')
    if len(parts) > 1:
        lines.append('- По времени: ' + '; '.join(parts) + '.')

    base = Counter(f for d in days for f in _features(d))
    near = Counter(f for d in with_p for f in _features(d) if f != f'человек: {key}')
    together = []
    for f, n in near.most_common():
        if n >= 2 and n / len(with_p) >= 1.5 * base[f] / len(days):
            together.append(f'{f} ({n})')
        if len(together) >= 6:
            break
    if together:
        lines.append('- Чаще обычного в те же дни: ' + ', '.join(together) + '.')

    pattern = _forms_re(set().union(*(_forms(part) for part in re.findall(r'\w+', key))))
    picked: list[Day] = [first]
    hard = [d for d in with_p if _tone_score(d.people[key]) < 0]
    warm = [d for d in with_p if _tone_score(d.people[key]) > 0]
    picked += sorted(hard, key=lambda d: (_tone_score(d.people[key]), d.rating))[:2]
    picked += sorted(warm, key=lambda d: (-_tone_score(d.people[key]), -d.rating))[:2]
    picked += with_p[-3:]
    seen, quotes = set(), []
    for d in sorted(picked, key=lambda d: d.date):
        if d.date in seen:
            continue
        seen.add(d.date)
        tone = ', '.join(sorted({TONE_RU.get(t, t) for t in d.people[key]}))
        quotes.append(f'[{ru_date(d.date)}] {d.rating}/10 ({tone}). {_excerpt(d.note, pattern)}')
    lines.append('Записи (первая, самые тёплые и тяжёлые, последние):')
    lines += quotes
    return '\n'.join(lines)


# ── a filtered list ───────────────────────────────────────────

def entries_query(days: list[Day], *, start: date | None = None, end: date | None = None,
                  min_rating: int | None = None, max_rating: int | None = None,
                  person: str | None = None, activity: str | None = None,
                  weather: str | None = None, weekday: int | None = None,
                  word: str | None = None, limit: int = 25) -> str:
    """Entries matching every filter given, newest first."""
    conditions = []
    picked = days
    if start or end:
        s, e = start or date.min, end or date.max
        picked = [d for d in picked if s <= d.date <= e]
        conditions.append(f'период {_span(start, end)}' if start and end
                          else f'с {ru_date(start, weekday=False)}' if start
                          else f'до {ru_date(end, weekday=False)}')
    if min_rating is not None:
        picked = [d for d in picked if d.rating >= min_rating]
        conditions.append(f'оценка от {min_rating}')
    if max_rating is not None:
        picked = [d for d in picked if d.rating <= max_rating]
        conditions.append(f'оценка до {max_rating}')
    pattern = None
    if person:
        key = match_person(person, {p for d in days for p in d.people})
        forms = set().union(*(_forms(part) for part in re.findall(r'\w+', person))) or {person.lower()}
        if key:
            forms |= set().union(*(_forms(part) for part in re.findall(r'\w+', key)))
        pattern = _forms_re(forms)
        picked = [d for d in picked if (key and key in d.people) or pattern.search(d.note)]
        conditions.append(f'человек «{key or person}»')
    if activity:
        act = activity.lower().strip()
        act_re = _stem_re(act)
        picked = [d for d in picked if any(act_re.search(a) for a in d.activities)
                  or act_re.search(d.note)]
        conditions.append(f'занятие «{activity}»')
        pattern = pattern or act_re
    if weather:
        picked = [d for d in picked if d.weather == weather]
        conditions.append(f'погода: {WEATHER_RU.get(weather, weather)}')
    if weekday is not None:
        picked = [d for d in picked if d.date.weekday() == weekday]
        conditions.append(WEEKDAYS_FULL[weekday])
    if word:
        # "одиночество|одиноко|одинокий": any of them, each in any form.
        words = [w.strip() for w in re.split(r'[|,]', word) if w.strip()]
        word_re = re.compile('|'.join(_stem_re(w).pattern for w in words), re.I)
        picked = [d for d in picked if word_re.search(d.note) or word_re.search(d.summary)
                  or any(word_re.search(t) for t in d.themes)]
        conditions.append('слово ' + ', '.join(f'«{w}»' for w in words))
        pattern = word_re

    label = ', '.join(conditions) or 'все записи'
    if not picked:
        return f'Записей не найдено ({label}).'
    lines = [f'Найдено {len(picked)} записей ({label}), среднее настроение '
             f'{_avg(d.rating for d in picked):.1f}/10.']
    if (picked[-1].date - picked[0].date).days > 60 and len(picked) < len(days):
        # How often, month by month, against how many entries each month has:
        # "стал реже тревожиться?" is answered by this line.
        total = Counter(d.date.strftime('%Y-%m') for d in days)
        hits = Counter(d.date.strftime('%Y-%m') for d in picked)
        months = [m for m in sorted(total) if picked[0].date.strftime('%Y-%m') <= m][-12:]
        lines.append('По месяцам (совпало / всего записей): ' + ', '.join(
            f'{m} {hits[m]}/{total[m]}' for m in months) + '.')
    shown = picked
    if len(picked) > limit:
        step = len(picked) / limit
        shown = [picked[int(i * step)] for i in range(limit)]
        lines.append(f'Показаны {limit}, равномерно по времени.')
    for d in reversed(shown):
        if pattern is not None:
            w = f' [{WEATHER_RU.get(d.weather, d.weather)}]' if weather and d.weather else ''
            lines.append(f'[{ru_date(d.date)}] {d.rating}/10{w}. {_excerpt(d.note, pattern)}')
        else:
            lines.append(_short(d, 200))
    return '\n'.join(lines)


# ── rhythms ───────────────────────────────────────────────────

def _season(month: int) -> str:
    return {12: 'зима', 1: 'зима', 2: 'зима', 3: 'весна', 4: 'весна', 5: 'весна',
            6: 'лето', 7: 'лето', 8: 'лето'}.get(month, 'осень')


def rhythms(days: list[Day]) -> str:
    """Mood by weekday, weekend, month of the year, season and year, and
    the stretches of low days with when they happened."""
    if len(days) < 14:
        return 'Записей пока мало для ритмов (нужно хотя бы две недели).'
    overall = _avg(d.rating for d in days)
    lines = [f'Ритмы настроения по {len(days)} записям, среднее {overall:.1f}/10.']

    by_wd: dict[int, list[int]] = {}
    for d in days:
        by_wd.setdefault(d.date.weekday(), []).append(d.rating)
    wd = [(i, _avg(r), len(r)) for i, r in sorted(by_wd.items())]
    lines.append('- Дни недели: ' + ', '.join(f'{WEEKDAYS[i]} {a:.1f} ({n})' for i, a, n in wd) + '.')
    solid = [x for x in wd if x[2] >= 4]
    if len(solid) >= 3:
        hi, lo = max(solid, key=lambda x: x[1]), min(solid, key=lambda x: x[1])
        if hi[1] - lo[1] >= 0.4:
            lines.append(f'  Лучший день недели: {WEEKDAYS_FULL[hi[0]]} ({hi[1] - overall:+.1f} к среднему), '
                         f'худший: {WEEKDAYS_FULL[lo[0]]} ({lo[1] - overall:+.1f}).')
        else:
            lines.append('  Заметной разницы между днями недели нет.')
    work = [d.rating for d in days if d.date.weekday() < 5]
    rest = [d.rating for d in days if d.date.weekday() >= 5]
    if len(work) >= 5 and len(rest) >= 3:
        lines.append(f'- Будни {_avg(work):.1f} ({len(work)}), выходные {_avg(rest):.1f} ({len(rest)}).')

    span = (days[-1].date - days[0].date).days
    if span >= 150:
        by_m: dict[int, list[int]] = {}
        for d in days:
            by_m.setdefault(d.date.month, []).append(d.rating)
        lines.append('- Месяцы года: ' + ', '.join(
            f'{MONTHS[m]} {_avg(r):.1f} ({len(r)})' for m, r in sorted(by_m.items())) + '.')
        by_s: dict[str, list[int]] = {}
        for d in days:
            by_s.setdefault(_season(d.date.month), []).append(d.rating)
        lines.append('- Времена года: ' + ', '.join(
            f'{s} {_avg(by_s[s]):.1f} ({len(by_s[s])})' for s in ('зима', 'весна', 'лето', 'осень')
            if s in by_s) + '.')
    years = sorted({d.date.year for d in days})
    if len(years) > 1:
        lines.append('- По годам: ' + ', '.join(
            f'{y} {_avg(d.rating for d in days if d.date.year == y):.1f}' for y in years) + '.')

    # A dip is a run of days in the bottom quarter that are also clearly
    # below the average; the quarter alone catches ordinary noise.
    ratings = sorted(d.rating for d in days)
    cut = min(ratings[len(ratings) // 4], int(overall - 1))
    if cut >= 1:
        dips, run = [], []
        for d in days:
            if d.rating <= cut and (not run or (d.date - run[-1].date).days <= 2):
                run.append(d)
                continue
            if len(run) >= 3:
                dips.append(run)
            run = [d] if d.rating <= cut else []
        if len(run) >= 3:
            dips.append(run)
        if dips:
            deepest = sorted(dips, key=lambda r: -len(r) * (overall - _avg(x.rating for x in r)))[:8]
            lines.append(f'- Спады (3 и больше записей подряд с оценкой ≤{cut}), всего {len(dips)}'
                         + (', самые глубокие' if len(dips) > 8 else '') + ': ' + '; '.join(
                f'{_span(r[0].date, r[-1].date)} ({len(r)} зап., {_avg(x.rating for x in r):.1f})'
                for r in sorted(deepest, key=lambda r: r[0].date)) + '.')
            # The same month in different years is what "every February"
            # means; several dips inside one February are not a pattern.
            years_by_month: dict[int, set[int]] = {}
            for r in dips:
                years_by_month.setdefault(r[0].date.month, set()).add(r[0].date.year)
            repeated = [f'{MONTHS[m]} ({", ".join(map(str, sorted(ys)))})'
                        for m, ys in sorted(years_by_month.items()) if len(ys) > 1]
            if repeated:
                lines.append('  Спады в один и тот же месяц разных лет: ' + ', '.join(repeated) + '.')
        else:
            lines.append('- Затяжных спадов (3+ плохих записи подряд) не было.')
    return '\n'.join(lines)


# ── themes ────────────────────────────────────────────────────

def themes(days: list[Day], today: date, start: date | None = None,
           end: date | None = None, clusters: list[tuple[str, int]] | None = None,
           top: int = 12) -> str:
    """What the entries are about: the most frequent themes with the mood
    they come with, the ones of hard days, and what has grown lately."""
    with_themes = [d for d in days if d.themes]
    if not with_themes:
        return 'Темы записей ещё не выделены: нужен фоновый разбор записей.'
    overall = _avg(d.rating for d in with_themes)
    scope = with_themes
    label = 'по всему дневнику'
    if start or end:
        scope = _in(with_themes, start or date.min, end or date.max)
        label = _span(start or with_themes[0].date, end or today)
        if not scope:
            return f'Записей с темами {label} нет.'

    def stats(ds):
        by: dict[str, list[int]] = {}
        for d in ds:
            for t in d.themes:
                by.setdefault(t, []).append(d.rating)
        return by

    by = stats(scope)
    ranked = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top]
    lines = [f'Темы записей {label} ({len(scope)} записей):']
    lines.append('- Чаще всего: ' + '; '.join(
        f'{t} {len(r)} ({_pct(len(r), len(scope))}%, настроение {_avg(r) - overall:+.1f})'
        for t, r in ranked) + '.')
    heavy = sorted(((t, _avg(r), len(r)) for t, r in by.items() if len(r) >= 3),
                   key=lambda x: x[1])[:5]
    heavy = [x for x in heavy if x[1] < overall - 0.3]
    if heavy:
        lines.append('- Темы тяжёлых дней: ' + '; '.join(
            f'{t} (настроение {a:.1f}, {n} зап.)' for t, a, n in heavy) + '.')

    # What grew: the scope (or the last 60 days) against the rest of the diary.
    if start or end:
        recent = scope
    else:
        recent = _in(with_themes, today - timedelta(days=59), today)
    inside = {d.date for d in recent}
    base = [d for d in with_themes if d.date not in inside]
    if len(recent) >= 5 and len(base) >= 5:
        rb, bb = stats(recent), stats(base)
        grew = []
        for t, r in rb.items():
            share_r, share_b = len(r) / len(recent), len(bb.get(t, [])) / len(base)
            if len(r) >= 2 and share_r - share_b >= 0.1:
                grew.append((share_r - share_b, t, share_r, share_b))
        grew.sort(reverse=True)
        if grew:
            what = label if (start or end) else 'за последние 60 дней'
            lines.append(f'- Чаще обычного {what}: ' + '; '.join(
                f'{t} ({round(100 * sb)}% → {round(100 * sr)}%)' for _, t, sr, sb in grew[:5]) + '.')
    if clusters:
        lines.append('- Смысловые кластеры карты мыслей: ' + ', '.join(
            f'{lbl} ({n})' for lbl, n in clusters[:8]) + '.')
    return '\n'.join(lines)
