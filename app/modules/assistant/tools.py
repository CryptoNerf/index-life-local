# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Read-only diary lookups exposed to the AI psychologist's tool router.

These were the tail half of memory.py. They are a distinct, self-contained
concern: each is a pure "DB query → formatted string" with no LLM call and
no module-level state, called from routes._execute_tool when the router LLM
decides the user's question needs specific grounding data. Splitting them
out shrinks the largest file and — unlike the streaming/model-loading code
they used to sit beside — makes them unit-testable without a loaded model.

The string outputs are injected into the main LLM call's system prompt, so
they stay cheap (DB only) and safe to call from inside the streaming
generator.
"""
import logging
import re

from app import db
from app.models import MoodEntry, EntryPerson, EntryActivity, PersonAlias
from .llm_text import ru_date
from .memory import search_relevant_entries, _normalize_mention

log = logging.getLogger(__name__)


def _format_entry_line(entry: MoodEntry, extra: str = '', max_note: int = 280) -> str:
    """One-line representation of an entry suitable for LLM context."""
    from app.note_text import plain_text
    note = plain_text(entry.note).strip()
    if len(note) > max_note:
        note = note[:max_note].rstrip() + '...'
    suffix = f' [{extra}]' if extra else ''
    return f'[{ru_date(entry.date)}] {entry.rating}/10{suffix}. {note}'


def _excerpt_around_term(note: str, term: str, window_chars: int = 280) -> str:
    """Return sentences from `note` that contain `term`, falling back to a
    char-window around the first match if no sentence boundaries are found.

    Lets the LLM see the actual context where a name/topic is mentioned —
    much more informative than the first 280 chars of the entry, which
    often have nothing to do with the lookup target.
    """
    note = (note or '').strip()
    if not note:
        return ''
    if not term:
        return note[:window_chars] + ('...' if len(note) > window_chars else '')

    term_l = term.lower()
    # Sentence split — Russian uses '.', '!', '?', plus newlines as separators.
    sentences = re.split(r'(?<=[.!?])\s+|\n+', note)
    matches = [s for s in sentences if s and term_l in s.lower()]
    if matches:
        out = ' / '.join(s.strip() for s in matches[:3])
        if len(out) > window_chars:
            out = out[:window_chars].rstrip() + '...'
        return out

    # No sentence-level hit — fall back to a char-window around the first match
    idx = note.lower().find(term_l)
    if idx == -1:
        return note[:window_chars] + ('...' if len(note) > window_chars else '')
    half = window_chars // 2
    start = max(0, idx - half)
    end = min(len(note), idx + len(term) + half)
    chunk = note[start:end].strip()
    prefix = '...' if start > 0 else ''
    suffix = '...' if end < len(note) else ''
    return prefix + chunk + suffix


def diary_vocabulary(max_people: int = 300, max_activities: int = 200):
    """(people, activities) the diary knows, most mentioned first.

    People are alias-resolved canonical names, as "My people" shows them.
    The scenario router's slot parser matches a question against these, so
    "с Машей" finds Маша even though no rule knows the name.
    """
    from sqlalchemy import func
    aliases = {a.alias: a.canonical for a in PersonAlias.query.all()}

    def resolve(n: str) -> str:
        seen: set = set()
        while n in aliases and n not in seen:
            seen.add(n)
            n = aliases[n]
        return n

    counts: dict[str, int] = {}
    for mention, n in (db.session.query(EntryPerson.mention, func.count())
                       .group_by(EntryPerson.mention).all()):
        name = resolve(_normalize_mention(mention))
        if name:
            counts[name] = counts.get(name, 0) + n
    people = [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:max_people]
    activities = [a for a, _ in (db.session.query(EntryActivity.activity, func.count())
                                 .group_by(EntryActivity.activity)
                                 .order_by(func.count().desc())
                                 .limit(max_activities).all())]
    return people, activities


def tool_topic_search(query: str, limit: int = 8) -> str:
    """Semantic search over entries for a topic-style query.

    Used when the user asks abstract questions ("when was I most
    anxious?", "patterns around my work stress"). Backed by the
    existing embedding index, so it's fast and free of LLM cost.
    """
    query = (query or '').strip()
    if not query:
        return ''
    try:
        entries = search_relevant_entries(query, top_k=limit, min_score=0.30)
    except Exception as exc:
        log.warning(f'tool_topic_search failed: {exc}')
        return ''
    if not entries:
        return f'По теме «{query}» подходящих записей не найдено.'
    lines = [f'Записи, найденные по теме «{query}»:']
    for e in entries:
        lines.append(_format_entry_line(e))
    return '\n'.join(lines)


def tool_person_history(name: str, limit: int = 30) -> str:
    """All entries that mention a specific person, alias-resolved.

    Uses entry_people + person_aliases — gives the LLM a complete view
    of the user's history with one person, not just the semantic-top-K.
    """
    name = (name or '').strip()
    if not name:
        return ''

    from app.models import PersonAlias, EntryPerson

    aliases = {a.alias: a.canonical for a in PersonAlias.query.all()}

    def resolve(n: str) -> str:
        seen: set = set()
        while n in aliases and n not in seen:
            seen.add(n)
            n = aliases[n]
        return n

    target = resolve(_normalize_mention(name))

    rows = db.session.query(
        EntryPerson.entry_id, EntryPerson.mention, EntryPerson.tone
    ).all()
    matching: dict[int, list[str]] = {}
    for entry_id, mention, tone in rows:
        if resolve(_normalize_mention(mention)) == target:
            matching.setdefault(entry_id, []).append(tone)

    if not matching:
        return f'Записей с упоминанием «{target}» не найдено.'

    entries = (MoodEntry.query
               .filter(MoodEntry.id.in_(matching.keys()),
                       MoodEntry.deleted == False)
               .order_by(MoodEntry.date.desc())
               .limit(limit)
               .all())

    # Tone breakdown — gives the model a quick global summary before
    # diving into individual entries.
    tone_totals: dict[str, int] = {}
    for tones in matching.values():
        for t in tones:
            tone_totals[t] = tone_totals.get(t, 0) + 1
    tone_summary = ', '.join(
        f'{t}: {c}' for t, c in sorted(tone_totals.items(), key=lambda x: -x[1])
    ) or 'тон не определён'

    lines = [
        f'Все упоминания «{target}» в дневнике (всего {len(matching)} записей; {tone_summary}):'
    ]
    # Use sentence-aware excerpts — show the actual sentence(s) around
    # the mention rather than the entry's first N characters.
    for e in entries:
        tones = matching.get(e.id, [])
        tone_txt = ', '.join(tones) if tones else 'unknown'
        excerpt = _excerpt_around_term(e.note or '', target, window_chars=240)
        lines.append(
            f'[{ru_date(e.date)}] {e.rating}/10 [тон: {tone_txt}]. {excerpt}'
        )
    return '\n'.join(lines)


def tool_mood_trend(window_days: int = 30) -> str:
    """Recent mood trajectory: average, range, and direction over the
    last `window_days` days. Lets the LLM ground answers like "у меня
    последнее время плохо" on actual numbers.
    """
    from datetime import date as _date, timedelta
    try:
        window_days = int(window_days)
    except (TypeError, ValueError):
        window_days = 30
    window_days = max(7, min(180, window_days))

    cutoff = _date.today() - timedelta(days=window_days - 1)
    entries = (MoodEntry.query
               .filter(MoodEntry.date >= cutoff, MoodEntry.deleted == False)
               .order_by(MoodEntry.date)
               .all())
    if not entries:
        return f'За последние {window_days} дней записей нет.'

    ratings = [e.rating for e in entries]
    avg = sum(ratings) / len(ratings)
    lo, hi = min(ratings), max(ratings)

    # Linear regression slope: positive = uptrend, negative = downtrend.
    n = len(ratings)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = avg
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ratings))
    den = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope = num / den  # rating change per day

    direction = 'стабильно'
    if slope > 0.04:
        direction = 'растёт'
    elif slope < -0.04:
        direction = 'снижается'

    half = n // 2 or 1
    first_half_avg = sum(ratings[:half]) / half
    second_half_avg = sum(ratings[-half:]) / half

    return (
        f'Тренд настроения за последние {window_days} дней '
        f'({len(entries)} записей):\n'
        f'- Среднее: {avg:.2f}/10 (диапазон {lo}–{hi})\n'
        f'- Первая половина окна: {first_half_avg:.2f}/10\n'
        f'- Вторая половина окна: {second_half_avg:.2f}/10\n'
        f'- Направление: {direction} (наклон {slope:+.3f}/день)'
    )


def _parse_period_spec(spec: str):
    """A period as the router writes it → (label, start, end), or None.

    Accepts "YYYY", "YYYY-MM" and an exact range "YYYY-MM-DD..YYYY-MM-DD"
    (a week, a season, "с 5 по 12 марта"). `end` is inclusive.
    """
    import calendar
    from datetime import date as _date
    s = (spec or '').strip()
    try:
        if '..' in s:
            a, b = (p.strip() for p in s.split('..', 1))
            start, end = _date.fromisoformat(a), _date.fromisoformat(b)
            if end < start:
                start, end = end, start
            return s, start, end
        parts = s.split('-')
        year = int(parts[0])
        if len(parts) > 1 and parts[1]:
            month = int(parts[1])
            last = calendar.monthrange(year, month)[1]
            return s, _date(year, month, 1), _date(year, month, last)
        return s, _date(year, 1, 1), _date(year, 12, 31)
    except (TypeError, ValueError, IndexError):
        return None


def tool_compare_periods(period_a: str, period_b: str) -> str:
    """Compare two periods: "YYYY", "YYYY-MM" or "YYYY-MM-DD..YYYY-MM-DD".

    Returns headline stats (mean, min, max, count) for each plus a delta.
    Useful when user asks "is my mood better this month than last".
    """
    a_spec = _parse_period_spec(period_a)
    b_spec = _parse_period_spec(period_b)
    if a_spec is None or b_spec is None:
        return ''
    a_label, b_label = a_spec[0], b_spec[0]

    def _stats(start, end):
        rows = (MoodEntry.query
                .filter(MoodEntry.date >= start, MoodEntry.date <= end,
                        MoodEntry.deleted == False)
                .all())
        if not rows:
            return None
        ratings = [r.rating for r in rows]
        return {
            'avg': sum(ratings) / len(ratings),
            'min': min(ratings),
            'max': max(ratings),
            'count': len(ratings),
        }

    a = _stats(a_spec[1], a_spec[2])
    b = _stats(b_spec[1], b_spec[2])

    if a is None and b is None:
        return f'За периоды {a_label} и {b_label} записей не найдено.'
    if a is None:
        return f'За {a_label} записей нет; за {b_label} среднее {b["avg"]:.2f}/10 ({b["count"]} записей).'
    if b is None:
        return f'За {b_label} записей нет; за {a_label} среднее {a["avg"]:.2f}/10 ({a["count"]} записей).'

    delta = b['avg'] - a['avg']
    direction = 'выше' if delta > 0.05 else ('ниже' if delta < -0.05 else 'примерно так же')
    return (
        f'Сравнение периодов:\n'
        f'- {a_label}: среднее {a["avg"]:.2f}/10 (диапазон {a["min"]}–{a["max"]}, {a["count"]} записей)\n'
        f'- {b_label}: среднее {b["avg"]:.2f}/10 (диапазон {b["min"]}–{b["max"]}, {b["count"]} записей)\n'
        f'- Разница: {b_label} {direction} на {abs(delta):.2f} балла'
    )


def tool_period_entries(year: int | None = None, month: int | None = None,
                        limit: int = 40, start: str | None = None,
                        end: str | None = None) -> str:
    """Entries from a year, a month, or an exact range `start`..`end`.

    A long period holds more entries than fit, and the newest forty of a
    year are only its last weeks. So when there are more than `limit`, the
    entries are picked evenly across the period, and a period longer than
    a month and a half opens with its per-month averages.
    """
    try:
        limit = max(1, min(60, int(limit)))
    except (TypeError, ValueError):
        limit = 40
    if start:
        spec = _parse_period_spec(f'{start}..{end or start}')
    else:
        try:
            year = int(year)
        except (TypeError, ValueError):
            return ''
        m = None
        if month is not None:
            try:
                m = int(month)
            except (TypeError, ValueError):
                m = None
        spec = _parse_period_spec(f'{year}-{m:02d}' if m else f'{year}')
    if spec is None:
        return ''
    label, d0, d1 = spec

    entries = (MoodEntry.query
               .filter(MoodEntry.date >= d0, MoodEntry.date <= d1,
                       MoodEntry.deleted == False)
               .order_by(MoodEntry.date)
               .all())
    if not entries:
        return f'Записей за {label} не найдено.'

    avg = sum(e.rating for e in entries) / len(entries)
    lines = [f'Записи за {label} (от свежих к старым):',
             f'Всего {len(entries)} записей, среднее настроение {avg:.2f}/10.']
    if (d1 - d0).days > 45:
        by_month: dict[str, list[int]] = {}
        for e in entries:
            by_month.setdefault(e.date.strftime('%Y-%m'), []).append(e.rating)
        lines.append('По месяцам: ' + ', '.join(
            f'{k} — {sum(v) / len(v):.1f} ({len(v)})' for k, v in by_month.items()))
    shown = entries
    if len(entries) > limit:
        step = len(entries) / limit
        shown = [entries[int(i * step)] for i in range(limit)]
        lines.append(f'Показаны {limit} записей, равномерно по периоду.')
    for e in reversed(shown):
        lines.append(_format_entry_line(e))
    return '\n'.join(lines)


def tool_activity_impact(limit: int = 12, min_count: int = 2) -> str:
    """How each activity correlates with mood.

    Aggregates EntryActivity (what the user did) against each day's rating:
    average mood on days featuring an activity vs the user's overall average.
    Grounds answers to "что мне помогает?" / "от чего мне лучше или хуже?".
    Activity labels come from the AI's background parsing of notes.
    """
    from app.models import EntryActivity

    rows = (db.session.query(EntryActivity.activity, MoodEntry.rating)
            .join(MoodEntry, EntryActivity.entry_id == MoodEntry.id)
            .filter(MoodEntry.deleted == False)
            .all())
    if not rows:
        return ('В дневнике пока не размечены активности — нужен фоновый разбор '
                'записей AI-психологом (он идёт автоматически после новых записей).')

    base_entries = MoodEntry.query.filter_by(deleted=False).all()
    overall = (sum(e.rating for e in base_entries) / len(base_entries)
               if base_entries else 0.0)

    agg: dict[str, list[int]] = {}
    for activity, rating in rows:
        agg.setdefault(activity, []).append(rating)

    stats = []
    for activity, ratings in agg.items():
        if len(ratings) < min_count:
            continue
        avg = sum(ratings) / len(ratings)
        stats.append((activity, avg, len(ratings), avg - overall))
    if not stats:
        return 'Активностей с достаточным числом упоминаний пока нет.'

    lifts = sorted([s for s in stats if s[3] > 0.1], key=lambda x: -x[3])[:limit]
    drags = sorted([s for s in stats if s[3] < -0.1], key=lambda x: x[3])[:limit]

    lines = [f'Влияние активностей на настроение (общее среднее {overall:.2f}/10):']
    if lifts:
        lines.append('Поднимают настроение:')
        for a, avg, c, d in lifts:
            lines.append(f'- {a}: {avg:.2f}/10 ({d:+.2f} к среднему), упоминаний {c}')
    if drags:
        lines.append('Связаны с понижением:')
        for a, avg, c, d in drags:
            lines.append(f'- {a}: {avg:.2f}/10 ({d:+.2f} к среднему), упоминаний {c}')
    if not lifts and not drags:
        lines.append('Заметной связи активностей с настроением не видно.')
    return '\n'.join(lines)


def tool_people_overview(limit: int = 15) -> str:
    """All people in the diary at a glance (alias-resolved), with tone.

    Complements tool_person_history (one person) — answers "кто в моей
    жизни связан с хорошим/плохим настроением?". Tone is per-mention
    (how the person is written about), not the day's overall rating.
    """
    from app.models import EntryPerson, PersonAlias

    aliases = {a.alias: a.canonical for a in PersonAlias.query.all()}

    def resolve(n: str) -> str:
        seen: set = set()
        while n in aliases and n not in seen:
            seen.add(n)
            n = aliases[n]
        return n

    rows = (db.session.query(EntryPerson.mention, EntryPerson.tone)
            .join(MoodEntry, EntryPerson.entry_id == MoodEntry.id)
            .filter(MoodEntry.deleted == False)
            .all())
    if not rows:
        return ('В дневнике пока не размечены люди — нужен фоновый разбор '
                'записей AI-психологом (он идёт автоматически после новых записей).')

    agg: dict[str, dict] = {}
    for mention, tone in rows:
        key = resolve(_normalize_mention(mention))
        d = agg.setdefault(key, {'pos': 0, 'neg': 0, 'neu': 0, 'total': 0})
        d['total'] += 1
        if tone == 'positive':
            d['pos'] += 1
        elif tone == 'negative':
            d['neg'] += 1
        else:
            d['neu'] += 1

    people = sorted(agg.items(), key=lambda kv: -kv[1]['total'])[:limit]
    lines = [
        f'Люди в дневнике (всего {len(agg)}; тон ∈ [−1; +1] — про упоминания, '
        f'не про настроение дня):'
    ]
    for name, d in people:
        score = (d['pos'] - d['neg']) / d['total']
        lines.append(
            f'- {name}: упоминаний {d["total"]} '
            f'(+{d["pos"]} / −{d["neg"]} / нейтр. {d["neu"]}), тон {score:+.2f}'
        )
    return '\n'.join(lines)


def tool_best_worst_days(top_n: int = 5) -> str:
    """The highest- and lowest-rated days with short excerpts.

    Answers "когда мне было лучше/хуже всего?". Distinct from mood_trend
    (trajectory) — this surfaces the actual peak and trough days.
    """
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        top_n = 5
    top_n = max(1, min(10, top_n))

    entries = MoodEntry.query.filter_by(deleted=False).all()
    if not entries:
        return 'В дневнике пока нет записей.'
    top_n = min(top_n, len(entries))

    best = sorted(entries, key=lambda e: (-e.rating, e.date.toordinal()))[:top_n]
    worst = sorted(entries, key=lambda e: (e.rating, -e.date.toordinal()))[:top_n]

    lines = ['Лучшие дни (по оценке):']
    for e in best:
        lines.append(_format_entry_line(e, max_note=160))
    lines.append('Худшие дни (по оценке):')
    for e in worst:
        lines.append(_format_entry_line(e, max_note=160))
    return '\n'.join(lines)


def tool_diary_stats() -> str:
    """Meta-statistics about the diary: totals, span, streaks, this month.

    Grounds answers like "сколько я веду дневник?" and lets the assistant
    celebrate milestones ("ты ведёшь дневник уже N дней подряд").
    """
    from datetime import date as _date, timedelta

    entries = (MoodEntry.query
               .filter_by(deleted=False)
               .order_by(MoodEntry.date)
               .all())
    if not entries:
        return 'В дневнике пока нет записей.'

    n = len(entries)
    ratings = [e.rating for e in entries]
    avg = sum(ratings) / n
    first, last = entries[0].date, entries[-1].date
    span_days = (last - first).days + 1
    dates = {e.date for e in entries}

    today = _date.today()
    cur = 0
    d = today if today in dates else today - timedelta(days=1)
    while d in dates:
        cur += 1
        d -= timedelta(days=1)

    longest = 0
    run = 0
    prev = None
    for e in entries:
        if prev is not None and (e.date - prev).days == 1:
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        prev = e.date

    this_month = [e for e in entries
                  if e.date.year == today.year and e.date.month == today.month]

    lines = [
        'Статистика дневника:',
        f'- Всего записей: {n}',
        f'- Период ведения: {first.isoformat()} — {last.isoformat()} ({span_days} дн.)',
        f'- Среднее настроение за всё время: {avg:.2f}/10',
        f'- Текущая серия записей подряд: {cur} дн.',
        f'- Самая длинная серия: {longest} дн.',
    ]
    if this_month:
        tm_avg = sum(e.rating for e in this_month) / len(this_month)
        lines.append(f'- В этом месяце: {len(this_month)} записей, среднее {tm_avg:.2f}/10')
    return '\n'.join(lines)


def tool_on_this_day() -> str:
    """Entries from the same calendar day in previous years.

    A reflection prompt — answers "что было год назад?" / "что у меня было
    в этот день раньше?".
    """
    from datetime import date as _date

    today = _date.today()
    entries = (MoodEntry.query
               .filter(db.extract('month', MoodEntry.date) == today.month,
                       db.extract('day', MoodEntry.date) == today.day,
                       MoodEntry.date < today,
                       MoodEntry.deleted == False)
               .order_by(MoodEntry.date.desc())
               .all())
    if not entries:
        return (f'Записей за этот день ({today.day:02d}.{today.month:02d}) '
                f'в прошлые годы нет.')

    lines = [f'Записи за {today.day:02d}.{today.month:02d} в прошлые годы:']
    for e in entries:
        years_ago = today.year - e.date.year
        suffix = f'{years_ago} г. назад' if years_ago > 0 else 'в этом году'
        lines.append(_format_entry_line(e, extra=suffix, max_note=200))
    return '\n'.join(lines)


def tool_weather_impact() -> str:
    """How the weather correlates with mood — temperature and condition.

    Reads the daily_signals collected by the weather integration; grounds
    answers like "влияет ли на меня погода?" / "в дождь мне хуже?".
    """
    from app import signals

    temp = signals.correlate_signal_with_mood('weather', 'temp_c')
    cond = signals.correlate_signal_with_mood('weather', 'condition')

    if temp.get('kind') == 'empty' and cond.get('kind') == 'empty':
        return ('Погодных данных пока нет. Включи погоду в настройках аккаунта — '
                'после новых записей появится связь настроения с погодой.')

    lines = ['Связь настроения с погодой:']
    if temp.get('kind') == 'numeric' and temp.get('low_avg') is not None:
        r = temp.get('pearson')
        r_txt = f'{r:+.2f}' if isinstance(r, (int, float)) else 'н/д'
        lines.append(
            f'- Температура: в тёплые дни среднее {temp["high_avg"]}/10, '
            f'в прохладные {temp["low_avg"]}/10 '
            f'(корреляция {r_txt}, по {temp["count"]} дням).'
        )
    if cond.get('kind') == 'categorical' and cond.get('groups'):
        parts = [
            f'{signals.condition_label(g["label"])}: {g["avg"]}/10 (×{g["count"]})'
            for g in cond['groups']
        ]
        lines.append('- По типу погоды: ' + '; '.join(parts))
    return '\n'.join(lines)


# ── analysis tools (ROADMAP §17 phase 2) ──────────────────────
#
# Thin wrappers: read the days from the database, hand them to the pure
# functions in analysis.py. Arguments arrive from the scenario plans as
# JSON-ish values, so each is checked here.

_WEATHER_KEYS = {'Clear', 'Clouds', 'Fog', 'Rain', 'Snow', 'Thunderstorm', 'Other'}


def _range(start, end):
    """(start, end) dates from ISO strings; either may be missing."""
    from datetime import date as _date
    def one(v):
        try:
            return _date.fromisoformat(str(v)) if v else None
        except ValueError:
            return None
    return one(start), one(end)


def _int_or_none(v, lo=None, hi=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        return None
    return n


def tool_what_changed(period_a: str = '', period_b: str = '') -> str:
    """Period b against period a ("YYYY", "YYYY-MM" or "A..B"); by default
    the last 30 days against the 30 before them."""
    from datetime import date as _date, timedelta
    from .analysis import what_changed
    from .daybook import load_days
    today = _date.today()
    b = _parse_period_spec(period_b) if period_b else None
    b = (b[1], b[2]) if b else (today - timedelta(days=29), today)
    a = _parse_period_spec(period_a) if period_a else None
    if a:
        a = (a[1], a[2])
    else:
        length = (b[1] - b[0]).days + 1
        a = (b[0] - timedelta(days=length), b[0] - timedelta(days=1))
    return what_changed(load_days(), a, b)


def tool_contrast_days(start: str = '', end: str = '') -> str:
    from .analysis import contrast_days
    from .daybook import load_days
    return contrast_days(load_days(*_range(start, end)))


def tool_person_deep(name: str) -> str:
    from datetime import date as _date
    from .analysis import person_deep
    from .daybook import load_days
    name = (name or '').strip()
    if not name:
        return ''
    return person_deep(load_days(), name, _date.today())


def tool_entries_query(start: str = '', end: str = '', min_rating=None, max_rating=None,
                       person: str = '', activity: str = '', weather: str = '',
                       weekday=None, word: str = '', limit: int = 25) -> str:
    from .analysis import entries_query
    from .daybook import load_days
    s, e = _range(start, end)
    return entries_query(
        load_days(), start=s, end=e,
        min_rating=_int_or_none(min_rating, 1, 10), max_rating=_int_or_none(max_rating, 1, 10),
        person=(person or '').strip() or None, activity=(activity or '').strip() or None,
        weather=weather if weather in _WEATHER_KEYS else None,
        weekday=_int_or_none(weekday, 0, 6), word=(word or '').strip() or None,
        limit=_int_or_none(limit, 1, 60) or 25,
    )


def tool_rhythms() -> str:
    from .analysis import rhythms
    from .daybook import load_days
    return rhythms(load_days())


def tool_themes(start: str = '', end: str = '') -> str:
    from datetime import date as _date
    from app.models import MindCluster
    from .analysis import themes
    from .daybook import load_days
    s, e = _range(start, end)
    clusters = [(c.label, c.entry_count or 0) for c in
                MindCluster.query.order_by(MindCluster.entry_count.desc()).limit(8).all()]
    return themes(load_days(), _date.today(), start=s, end=e, clusters=clusters)


# Name → function for the tools above; routes._execute_tool passes on only
# the arguments a function accepts.
ANALYSIS_TOOLS = {
    'what_changed': tool_what_changed,
    'contrast_days': tool_contrast_days,
    'person_deep': tool_person_deep,
    'entries_query': tool_entries_query,
    'rhythms': tool_rhythms,
    'themes': tool_themes,
}
