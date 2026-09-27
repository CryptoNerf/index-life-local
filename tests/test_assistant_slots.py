"""What code reads from a question before the router model sees it.

Checked against the same labelled questions the router evaluation uses
(tools/assistant_eval/cases.jsonl), with "today" pinned so relative
periods ("на прошлой неделе", "три месяца назад") have one right answer.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.modules.assistant.slots import extract_slots, parse_period

TODAY = date(2026, 9, 27)
KNOWN_PEOPLE = ['Маша', 'Сергей', 'Лёша', 'Мари', 'Дима', 'Илья', 'Лена']
KNOWN_ACTIVITIES = ['прогулка', 'спорт', 'работа', 'учёба', 'чтение', 'бег',
                    'встреча с друзьями']

CASES = [json.loads(line) for line in
         (Path(__file__).resolve().parents[1] / 'tools' / 'assistant_eval' / 'cases.jsonl')
         .read_text(encoding='utf-8').splitlines() if line.strip()]
LABELLED = [c for c in CASES if c.get('slots')]


@pytest.mark.parametrize('case', LABELLED, ids=[c['q'][:40] for c in LABELLED])
def test_slots_match_the_labels(case):
    got = extract_slots(case['q'], TODAY, KNOWN_PEOPLE, KNOWN_ACTIVITIES)
    want = case['slots']
    if 'period' in want:
        assert got.period is not None, 'no period found'
        assert got.period.kind == want['period']['kind'], got.period
        if 'start' in want['period']:
            assert got.period.start.isoformat() == want['period']['start'], got.period
        if 'end' in want['period']:
            assert got.period.end.isoformat() == want['period']['end'], got.period
    if 'people' in want:
        assert set(want['people']) <= set(got.people), got.people
    if 'emotions' in want:
        assert set(want['emotions']) <= set(got.emotions), got.emotions
    if 'filters' in want:
        assert got.filters() == want['filters'], got.filters()


def test_questions_without_day_filters_get_none():
    """Every labelled question that names no filter gets none: a stray
    "плохие дни" would narrow a plan to the wrong days."""
    for case in CASES:
        if 'filters' not in (case.get('slots') or {}):
            got = extract_slots(case['q'], TODAY, KNOWN_PEOPLE, KNOWN_ACTIVITIES).filters()
            assert got == {}, (case['q'], got)


def test_questions_without_a_period_get_none():
    """A period invented where there is none would steer the data plan."""
    for q in ('Что мне помогает чувствовать себя лучше?', 'Кто на меня плохо влияет?',
              'Когда я последний раз видел Лёшу?', 'настроение 7.5 это нормально?',
              'Сколько у меня записей?'):
        assert parse_period(q, TODAY) is None, q


def test_a_known_name_is_found_in_any_case_form():
    for q in ('с Машей', 'про Машу', 'у Маши', 'Маше написал'):
        assert 'Маша' in extract_slots(q, TODAY, KNOWN_PEOPLE).people, q


def test_a_month_named_without_a_year_is_the_last_one_that_happened():
    assert parse_period('в декабре', TODAY).start == date(2025, 12, 1)
    assert parse_period('в марте', TODAY).start == date(2026, 3, 1)


def test_seasons_step_back_with_proshlym():
    assert parse_period('этим летом', TODAY).start == date(2026, 6, 1)
    assert parse_period('прошлым летом', TODAY).start == date(2025, 6, 1)
    assert parse_period('прошлой зимой', TODAY).start == date(2024, 12, 1)
