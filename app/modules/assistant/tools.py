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
from .memory import search_relevant_entries, _normalize_mention

log = logging.getLogger(__name__)


def _format_entry_line(entry: MoodEntry, extra: str = '', max_note: int = 280) -> str:
    """One-line representation of an entry suitable for LLM context."""
    from app.note_text import plain_text
    note = plain_text(entry.note).strip()
    if len(note) > max_note:
        note = note[:max_note].rstrip() + '...'
    suffix = f' [{extra}]' if extra else ''
    return f'[{entry.date.isoformat()}] {entry.rating}/10{suffix}. {note}'


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
            f'[{e.date.isoformat()}] {e.rating}/10 [тон: {tone_txt}]. {excerpt}'
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


def tool_compare_periods(period_a: str, period_b: str) -> str:
    """Compare two periods. Each `period` is either "YYYY" or "YYYY-MM".

    Returns headline stats (mean, min, max, count) for each plus a delta.
    Useful when user asks "is my mood better this month than last".
    """
    def _parse(s: str):
        s = (s or '').strip()
        parts = s.split('-')
        try:
            year = int(parts[0])
        except (TypeError, ValueError, IndexError):
            return None, None, None
        month = None
        if len(parts) > 1 and parts[1]:
            try:
                month = int(parts[1])
            except ValueError:
                pass
        return s, year, month

    a_label, a_year, a_month = _parse(period_a)
    b_label, b_year, b_month = _parse(period_b)
    if a_year is None or b_year is None:
        return ''

    def _stats(year: int, month: int | None):
        q = MoodEntry.query.filter(db.extract('year', MoodEntry.date) == year,
                                   MoodEntry.deleted == False)
        if month:
            q = q.filter(db.extract('month', MoodEntry.date) == month)
        rows = q.all()
        if not rows:
            return None
        ratings = [r.rating for r in rows]
        return {
            'avg': sum(ratings) / len(ratings),
            'min': min(ratings),
            'max': max(ratings),
            'count': len(ratings),
        }

    a = _stats(a_year, a_month)
    b = _stats(b_year, b_month)

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


def tool_period_entries(year: int, month: int | None = None,
                        limit: int = 40) -> str:
    """All entries from a specific year (and optionally month)."""
    try:
        year = int(year)
    except (TypeError, ValueError):
        return ''
    if month is not None:
        try:
            month = int(month)
        except (TypeError, ValueError):
            month = None

    q = MoodEntry.query.filter(db.extract('year', MoodEntry.date) == year,
                               MoodEntry.deleted == False)
    if month:
        q = q.filter(db.extract('month', MoodEntry.date) == month)
    entries = q.order_by(MoodEntry.date.desc()).limit(limit).all()

    if not entries:
        period = f'{year}-{month:02d}' if month else f'{year}'
        return f'Записей за {period} не найдено.'

    period = f'{year}-{month:02d}' if month else f'{year}'
    lines = [f'Записи за {period} (отсортированы от свежих к старым):']
    avg = sum(e.rating for e in entries) / len(entries)
    lines.append(f'Всего {len(entries)} записей, среднее настроение {avg:.2f}/10.')
    for e in entries:
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
