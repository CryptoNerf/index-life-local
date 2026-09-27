"""The scenario router without a model: prompt, parsing, fallbacks, plans,
the context layers they ask for, and the range-aware tools the plans call.

How well the model itself picks scenarios is measured by
tools/assistant_eval/run.py on the labelled questions, not here.
"""
import json
from datetime import date, timedelta

import pytest

from app.modules.assistant import scenarios
from app.modules.assistant.scenarios import Decision, plan, route
from app.modules.assistant.slots import Slots, extract_slots

TODAY = date(2026, 9, 27)
KNOWN = ['Маша', 'Сергей', 'Лена']


class FakeLLM:
    """Answers with a fixed string and remembers what it was asked."""

    def __init__(self, content):
        self.content = content
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.content, Exception):
            raise self.content
        return {'choices': [{'message': {'content': self.content}}]}


def _json(scenario, topic='', person=''):
    return json.dumps({'scenario': scenario, 'topic': topic, 'person': person},
                      ensure_ascii=False)


# ── routing ───────────────────────────────────────────────────

def test_router_asks_for_json_under_the_schema_and_passes_slots():
    llm = FakeLLM(_json('person'))
    d = route(llm, 'Что я писал про Машу в марте?', TODAY, known_people=KNOWN)
    assert d.scenario == 'person' and d.source == 'llm'
    kwargs = llm.calls[0]
    assert kwargs['response_format']['type'] == 'json_object'
    assert kwargs['response_format']['schema']['properties']['scenario']['enum'] \
        == list(scenarios.SCENARIOS)
    prompt = kwargs['messages'][0]['content']
    # The parsed details reach the model, so it doesn't redo the dates.
    assert 'люди: Маша' in prompt and '2026-03-01' in prompt
    assert 'Сегодня: 2026-09-27' in prompt


@pytest.mark.parametrize('said', ['topic', 'period', 'diary_meta'])
def test_a_person_question_filed_as_a_look_alike_becomes_person(said):
    d = route(FakeLLM(_json(said, person='Маша')), 'Что я писал про Машу?', TODAY,
              known_people=KNOWN)
    assert d.scenario == 'person'
    # A named person in a question that is really about something else stays put.
    d = route(FakeLLM(_json('support', person='Сергей')), 'Поругался с Сергеем, что делать?',
              TODAY, known_people=KNOWN)
    assert d.scenario == 'support'
    d = route(FakeLLM(_json(said)), 'Что я писал про деньги?', TODAY, known_people=KNOWN)
    assert d.scenario == said


@pytest.mark.parametrize('msg', ['Привет!', 'спасибо', 'Ок, понял', 'Доброе утро)',
                                 'Ты тут?', 'Как дела?'])
def test_small_talk_skips_the_model(msg):
    llm = FakeLLM(_json('topic'))
    d = route(llm, msg, TODAY)
    assert d.scenario == 'conversation' and d.source == 'rule'
    assert llm.calls == []


@pytest.mark.parametrize('msg', ['Привет, мне сегодня очень тревожно', 'Спасибо, а что с Машей?'])
def test_a_greeting_with_more_after_it_is_routed(msg):
    llm = FakeLLM(_json('support'))
    route(llm, msg, TODAY, known_people=KNOWN)
    assert len(llm.calls) == 1


@pytest.mark.parametrize('content', ['не JSON', '{"scenario": "unknown"}', '', RuntimeError('boom')])
def test_a_broken_answer_falls_back_on_the_slots(content):
    d = route(FakeLLM(content), 'Что было с Машей на прошлой неделе?', TODAY,
              known_people=KNOWN)
    assert d.source == 'fallback'
    assert d.scenario == 'person'  # a person named beats a period
    d = route(FakeLLM(content), 'Что было на прошлой неделе?', TODAY)
    assert d.scenario == 'period'
    d = route(FakeLLM(content), 'Мне очень одиноко', TODAY)
    assert d.scenario == 'support'


def test_parse_decision_tolerates_text_around_the_json():
    raw = '<think></think>\nВот: {"scenario": "topic", "topic": "работа", "person": ""} '
    assert scenarios.parse_decision(raw) == {'scenario': 'topic', 'topic': 'работа', 'person': ''}


