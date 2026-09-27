"""The analysis tools find what was planted in a made-up diary
(tests/assistant_diary.py), and load_days builds that diary's shape from
the real tables."""
import re
from datetime import date, timedelta

import pytest

from app.modules.assistant import analysis
from app.modules.assistant.daybook import Day
from app.modules.assistant.llm_text import ru_date

_MONTHS = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
           'августа', 'сентября', 'октября', 'ноября', 'декабря']


def _row_date(line):
    """The date of an entry line "[2 июня 2025, пн] 1/10. …", or None."""
    m = re.match(r'\[(\d{1,2}) (\w+) (\d{4}), \w\w\]', line)
    return date(int(m[3]), _MONTHS.index(m[2]), int(m[1])) if m else None

from assistant_diary import MASHA_FIRST, RUNNING_STOPS, TODAY, make_diary


@pytest.fixture(scope='module')
def diary():
    return make_diary()


def _line(text, prefix):
    for ln in text.splitlines():
        if ln.lstrip('- ').startswith(prefix):
            return ln
    raise AssertionError(f'no line starting with {prefix!r} in:\n{text}')


# ── what changed ──────────────────────────────────────────────

def test_what_changed_finds_the_running_that_stopped(diary):
    now = (TODAY - timedelta(days=29), TODAY)
    before = (now[0] - timedelta(days=30), now[0] - timedelta(days=1))
    out = analysis.what_changed(diary, before, now)
    mood = _line(out, 'Настроение')
    a, b = map(float, re.findall(r'(\d+\.\d) → (\d+\.\d)', mood)[0])
    assert b < a
    faded = _line(out, 'Стало меньше или пропало')
    # ...and says running usually lifts the mood.
    assert re.search(r'занятие: бег \(\d+% дней → 0%, обычно \+\d\.\d к настроению\)', faded)
    assert 'Самые тяжёлые дни (теперь):' in out
    assert '—' not in out


def test_what_changed_sees_new_things_and_a_turned_tone(diary):
    out = analysis.what_changed(diary, (date(2026, 3, 1), date(2026, 5, 31)),
                                (date(2026, 6, 1), date(2026, 8, 31)))
    assert 'Сергей (+0.0 → -1.0)' in _line(out, 'Тон упоминаний')
    out = analysis.what_changed(diary, (TODAY - timedelta(days=119), TODAY - timedelta(days=60)),
                                (TODAY - timedelta(days=59), TODAY))
    assert 'тема: переезд (0% дней →' in _line(out, 'Появилось')


def test_what_changed_on_empty_periods(diary):
    assert analysis.what_changed(diary, (date(2020, 1, 1), date(2020, 1, 31)),
                                 (date(2026, 9, 1), date(2026, 9, 27))).startswith('Записей с 1 по 31 января 2020 нет')
    assert analysis.what_changed(diary, (date(2026, 9, 1), date(2026, 9, 2)),
                                 (date(2030, 1, 1), date(2030, 1, 2))) == 'Записей с 1 по 2 января 2030 нет.'


# ── good days against bad ─────────────────────────────────────

def test_contrast_days_separates_the_planted_causes(diary):
    out = analysis.contrast_days(diary)
    good, bad = _line(out, 'Чаще в хорошие дни'), _line(out, 'Чаще в плохие дни')
    for f in ('занятие: бег', 'человек: Маша'):
        assert f in good and f not in bad
    for f in ('погода: дождь', 'тема: дедлайн', 'день недели: понедельник'):
        assert f in bad and f not in good
    assert out.count('/10.') == 6  # three examples each


def test_contrast_days_on_a_flat_or_tiny_diary():
    flat = [Day(date(2026, 1, i), 6) for i in range(1, 20)]
    assert 'одинаковые' in analysis.contrast_days(flat)
    assert 'мало' in analysis.contrast_days(flat[:5])


# ── one person ────────────────────────────────────────────────

def test_person_deep_from_a_declined_name(diary):
    out = analysis.person_deep(diary, 'Машу', TODAY)
    assert out.startswith('«Маша»: упоминается в ')
    assert f'Первое упоминание {ru_date(MASHA_FIRST)}' in out
    tone = _line(out, 'Тон упоминаний')
    assert 'негативно 0' in tone and 'нейтрально 0' in tone
    with_p, without = map(float, re.findall(r'(\d+\.\d)', _line(out, 'Настроение в дни'))[:2])
    assert with_p > without
    # Quotes show the name as it was written, in the case it was written in.
    assert 'гуляли с Машей' in out


def test_person_deep_shows_the_tone_turning(diary):
    out = analysis.person_deep(diary, 'сергей', TODAY)
    over_time = _line(out, 'По времени')
    tones = [float(t) for t in re.findall(r'тон ([+-]\d\.\d)', over_time)]
    assert tones[0] == 0.0 and tones[-1] == -1.0
    assert 'придирался' in out and 'по делу' in out


