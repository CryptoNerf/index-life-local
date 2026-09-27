# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Every diary day with what the background parsing found in it.

The analysis tools (what changed, good days against bad, one person over
time, rhythms, themes) all ask questions of the same table: for each day,
its rating and text, the activities, the people and how they were written
about, the themes, the weather. `load_days` builds that table with a few
queries; the tools in analysis.py are pure functions over it, so they are
tested on made-up diaries without a database.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Day:
    date: date
    rating: int
    note: str = ''
    summary: str = ''
    themes: tuple[str, ...] = ()
    activities: tuple[str, ...] = ()
    # canonical name → tones of its mentions that day
    people: dict[str, tuple[str, ...]] = field(default_factory=dict)
    weather: str | None = None   # 'Rain', 'Clear' … (signals._CONDITION_LABELS)
    temp: float | None = None


def load_days(start: date | None = None, end: date | None = None) -> list[Day]:
    """Non-deleted days in [start, end], oldest first."""
    from app import db
    from app.models import (DailySignal, EntryActivity, EntryPerson, EntrySummary,
                            MoodEntry, PersonAlias)
    from app.note_text import plain_text
    from .memory import _normalize_mention

    q = MoodEntry.query.filter(MoodEntry.deleted == False)  # noqa: E712
    if start:
        q = q.filter(MoodEntry.date >= start)
    if end:
        q = q.filter(MoodEntry.date <= end)
    entries = q.order_by(MoodEntry.date).all()
    if not entries:
        return []
    ids = [e.id for e in entries]
    by_id = {e.id: Day(date=e.date, rating=e.rating, note=plain_text(e.note or '').strip())
             for e in entries}

    def chunks(seq, n=500):
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    for part in chunks(ids):
        for s in EntrySummary.query.filter(EntrySummary.entry_id.in_(part)).all():
            day = by_id[s.entry_id]
            day.summary = (s.summary or '').strip()
            try:
                raw = json.loads(s.themes or '[]')
            except ValueError:
                raw = []
            day.themes = tuple(dict.fromkeys(
                str(t).strip().lower() for t in raw if str(t).strip()))

        acts: dict[int, list[str]] = {}
        for entry_id, activity in (db.session.query(EntryActivity.entry_id, EntryActivity.activity)
                                   .filter(EntryActivity.entry_id.in_(part)).all()):
            acts.setdefault(entry_id, []).append(activity.strip().lower())
        for entry_id, items in acts.items():
            by_id[entry_id].activities = tuple(dict.fromkeys(items))

    aliases = {a.alias: a.canonical for a in PersonAlias.query.all()}

    def resolve(n: str) -> str:
        seen: set = set()
        while n in aliases and n not in seen:
            seen.add(n)
            n = aliases[n]
        return n

    for part in chunks(ids):
        tones: dict[int, dict[str, list[str]]] = {}
        for entry_id, mention, tone in (db.session.query(EntryPerson.entry_id, EntryPerson.mention,
                                                         EntryPerson.tone)
                                        .filter(EntryPerson.entry_id.in_(part)).all()):
            name = resolve(_normalize_mention(mention))
            if name:
                tones.setdefault(entry_id, {}).setdefault(name, []).append(tone or 'neutral')
        for entry_id, people in tones.items():
            by_id[entry_id].people = {k: tuple(v) for k, v in people.items()}

    days = [by_id[i] for i in ids]
    by_date = {d.date: d for d in days}
    signals = (DailySignal.query
               .filter(DailySignal.source == 'weather',
                       DailySignal.metric.in_(('condition', 'temp_c')),
                       DailySignal.date >= days[0].date,
                       DailySignal.date <= days[-1].date)
               .all())
    for s in signals:
        day = by_date.get(s.date)
        if day is None:
            continue
        if s.metric == 'condition':
            day.weather = s.value_text or None
        elif s.metric == 'temp_c':
            day.temp = s.value_num
    return days