def test_a_follow_up_keeps_the_previous_questions_details():
    llm = FakeLLM(_json('person'))
    d = route(llm, 'Расскажи подробнее', TODAY,
              prior_messages=['Что я писал про Машу?'], known_people=KNOWN)
    assert d.slots.people == ['Маша']
    assert 'Что я писал про Машу?' in llm.calls[0]['messages'][0]['content']
    # A follow-up naming its own person replaces the old one.
    d = route(FakeLLM(_json('person')), 'А с Сергеем?', TODAY,
              prior_messages=['Что я писал про Машу?'], known_people=KNOWN)
    assert d.slots.people == ['Сергей']


def test_router_lock_is_held_during_the_call():
    import threading
    lock = threading.Lock()

    class Checking(FakeLLM):
        def create_chat_completion(self, **kwargs):
            assert lock.locked()
            return super().create_chat_completion(**kwargs)

    route(Checking(_json('topic')), 'Что я писал про деньги?', TODAY, lock=lock)
    assert not lock.locked()


# ── plans ─────────────────────────────────────────────────────

def _plan(scenario, msg, topic='', person='', prior=None):
    own = extract_slots(msg, TODAY, KNOWN)
    slots = own
    if prior:
        slots = scenarios.merge_slots(own, extract_slots(prior, TODAY, KNOWN))
    return plan(Decision(scenario, topic, person, slots, own=own), msg, TODAY)


def _tools(calls):
    return [c['tool'] for c in calls]


def test_period_plans_fetch_exactly_the_period_named():
    assert _plan('period', 'Что было на прошлой неделе?') == [
        {'tool': 'period_entries', 'args': {'start': '2026-09-14', 'end': '2026-09-20'}}]
    assert _plan('period', 'Как прошёл мой март?') == [
        {'tool': 'period_entries', 'args': {'year': 2026, 'month': 3}}]
    assert _plan('period', 'Что у меня было год назад?') == [
        {'tool': 'on_this_day', 'args': {}}]
    # Nothing named: the last week, not a whole month.
    assert _plan('period', 'Что было?') == [
        {'tool': 'period_entries', 'args': {'start': '2026-09-21', 'end': '2026-09-27'}}]


def test_compare_reads_both_periods_earlier_first():
    assert _plan('compare', 'Как отличается август от июля?') == [
        {'tool': 'compare_periods', 'args': {'period_a': '2026-07', 'period_b': '2026-08'}}]
    assert _plan('compare', 'Этот месяц лучше прошлого?') == [
        {'tool': 'compare_periods', 'args': {'period_a': '2026-08', 'period_b': '2026-09'}}]
    assert _plan('compare', 'Лето было лучше зимы?') == [
        {'tool': 'compare_periods', 'args': {'period_a': '2025-12-01..2026-02-28',
                                             'period_b': '2026-06-01..2026-08-31'}}]


def test_why_changed_looks_at_the_change_not_only_the_level():
    calls = _plan('why_changed', 'Почему в последние две недели настроение упало?')
    assert _tools(calls) == ['mood_trend', 'compare_periods', 'activity_impact']
    assert calls[1]['args'] == {'period_a': '2026-08-31..2026-09-13',
                                'period_b': '2026-09-14..2026-09-27'}
    # A month that is over: its entries, against the month before.
    calls = _plan('why_changed', 'Что пошло не так в августе?')
    assert calls[0] == {'tool': 'period_entries', 'args': {'year': 2026, 'month': 8}}
    assert calls[1]['args'] == {'period_a': '2026-07', 'period_b': '2026-08'}


def test_person_plan_uses_names_from_slots_and_router():
    assert _plan('person', 'Что я писал про Сергея в марте?') == [
        {'tool': 'person_history', 'args': {'name': 'Сергей'}},
        {'tool': 'period_entries', 'args': {'year': 2026, 'month': 3}}]
    # A name the diary doesn't know yet comes from the router.
    assert _plan('person', 'Как там Аркадий?', person='Аркадий') == [
        {'tool': 'person_history', 'args': {'name': 'Аркадий'}}]
    assert _plan('person', 'Расскажи подробнее', prior='Что я писал про Машу?') == [
        {'tool': 'person_history', 'args': {'name': 'Маша'}}]


@pytest.mark.parametrize('scenario', ['topic', 'period', 'diary_meta', 'drivers', 'support'])
def test_a_named_person_is_fetched_whatever_the_scenario(scenario):
    # The eval showed the model filing "что я писал про Машу" under topic,
    # period or diary_meta while naming the person correctly.
    calls = _plan(scenario, 'Что я писал про Машу?', person='Маша')
    assert calls[0] == {'tool': 'person_history', 'args': {'name': 'Маша'}}
    assert len(calls) <= scenarios.MAX_CALLS