def test_person_deep_unknown_and_unparsed():
    days = [Day(date(2026, 1, 1), 5, people={'Маша': ('positive',)})]
    assert 'нет' in analysis.person_deep(days, 'Аркадий', TODAY)
    assert 'не размечены' in analysis.person_deep([Day(date(2026, 1, 1), 5)], 'Маша', TODAY)


def test_match_person_knows_roles_and_forms():
    known = ['Мама', 'Маша', 'Лёша']
    assert analysis.match_person('маму', known) == 'Мама'
    assert analysis.match_person('Машей', known) == 'Маша'
    assert analysis.match_person('Леша', known) == 'Лёша'
    assert analysis.match_person('Петя', known) is None


# ── filters ───────────────────────────────────────────────────

def test_entries_query_combines_filters(diary):
    out = analysis.entries_query(diary, start=date(2026, 3, 1), end=date(2026, 3, 31),
                                 weather='Rain', max_rating=5)
    head = out.splitlines()[0]
    assert head.startswith('Найдено ') and 'период с 1 по 31 марта 2026' in head
    assert 'погода: дождь' in head and 'оценка до 5' in head
    rows = [ln for ln in out.splitlines() if _row_date(ln)]
    assert rows and all(_row_date(ln).month == 3 for ln in rows)
    assert all(int(re.match(r'\[[^\]]+\] (\d+)/10', ln)[1]) <= 5 for ln in rows)
    # Newest first.
    dates = [_row_date(ln) for ln in rows]
    assert dates == sorted(dates, reverse=True)


def test_entries_query_by_weekday_person_word_and_limit(diary):
    out = analysis.entries_query(diary, weekday=0, limit=10)
    rows = [ln for ln in out.splitlines() if _row_date(ln)]
    assert len(rows) == 10 and 'Показаны 10' in out
    assert all(_row_date(ln).weekday() == 0 and ', пн]' in ln for ln in rows)

    out = analysis.entries_query(diary, person='Сергея', start=date(2026, 6, 1), end=date(2026, 9, 27))
    assert 'человек «Сергей»' in out and 'придирался' in out and 'по делу' not in out

    out = analysis.entries_query(diary, word='дождём', start=date(2026, 9, 1), end=TODAY)
    assert 'слово «дождём»' in out and 'Дождь весь день' in out
    assert analysis.entries_query(diary, word='вулкан').startswith('Записей не найдено')


# ── rhythms and themes ────────────────────────────────────────

def test_rhythms_find_mondays_and_the_februaries(diary):
    out = analysis.rhythms(diary)
    assert 'худший: понедельник' in _line(out, 'Лучший день недели')
    assert re.search(r'фев \d\.\d', _line(out, 'Месяцы года'))
    assert 'фев (2025, 2026)' in _line(out, 'Спады в один и тот же месяц разных лет')
    assert _line(out, 'По годам').count(' 20') == 3  # 2024, 2025, 2026


def test_rhythms_need_two_weeks():
    assert 'мало' in analysis.rhythms([Day(date(2026, 1, i), 5) for i in range(1, 8)])


def test_themes_rank_mark_hard_ones_and_see_what_grew(diary):
    out = analysis.themes(diary, TODAY, clusters=[('работа и усталость', 40)])
    assert _line(out, 'Чаще всего').startswith('- Чаще всего: работа ')
    assert 'дедлайн' in _line(out, 'Темы тяжёлых дней')
    assert 'переезд (0% →' in _line(out, 'Чаще обычного за последние 60 дней')
    assert 'работа и усталость (40)' in out
    scoped = analysis.themes(diary, TODAY, start=date(2026, 8, 1), end=TODAY)
    assert scoped.startswith('Темы записей с 1 августа по 27 сентября 2026')
    assert 'не выделены' in analysis.themes([Day(date(2026, 1, 1), 5)], TODAY)


def test_outputs_stay_compact(diary):
    """What the chat can afford: the scenario path shares ~8000 chars
    between at most three tools."""
    now = (TODAY - timedelta(days=29), TODAY)
    before = (now[0] - timedelta(days=30), now[0] - timedelta(days=1))
    for out in (analysis.what_changed(diary, before, now), analysis.contrast_days(diary),
                analysis.person_deep(diary, 'Маша', TODAY), analysis.rhythms(diary),
                analysis.themes(diary, TODAY), analysis.entries_query(diary, weekday=4)):
        assert len(out) < 3200, out[:200]


# ── from the database ─────────────────────────────────────────

