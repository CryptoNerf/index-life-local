"""Combined extraction (one LLM call = summary + people + activities).

Quality-parity contract: the combined parser applies the exact same
per-item validation as the standalone extractors (shared _clean_* helpers),
and anything unusable returns None so the caller falls back to the three
individual calls — a degraded model answer can never silently produce
empty sections.
"""
import json
from datetime import date

import pytest

from app import db
from app.models import (
    MoodEntry, EntrySummary, EntryPerson, EntryActivity,
)
from app.modules.assistant.memory import (
    _parse_combined_response, extract_entry_combined,
)

GOOD = json.dumps({
    'summary': 'Хороший день: прогулка и встреча с Олей.',
    'themes': ['прогулка', 'общение'],
    'people': [{'mention': 'Оля', 'tone': 'positive'},
               {'mention': 'Мама', 'tone': 'neutral'}],
    'activities': ['прогулка', 'встреча с друзьями'],
}, ensure_ascii=False)


# ── parser ────────────────────────────────────────────────────

def test_parses_a_clean_response():
    parsed = _parse_combined_response(GOOD)
    assert parsed['summary'].startswith('Хороший день')
    assert parsed['themes'] == ['прогулка', 'общение']
    assert parsed['people'] == [
        {'mention': 'Оля', 'tone': 'positive'},
        {'mention': 'Мама', 'tone': 'neutral'},
    ]
    assert parsed['activities'] == ['прогулка', 'встреча с друзьями']


def test_tolerates_markdown_wrapping_and_think_tags():
    text = '<think>рассуждения</think>\n```json\n' + GOOD + '\n```'
    parsed = _parse_combined_response(text)
    assert parsed is not None
    assert parsed['people'][0]['mention'] == 'Оля'


def test_missing_or_junk_summary_falls_back():
    no_summary = json.dumps({'themes': [], 'people': [], 'activities': []})
    assert _parse_combined_response(no_summary) is None
    think_summary = json.dumps({'summary': '<think>х</think>',
                                'people': [], 'activities': []})
    assert _parse_combined_response(think_summary) is None
    assert _parse_combined_response('не JSON вовсе') is None


def test_broken_section_shape_falls_back():
    bad_people = json.dumps({'summary': 'День как день.',
                             'people': 'Оля', 'activities': []})
    assert _parse_combined_response(bad_people) is None
    bad_acts = json.dumps({'summary': 'День как день.',
                           'people': [], 'activities': {'a': 1}})
    assert _parse_combined_response(bad_acts) is None


def test_missing_sections_default_to_empty():
    only_summary = json.dumps({'summary': 'Спокойный день без событий.'})
    parsed = _parse_combined_response(only_summary)
    assert parsed == {'summary': 'Спокойный день без событий.',
                      'themes': [], 'people': [], 'activities': []}


def test_applies_the_same_item_validation_as_standalone_paths():
    messy = json.dumps({
        'summary': 'День с людьми.',
        'themes': ['a', 'b', 'c', 'd', 'e', 'f', ''],       # cap 5, drop empty
        'people': [
            {'mention': 'Она', 'tone': 'positive'},          # pronoun — drop
            {'mention': 'Оля', 'tone': 'великолепный'},      # bad tone — drop
            {'mention': 'Оля', 'tone': 'positive'},
            {'mention': 'Оля', 'tone': 'positive'},          # dupe — drop
            'просто строка',                                 # not a dict — drop
        ],
        'activities': ['Спорт', 'спорт', 'x' * 31, '', 'чтение'],
    }, ensure_ascii=False)
    parsed = _parse_combined_response(messy)
    assert len(parsed['themes']) == 5
    assert parsed['people'] == [{'mention': 'Оля', 'tone': 'positive'}]
    assert parsed['activities'] == ['спорт', 'чтение']


# ── write path (fake LLM, no model) ───────────────────────────

class _FakeLLM:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def create_chat_completion(self, **kwargs):
        self.calls += 1
        return {'choices': [{'message': {'content': self.text}}]}


@pytest.fixture
def entry(app):
    e = MoodEntry(date=date(2026, 7, 3), rating=8,
                  note='Гуляли с Олей, потом читал.')
    db.session.add(e)
    db.session.commit()
    return e


def test_one_call_writes_all_three_sections(entry):
    llm = _FakeLLM(GOOD)

    assert extract_entry_combined(entry, llm) is True

    assert llm.calls == 1
    summary = EntrySummary.query.filter_by(entry_id=entry.id).first()
    assert summary.summary.startswith('Хороший день')
    assert json.loads(summary.themes) == ['прогулка', 'общение']
    mentions = {(p.mention, p.tone) for p in EntryPerson.query.all()}
    assert mentions == {('Оля', 'positive'), ('Мама', 'neutral')}
    acts = {a.activity for a in EntryActivity.query.all()}
    assert acts == {'прогулка', 'встреча с друзьями'}


def test_rerun_replaces_prior_rows(entry):
    extract_entry_combined(entry, _FakeLLM(GOOD))

    updated = json.dumps({'summary': 'Совсем другой день.', 'themes': [],
                          'people': [{'mention': 'Дима', 'tone': 'neutral'}],
                          'activities': ['работа']}, ensure_ascii=False)
    entry = db.session.get(MoodEntry, entry.id)
    extract_entry_combined(entry, _FakeLLM(updated))

    assert EntrySummary.query.count() == 1
    assert EntrySummary.query.first().summary == 'Совсем другой день.'
    assert [p.mention for p in EntryPerson.query.all()] == ['Дима']
    assert [a.activity for a in EntryActivity.query.all()] == ['работа']


def test_unusable_answer_leaves_existing_data_untouched(entry):
    extract_entry_combined(entry, _FakeLLM(GOOD))

    entry = db.session.get(MoodEntry, entry.id)
    ok = extract_entry_combined(entry, _FakeLLM('мусор вместо JSON'))

    assert ok is False                                   # caller will fall back
    # nothing was deleted before the parse succeeded
    assert EntryPerson.query.count() == 2
    assert EntryActivity.query.count() == 2
    assert EntrySummary.query.first().summary.startswith('Хороший день')


def test_empty_note_writes_placeholder_without_llm(app):
    e = MoodEntry(date=date(2026, 7, 4), rating=6, note='')
    db.session.add(e)
    db.session.commit()
    llm = _FakeLLM(GOOD)

    assert extract_entry_combined(e, llm) is True

    assert llm.calls == 0                                # no model call needed
    assert EntrySummary.query.first().summary == 'Настроение 6/10, без заметки.'
    assert EntryPerson.query.count() == 0
    assert EntryActivity.query.count() == 0


# ── feature flag ──────────────────────────────────────────────

def test_combined_extract_is_opt_in(monkeypatch):
    """A/B showed no wall-clock win on the current model, so the combined
    path must stay opt-in until re-measured on a faster one."""
    from app.modules.assistant.background import _combined_extract_enabled

    monkeypatch.delenv('ASSISTANT_COMBINED_EXTRACT', raising=False)
    assert _combined_extract_enabled() is False

    monkeypatch.setenv('ASSISTANT_COMBINED_EXTRACT', '1')
    assert _combined_extract_enabled() is True

    monkeypatch.setenv('ASSISTANT_COMBINED_EXTRACT', '0')
    assert _combined_extract_enabled() is False