def test_small_talk_and_the_people_overview_skip_the_person_lookup():
    assert _plan('conversation', 'Сегодня с Машей гуляли, было здорово', person='Маша') == []
    assert _tools(_plan('people', 'Кто лучше влияет, Маша или Сергей?')) == ['people_overview']


def test_a_bare_follow_up_keeps_the_previous_person_under_any_scenario():
    calls = _plan('chat_memory', 'Расскажи подробнее', prior='Что я писал про Машу?')
    assert calls == [{'tool': 'person_history', 'args': {'name': 'Маша'}}]
    # A follow-up with its own subject does not drag the old person along.
    assert 'person_history' not in _tools(
        _plan('topic', 'А что я писал про деньги в марте?', topic='деньги',
              prior='Что я писал про Машу?'))


def test_progress_compares_when_the_question_does():
    calls = _plan('progress', 'Я сейчас счастливее, чем год назад?')
    assert _tools(calls)[:2] == ['mood_trend', 'compare_periods']
    assert calls[1]['args'] == {'period_a': '2025-08-29..2025-09-27',
                                'period_b': '2026-08-29..2026-09-27'}
    assert _tools(_plan('progress', 'Становится ли мне лучше со временем?')) == ['mood_trend']


def test_drivers_add_the_trend_when_asked_about_a_change():
    assert 'mood_trend' in _tools(_plan('drivers', 'с чем связан мой подъём настроения'))
    assert 'mood_trend' in _tools(_plan('drivers', 'чё у меня с настроением последнее время'))


def test_themes_with_a_subject_search_it():
    assert _plan('themes', 'Что я писал про деньги?', topic='деньги') == [
        {'tool': 'search_topic', 'args': {'query': 'деньги'}}]
    assert _plan('themes', 'О чём я чаще всего пишу?') == []


def test_topic_query_widens_a_feeling_with_its_words():
    calls = _plan('topic', 'Когда мне было тревожно?')
    q = calls[0]['args']['query']
    assert q.split()[0] == 'тревога' and 'беспокойство' in q
    assert _plan('topic', 'Что у меня с работой?', topic='работа')[0]['args']['query'] == 'работа'


def test_drivers_pick_weather_and_extremes_from_the_question():
    assert _tools(_plan('drivers', 'В дождь мне правда хуже?')) == ['weather_impact', 'activity_impact']
    assert _tools(_plan('drivers', 'Что общего у моих лучших дней?')) == ['best_worst_days', 'activity_impact']
    assert _tools(_plan('drivers', 'Что меня выматывает?')) == ['activity_impact']


@pytest.mark.parametrize('scenario', ['conversation', 'themes', 'chat_memory', 'about_me'])
def test_scenarios_without_a_tool_fetch_nothing(scenario):
    # (no person, no topic named)
    assert _plan(scenario, 'Что ты обо мне знаешь про работу в марте?') == []


def test_every_plan_is_at_most_three_calls():
    for sc in scenarios.SCENARIOS:
        calls = _plan(sc, 'Мне тревожно из-за Маши и Сергея и Лены, погода, лучшие дни, люди в марте',
                      topic='тревога', person='Лена')
        assert len(calls) <= scenarios.MAX_CALLS, sc


def test_context_layers_drop_what_the_tools_already_fetched():
    assert scenarios.context_layers('person', has_evidence=True) == {'relevant': False, 'timeline': False}
    assert scenarios.context_layers('person', has_evidence=False)['relevant'] is True
    assert scenarios.context_layers('review', has_evidence=True) == {'relevant': False, 'timeline': True}
    assert scenarios.context_layers('conversation', has_evidence=False) == {'relevant': False, 'timeline': False}
    assert scenarios.context_layers('themes', has_evidence=False) == {'relevant': True, 'timeline': True}


# ── tools with ranges ─────────────────────────────────────────

def _entries(db, days_ratings):
    from app.models import MoodEntry
    for d, r in days_ratings:
        db.session.add(MoodEntry(date=d, rating=r, note=f'запись {d.isoformat()}', deleted=False))
    db.session.commit()


def test_period_entries_takes_an_exact_range(app):
    from app import db
    from app.modules.assistant.tools import tool_period_entries
    _entries(db, [(date(2026, 3, d), 5) for d in range(1, 20)])
    out = tool_period_entries(start='2026-03-05', end='2026-03-12')
    assert 'Всего 8 записей' in out
    assert '[2026-03-12]' in out and '[2026-03-04]' not in out and '[2026-03-13]' not in out
    # Newest first, as before.
    assert out.index('[2026-03-12]') < out.index('[2026-03-05]')