def test_load_days_joins_every_layer(app):
    import json
    from app import db
    from app.models import (DailySignal, EntryActivity, EntryPerson, EntrySummary,
                            MoodEntry, PersonAlias)
    from app.modules.assistant.daybook import load_days

    e1 = MoodEntry(date=date(2026, 9, 1), rating=7, note='Гуляли с <span style="color: red">Машей</span>', deleted=False)
    e2 = MoodEntry(date=date(2026, 9, 2), rating=3, note='Марь опять', deleted=False)
    gone = MoodEntry(date=date(2026, 9, 3), rating=1, note='удалено', deleted=True)
    db.session.add_all([e1, e2, gone])
    db.session.commit()
    db.session.add_all([
        EntrySummary(entry_id=e1.id, summary='Прогулка', themes=json.dumps(['Отношения', 'отдых'])),
        EntrySummary(entry_id=e2.id, summary='Ссора', themes='не json'),
        EntryActivity(entry_id=e1.id, activity='Прогулка'),
        EntryPerson(entry_id=e1.id, mention='Машей', tone='positive'),
        EntryPerson(entry_id=e2.id, mention='Марь', tone='negative'),
        PersonAlias(alias='Марь', canonical='Мари'),
        DailySignal(date=date(2026, 9, 1), source='weather', metric='condition', value_text='Rain'),
        DailySignal(date=date(2026, 9, 1), source='weather', metric='temp_c', value_num=12.5),
    ])
    db.session.commit()

    days = load_days()
    assert [d.date for d in days] == [date(2026, 9, 1), date(2026, 9, 2)]
    d1, d2 = days
    assert d1.note == 'Гуляли с Машей'
    assert d1.summary == 'Прогулка' and d1.themes == ('отношения', 'отдых')
    assert d1.activities == ('прогулка',)
    assert d1.people == {'Маша': ('positive',)}
    assert d1.weather == 'Rain' and d1.temp == 12.5
    assert d2.themes == () and d2.people == {'Мари': ('negative',)} and d2.weather is None
    assert [d.date for d in load_days(start=date(2026, 9, 2))] == [date(2026, 9, 2)]


def test_every_analysis_tool_runs_through_the_chat_dispatch(app):
    """From the plan's JSON-ish arguments to text, against the real tables:
    stray or malformed arguments are dropped, not raised."""
    from app import db
    from app.models import EntryPerson, EntrySummary, MoodEntry
    from app.modules.assistant.routes import _execute_tool
    from app.modules.assistant.tools import ANALYSIS_TOOLS

    today = date.today()
    for i, day in enumerate(make_diary()[-60:]):
        e = MoodEntry(date=today - timedelta(days=59 - i), rating=day.rating,
                      note=day.note, deleted=False)
        db.session.add(e)
        db.session.flush()
        db.session.add(EntrySummary(entry_id=e.id, summary=day.summary,
                                    themes='["' + '", "'.join(day.themes) + '"]' if day.themes else '[]'))
        for name, tones in day.people.items():
            db.session.add(EntryPerson(entry_id=e.id, mention=name, tone=tones[0]))
    db.session.commit()

    calls = {
        'what_changed': {},
        'contrast_days': {'start': 'не дата'},
        'person_deep': {'name': 'Машу'},
        'entries_query': {'weekday': '0', 'max_rating': 'много', 'bogus': 1, 'limit': 5},
        'rhythms': {},
        'themes': {'start': (today - timedelta(days=30)).isoformat()},
    }
    assert set(calls) == set(ANALYSIS_TOOLS)
    for tool, args in calls.items():
        out = _execute_tool(tool, args)
        assert out and 'Traceback' not in out, tool
    assert _execute_tool('person_deep', {'name': 'Машу'}).startswith('«Маша»')
    assert 'понедельник' in _execute_tool('entries_query', {'weekday': 0})


def test_tool_section_gives_short_results_all_they_need():
    from app.modules.assistant.routes import _tool_section
    out = _tool_section([('a', 'q' * 600), ('b', 'z' * 9000),
                         ('c', 'w' * 400)], 8000)
    assert out.count('q') == 600 and out.count('w') == 400
    assert out.count('z') == 8000 - 600 - 400
    # Evenly, when everything is long.
    out = _tool_section([('j', 'x' * 9000), ('k', 'y' * 9000)], 8000)
    assert out.count('x') == out.count('y') == 4000


def test_dates_are_written_the_way_answers_say_them():
    from app.modules.assistant.llm_text import ru_date, ru_span
    assert ru_date(date(2025, 6, 2)) == '2 июня 2025, пн'
    assert ru_date(date(2025, 6, 2), weekday=False) == '2 июня 2025'
    assert ru_span(date(2026, 3, 5), date(2026, 3, 12)) == 'с 5 по 12 марта 2026'
    assert ru_span(date(2026, 8, 29), date(2026, 9, 27)) == 'с 29 августа по 27 сентября 2026'
    assert ru_span(date(2025, 12, 29), date(2026, 1, 3)) == 'с 29 декабря 2025 по 3 января 2026'
    assert ru_span(date(2026, 1, 1), date(2026, 1, 1)) == '1 января 2026'