def test_a_long_period_is_sampled_across_it_with_monthly_averages(app):
    from app import db
    from app.modules.assistant.tools import tool_period_entries
    start = date(2025, 1, 1)
    _entries(db, [(start + timedelta(days=i), 3 if i < 180 else 8) for i in range(365)])
    out = tool_period_entries(2025, limit=40)
    assert 'Всего 365 записей' in out
    assert 'По месяцам: 2025-01 — 3.0 (31)' in out and '2025-12 — 8.0 (31)' in out
    lines = [ln for ln in out.splitlines() if ln.startswith('[2025-')]
    assert len(lines) == 40
    # Not the newest forty: the first months are there too.
    assert any(ln.startswith('[2025-01') for ln in lines)


def test_compare_periods_takes_ranges(app):
    from app import db
    from app.modules.assistant.tools import tool_compare_periods
    _entries(db, [(date(2026, 9, d), 4) for d in range(1, 14)]
             + [(date(2026, 9, d), 8) for d in range(14, 28)])
    out = tool_compare_periods('2026-09-01..2026-09-13', '2026-09-14..2026-09-27')
    assert 'среднее 4.00/10' in out and 'среднее 8.00/10' in out and 'выше на 4.00' in out
    # The old forms still work.
    assert 'Сравнение периодов' in tool_compare_periods('2026-08', '2026-09') or \
        'записей нет' in tool_compare_periods('2026-08', '2026-09')
    assert tool_compare_periods('март', '2026') == ''


def test_diary_vocabulary_resolves_aliases_and_ranks_by_mentions(app):
    from app import db
    from app.models import EntryActivity, EntryPerson, MoodEntry, PersonAlias
    from app.modules.assistant.tools import diary_vocabulary
    e1 = MoodEntry(date=date(2026, 9, 1), rating=5, note='x', deleted=False)
    e2 = MoodEntry(date=date(2026, 9, 2), rating=5, note='y', deleted=False)
    db.session.add_all([e1, e2])
    db.session.commit()
    db.session.add_all([
        EntryPerson(entry_id=e1.id, mention='Маша', tone='positive'),
        EntryPerson(entry_id=e2.id, mention='Машей', tone='neutral'),
        EntryPerson(entry_id=e2.id, mention='Марь', tone='neutral'),
        EntryPerson(entry_id=e1.id, mention='Мари', tone='neutral'),
        PersonAlias(alias='Марь', canonical='Мари'),
        EntryActivity(entry_id=e1.id, activity='бег'),
        EntryActivity(entry_id=e2.id, activity='бег'),
        EntryActivity(entry_id=e2.id, activity='чтение'),
    ])
    db.session.commit()
    people, activities = diary_vocabulary()
    assert set(people) == {'Маша', 'Мари'}
    assert activities == ['бег', 'чтение']


def test_execute_tool_passes_a_range_through(app):
    from app import db
    from app.modules.assistant.routes import _execute_tool
    _entries(db, [(date(2026, 9, 20), 6), (date(2026, 9, 26), 7)])
    out = _execute_tool('period_entries', {'start': '2026-09-26', 'end': '2026-09-26'})
    assert '[2026-09-26]' in out and '[2026-09-20]' not in out


def test_thinking_is_off_while_routing_and_restored_after():
    from app.modules.assistant import routes
    routes._set_request_thinking(True)
    try:
        with routes._thinking_off():
            assert routes._get_request_thinking() is False
        assert routes._get_request_thinking() is True
    finally:
        routes._clear_request_thinking()
    with routes._thinking_off():
        assert routes._get_request_thinking() is False
    assert not hasattr(routes._thinking_state, 'enabled')


def test_router_mode_defaults_to_legacy(monkeypatch):
    from app.modules.assistant import routes
    monkeypatch.delenv('ASSISTANT_ROUTER', raising=False)
    assert routes._router_mode() == 'legacy'
    monkeypatch.setenv('ASSISTANT_ROUTER', 'Scenario')
    assert routes._router_mode() == 'scenario'
    monkeypatch.setenv('ASSISTANT_ROUTER', 'nonsense')
    assert routes._router_mode() == 'legacy'


def test_slots_describe_is_empty_without_details():
    assert Slots().describe() == ''
