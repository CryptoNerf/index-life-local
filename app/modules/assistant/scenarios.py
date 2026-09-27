# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""What kind of question this is, and which diary data answers it.

The older router asked the model to pick tools and fill in their arguments
in one go: dates, names, search queries. A 9B model does that unevenly — it
computes "three months ago" wrong, invents a month for "last week", or
answers in prose around the JSON. Here the work is split:

1. `slots.extract_slots` reads dates, people and feelings with plain rules;
2. the model only names the scenario (and a topic or a person, when there is
   one), under a JSON-schema grammar, so its answer always parses;
3. `plan` turns the scenario and the slots into tool calls, deterministically.

Each step can be tested on its own, and the eval in tools/assistant_eval
measures step 2 against labelled questions.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .slots import (Period, Slots, compare_pair, emotion_synonyms,
                    extract_slots, previous_period)

log = logging.getLogger(__name__)

# id → what it covers. The order is the order the router prompt lists them.
SCENARIOS = {
    'support': 'человеку плохо прямо сейчас: делится состоянием или просит помочь себе сейчас («мне тревожно», «нет сил», «как мне сейчас себе помочь»)',
    'conversation': 'приветствие, благодарность, короткая реплика, рассказ о своём дне без вопроса, общий вопрос не про дневник («привет», «спасибо», «посоветуй книгу», «как дышать при стрессе»)',
    'why_changed': 'почему настроение изменилось: откуда спад или подъём, что пошло не так',
    'drivers': 'что вообще влияет на настроение: что помогает, что выматывает, погода, чем хорошие дни отличаются от плохих',
    'rhythms': 'закономерности во времени: дни недели, выходные и будни, времена года, циклы',
    'themes': 'о чём я пишу чаще всего, какие темы и мысли повторяются',
    'topic': 'одна конкретная тема или чувство: работа, деньги, сон, тревога, «когда мне было одиноко», «упоминал ли я здоровье»',
    'person': 'один-два конкретных человека по имени или роли (мама, начальник)',
    'people': 'люди в целом: кто поддерживает, кто плохо влияет, кого я чаще упоминаю',
    'period': 'что было в конкретный день, неделю, месяц, сезон или год, что было в этот день год назад',
    'review': 'подвести итоги периода или сделать его обзор',
    'compare': 'сравнить два периода между собой',
    'progress': 'изменилось ли что-то во мне со временем: есть ли прогресс, как менялось настроение, стал ли я реже или чаще что-то делать или чувствовать',
    'diary_meta': 'про сам дневник: сколько записей, как давно веду, серии, среднее настроение, самый худший или лучший день',
    'chat_memory': 'про наши прошлые разговоры в этом чате («что я тебе говорил», «мы уже обсуждали»)',
    'about_me': 'что ты обо мне знаешь, какой я человек, мой портрет, мои сильные стороны',
}

ROUTER_SCHEMA = {
    'type': 'object',
    'properties': {
        'scenario': {'type': 'string', 'enum': list(SCENARIOS)},
        'topic': {'type': 'string', 'maxLength': 40},
        'person': {'type': 'string', 'maxLength': 40},
    },
    'required': ['scenario', 'topic', 'person'],
}

_ROUTER_PROMPT = """Ты — диспетчер AI-психолога. Определи, какого типа сообщение пользователя, чтобы подобрать к ответу нужные данные из его дневника.

Сегодня: {today}.

Типы:
{scenarios}

Правила:
- Если сообщение продолжает прошлое («а с Сергеем?», «расскажи подробнее», «и почему так?»), тип выбирай с учётом прошлого сообщения.
- Человек назван и вопрос про него — person, даже если в вопросе есть чувство.
- Чувство без вопроса о прошлом — support. Вопрос «почему так стало» — why_changed. «Когда такое было» — topic.
- topic — тема в 1–3 словах, если сообщение про тему или чувство, иначе пустая строка.
- person — имя или роль человека, если он назван, иначе пустая строка.

{prior}{found}Сообщение:
{message}

Ответ — только JSON."""

# Messages that are only a greeting, thanks or an acknowledgement. They need
# no diary data and no router call.
_SMALL_TALK = re.compile(
    r'^\s*(?:привет|приветик|здравствуй(?:те)?|добр(?:ое|ый|ой)\s+(?:утро|день|вечер|ночи)|'
    r'хай|хей|спасибо(?:\s+большое)?|благодарю|ок(?:ей)?|окей|ладно|понятно|понял[аи]?|'
    r'ясно|хорошо|договорились|пока|до\s+завтра|спокойной\s+ночи|ты\s+тут|ты\s+здесь|'
    r'как\s+(?:дела|ты)|угу|ага|да|нет)'
    r'(?:[\s,.!?)(]+(?:привет|спасибо|ок|понял[аи]?|ясно|хорошо|пока|да|нет))*[\s,.!?)(:]*$',
    re.I)


@dataclass
class Decision:
    scenario: str
    topic: str = ''
    person: str = ''
    slots: Slots = field(default_factory=Slots)
    source: str = 'llm'  # llm | rule | fallback
    # What the message itself names; `slots` also carries what a follow-up
    # inherited from the previous question. None means the same as `slots`.
    own: Slots | None = None

    def as_dict(self) -> dict:
        return {'scenario': self.scenario, 'topic': self.topic,
                'person': self.person, 'source': self.source,
                'slots': self.slots.as_dict()}


def is_small_talk(message: str) -> bool:
    return bool(_SMALL_TALK.match(message or ''))


def merge_slots(current: Slots, prior: Slots | None) -> Slots:
    """A follow-up ("а что было после этого?") keeps what the previous
    question named, unless it names its own."""
    if prior is None:
        return current
    return Slots(
        period=current.period or prior.period,
        people=current.people or prior.people,
        activities=current.activities or prior.activities,
        emotions=current.emotions or prior.emotions,
        rating=current.rating,
        weekday=current.weekday,
        weather=current.weather,
    )


def build_prompt(message: str, today: date, slots: Slots,
                 prior_messages=()) -> str:
    prior = ''
    recent = [m.strip() for m in prior_messages if m and m.strip()][-2:]
    if recent:
        lines = [(m[:300] + '…') if len(m) > 300 else m for m in recent]
        prior = ('Прошлые сообщения пользователя (для контекста):\n'
                 + '\n'.join(f'- {m}' for m in lines) + '\n\n')
    found = slots.describe()
    if found:
        found = 'В сообщении найдено:\n' + found + '\n\n'
    return _ROUTER_PROMPT.format(
        today=today.isoformat(),
        scenarios='\n'.join(f'- {k} — {v}.' for k, v in SCENARIOS.items()),
        prior=prior, found=found, message=message.strip(),
    )


def parse_decision(text: str) -> dict | None:
    """The router's JSON, or None. Tolerates stray text around it."""
    text = (text or '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get('scenario') not in SCENARIOS:
        return None
    return {
        'scenario': data['scenario'],
        'topic': str(data.get('topic') or '').strip()[:60],
        'person': str(data.get('person') or '').strip()[:60],
    }


def _fallback(slots: Slots) -> str:
    """A guess from the slots alone, for when the model can't be asked."""
    if slots.people:
        return 'person'
    if slots.period:
        return 'period'
    if slots.emotions:
        return 'support'
    return 'conversation'


def route(llm, message: str, today: date, *, prior_messages=(),
          known_people=(), known_activities=(), lock=None,
          max_tokens: int = 60) -> Decision:
    """Slots by rule, the scenario by the model under a JSON grammar."""
    slots = extract_slots(message, today, known_people, known_activities)
    prior_slots = None
    if prior_messages:
        prior_slots = extract_slots(prior_messages[-1], today,
                                    known_people, known_activities)
    merged = merge_slots(slots, prior_slots)

    if is_small_talk(message):
        return Decision('conversation', slots=slots, source='rule', own=slots)

    prompt = build_prompt(message, today, slots, prior_messages)
    kwargs = dict(
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=max_tokens,
        temperature=0.0,
        response_format={'type': 'json_object', 'schema': ROUTER_SCHEMA},
    )
    try:
        if lock is not None:
            with lock:
                result = llm.create_chat_completion(**kwargs)
        else:
            result = llm.create_chat_completion(**kwargs)
        text = result['choices'][0]['message']['content'] or ''
        parsed = parse_decision(re.sub(r'<think>.*?</think>', '', text, flags=re.S))
    except Exception as exc:
        log.warning('Scenario router failed: %s', exc)
        parsed = None
    if parsed is None:
        return Decision(_fallback(merged), slots=merged, source='fallback', own=slots)
    return Decision(_correct(parsed, slots), parsed['topic'], parsed['person'],
                    slots=merged, source='llm', own=slots)


# Scenarios the model picks for a question that is really about someone:
# "Что я писал про Машу?" reads like a topic, "когда я видел Лёшу" like a
# date. It still names the person, so the slip is visible.
_PERSON_LOOKALIKES = {'topic', 'period', 'diary_meta'}


def _correct(parsed: dict, own: Slots) -> str:
    """The model's scenario, unless the message plainly says otherwise:
    it names a person and the model filed it under a look-alike, or it is
    filed as a period while naming no period, only a topic ("когда я
    последний раз писал про переезд?")."""
    sc = parsed['scenario']
    named = bool(own.people) or bool(parsed['person'])
    if sc in _PERSON_LOOKALIKES and named:
        return 'person'
    if sc == 'period' and not own.period and parsed['topic']:
        return 'topic'
    return sc


# ── plans ─────────────────────────────────────────────────────

MAX_CALLS = 3

_WEATHER = re.compile(r'погод|дожд|солн|жар|холод|снег|пасмур|температур', re.I)
_EXTREMES = re.compile(r'(лучш|худш|хорош|плох)\w*\s+(\w+\s+)?(дн|день|дня)', re.I)
_PEOPLE_WORDS = re.compile(r'\bлюд|\bкто\b|\bкого\b|\bс кем\b|друз', re.I)


def _period_args(p: Period, long_limit: int = 25) -> dict:
    """period_entries arguments: a whole month or year by number, anything
    else as an exact range. A long period asks for fewer entries, spread
    across it, so the list fits the context whole instead of being cut to
    its newest part."""
    if p.kind == 'month' and p.start.day == 1:
        args = {'year': p.start.year, 'month': p.start.month}
    elif p.kind == 'year' and (p.start.month, p.start.day) == (1, 1):
        args = {'year': p.start.year}
    else:
        args = {'start': p.start.isoformat(), 'end': p.end.isoformat()}
    if (p.end - p.start).days > 45:
        args['limit'] = long_limit
    return args


def _range_args(p: Period) -> dict:
    return {'start': p.start.isoformat(), 'end': p.end.isoformat()}


# Periods short enough that "про Сергея в марте" means those entries rather
# than the whole story of the person.
_NARROW = {'day', 'week', 'month', 'range', 'season'}


def _period_spec(p: Period) -> str:
    """A compare_periods operand."""
    if p.kind == 'month' and p.start.day == 1:
        return f'{p.start.year}-{p.start.month:02d}'
    if p.kind == 'year' and (p.start.month, p.start.day) == (1, 1):
        return str(p.start.year)
    return f'{p.start.isoformat()}..{p.end.isoformat()}'


def _recent(days: int, today: date) -> Period:
    return Period(today - timedelta(days=days - 1), today, 'recent', f'последние {days} дн.')


def _trend_window(days: int) -> int:
    """A trend window twice the span asked about, so a change within it
    shows against what came before."""
    return max(30, min(180, 2 * days))


def _is_past(p: Period, today: date) -> bool:
    """Ended more than a week ago: the recent trend says nothing about it."""
    return p.end < today - timedelta(days=7)


def _topic_query(d: Decision, message: str) -> str:
    """A search query: the router's topic plus a few words for each feeling."""
    words = []
    if d.topic:
        words.append(d.topic)
    for emo in d.slots.emotions[:2]:
        if not any(emo in w for w in words):
            words.append(emo)
        words.extend(w for w in emotion_synonyms(emo)[:3] if w != emo)
    if not words:
        words.append(message.strip()[:80])
    seen, out = set(), []
    for w in ' '.join(words).split():
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return ' '.join(out[:8])


def _is_follow_up(d: Decision, message: str) -> bool:
    """"Расскажи подробнее", "а потом?": short, and naming nothing itself."""
    own = d.own if d.own is not None else d.slots
    names_nothing = not (own.period or own.people or own.emotions or d.person)
    return names_nothing and len(re.findall(r'\w+', message)) <= 4


def _topic_words(d: Decision) -> list[str]:
    """Words to find a topic by in the text itself: the router's topic, or
    a feeling's commonest words."""
    if d.topic:
        head = re.findall(r'\w+', d.topic)
        return head[:1]
    if d.slots.emotions:
        return emotion_synonyms(d.slots.emotions[0])[:4]
    return []


def _people(d: Decision, message: str = '') -> list[str]:
    """People the question is about: named in it (by rule or by the model),
    or, for a bare follow-up, the ones the previous question named."""
    own = d.own if d.own is not None else d.slots
    names = list(own.people)
    if d.person and not any(d.person.lower() == n.lower() for n in names):
        names.append(d.person)
    if not names and (d.scenario == 'person' or _is_follow_up(d, message)):
        names = list(d.slots.people)
    return names[:2]


# Scenarios where a named person is not what the data should be about.
_NO_PERSON_LOOKUP = {'conversation', 'people'}
_SUPERLATIVE = re.compile(r'сам\w+\s+(лучш|худш|плох|хорош|тяж[её]л|счастлив|светл)', re.I)
_WHEN = re.compile(r'\bкогда\b|как часто|сколько раз|последний раз|впервые|'
                   r'перв\w+ раз|стал\w* (?:реже|чаще|меньше|больше)|перестал', re.I)
_CHANGE = re.compile(r'подъ[её]м|спад|\bстал[аио]?\b|\bстало\b|измени|последн\w* врем', re.I)


def plan(d: Decision, message: str, today: date) -> list[dict]:
    """Tool calls for a decision: [{'tool': name, 'args': {...}}], at most three."""
    s = d.slots
    period = s.period
    filters = s.filters()
    calls: list[dict] = []

    def add(tool: str, **args):
        if len(calls) < MAX_CALLS and {'tool': tool, 'args': args} not in calls:
            calls.append({'tool': tool, 'args': args})

    sc = d.scenario
    # A named person comes first whatever the scenario: the model names the
    # person reliably even when it files "что я писал про Машу" under a
    # topic, and a question about someone needs their entries. With a short
    # period ("про Сергея в марте") that means the entries of that period;
    # otherwise the whole picture of the person.
    if sc not in _NO_PERSON_LOOKUP:
        narrow = bool(period and period.kind in _NARROW)
        for name in _people(d, message):
            if narrow and sc in ('person', 'topic', 'period', 'diary_meta'):
                add('entries_query', person=name, **_range_args(period), **filters)
            else:
                add('person_deep', name=name)

    if sc == 'support':
        add('mood_trend', window_days=14)
        add('activity_impact')
        if s.emotions or d.topic:
            add('search_topic', query=_topic_query(d, message))

    elif sc == 'why_changed':
        if period and period.kind not in ('recent', 'day', 'anniversary'):
            # A named month or season, against the one before it.
            add('what_changed', period_a=_period_spec(previous_period(period)),
                period_b=_period_spec(period))
            if _is_past(period, today):
                add('period_entries', **_period_args(period))
            else:
                add('mood_trend', window_days=_trend_window((today - period.start).days + 1))
        else:
            days = (period.end - period.start).days + 1 if period and period.kind == 'recent' else 30
            now = _recent(days, today)
            add('what_changed', period_a=_period_spec(previous_period(now)),
                period_b=_period_spec(now))
            add('mood_trend', window_days=_trend_window(days))

    elif sc == 'drivers':
        if _WEATHER.search(message) or s.weather:
            add('weather_impact')
        add('contrast_days')
        add('activity_impact')
        if _CHANGE.search(message) or (period and period.kind == 'recent'):
            # "с чем связан мой подъём": the change itself, not only its causes
            add('mood_trend', window_days=30)
        if _PEOPLE_WORDS.search(message):
            add('people_overview')

    elif sc == 'rhythms':
        add('rhythms')
        if s.weather:
            # "в снежные дни": how weather goes with mood, not the calendar
            add('weather_impact')
        if s.rating and s.weekday is None and not period:
            # "что общего у моих лучших дней", filed as a rhythm: it asks
            # what those days share, not when they fall.
            add('contrast_days')
        if filters:
            # "что я пишу по понедельникам", "хорошие дни этим летом": the
            # days themselves too, within the period if one is named.
            add('entries_query', **(_range_args(period) if period else {}), **filters, limit=15)

    elif sc == 'themes':
        add('themes', **(_range_args(period) if period else {}))
        # "Что я писал про деньги?" filed as a theme still has a subject.
        if d.topic:
            add('search_topic', query=_topic_query(d, message))

    elif sc == 'topic':
        add('search_topic', query=_topic_query(d, message))
        words = _topic_words(d)
        if words and (period or filters or _WHEN.search(message)):
            # Search by meaning finds similar days; "когда", "как часто" and
            # a period need the matching days by date.
            add('entries_query', word='|'.join(words),
                **(_range_args(period) if period else {}), **filters)
        elif period:
            add('period_entries', **_period_args(period))

    elif sc == 'person':
        if not calls and d.topic:
            add('search_topic', query=_topic_query(d, message))

    elif sc == 'people':
        add('people_overview')

    elif sc == 'period':
        p = period or _recent(7, today)
        if not period and _SUPERLATIVE.search(message):
            # "Когда был мой самый худший день?" asks for the extremes of the
            # whole diary, not for bad days of the last week.
            add('best_worst_days', top_n=5)
        elif p.kind == 'anniversary':
            add('on_this_day')
        elif filters:
            add('entries_query', **_range_args(p), **filters)
        else:
            add('period_entries', **_period_args(p))

    elif sc == 'review':
        p = period or Period(today.replace(day=1), today, 'month', 'этот месяц')
        add('period_entries', **_period_args(p, long_limit=20))
        add('what_changed', period_a=_period_spec(previous_period(p)),
            period_b=_period_spec(p))
        add('themes', **_range_args(p))

    elif sc == 'compare':
        pair = compare_pair(message, today)
        if pair is None:
            now = Period(today.replace(day=1), today, 'month', 'этот месяц')
            pair = (previous_period(now), now)
        add('what_changed', period_a=_period_spec(pair[0]), period_b=_period_spec(pair[1]))

    elif sc == 'progress':
        add('mood_trend', window_days=180)
        # "Я сейчас счастливее, чем год назад?" names what to compare.
        own = d.own if d.own is not None else s
        pair = compare_pair(message, today) if own.period and re.search(
            r'\bчем\b|по сравнению', message, re.I) else None
        if pair:
            add('what_changed', period_a=_period_spec(pair[0]), period_b=_period_spec(pair[1]))
        elif own.period and own.period.kind in ('recent', 'month', 'season', 'year'):
            # "что изменилось за последний месяц": that period against the one before
            add('what_changed', period_a=_period_spec(previous_period(own.period)),
                period_b=_period_spec(own.period))
        words = _topic_words(d)
        if words:
            # Month by month, how often: "стал реже тревожиться?"
            add('entries_query', word='|'.join(words))

    elif sc == 'diary_meta':
        if _EXTREMES.search(message) or _SUPERLATIVE.search(message):
            add('best_worst_days', top_n=5)
        else:
            add('diary_stats')

    # conversation, chat_memory, about_me: nothing to fetch yet (beyond a
    # named person); the profile and the semantic layer carry them.
    return calls


# ── context ───────────────────────────────────────────────────

# The background layers of the system prompt each scenario still wants.
# "relevant" (entries found by meaning or date) repeats what a tool fetched,
# so it is kept only while no tool brought evidence; the monthly timeline is
# kept where the long view is the point.
_TIMELINE = {'why_changed', 'rhythms', 'themes', 'review', 'compare',
             'progress', 'about_me'}
_RELEVANT = {'support', 'why_changed', 'drivers', 'rhythms', 'themes', 'topic',
             'person', 'period', 'review', 'progress', 'about_me'}


def context_layers(scenario: str, has_evidence: bool) -> dict:
    """assemble_context flags for a scenario."""
    return {
        'relevant': scenario in _RELEVANT and not has_evidence,
        'timeline': scenario in _TIMELINE,
    }


# ── how to answer ─────────────────────────────────────────────

# Written after reading the first answer eval: the model misread shares
# ("около четверти" for 75%), cited dates it was never shown, and answered
# an analytic question by paraphrasing it back first.
_ANSWER_RULES = (
    'Даты называй только те, что есть в данных выше. Если точной даты там нет, '
    'не придумывай её. Числа (доли, средние, количества) бери из данных как есть.'
)

ANSWER_GUIDE = {
    'support': 'Сначала коротко откликнись на чувство. Из данных возьми одно-два '
               'наблюдения, только если они помогают: например, что раньше помогало '
               'в похожем состоянии. Без разбора статистики и без списка советов.',
    'conversation': 'Ответь коротко и по-человечески. Не пересказывай дневник, если '
                    'об этом не спрашивали.',
    'why_changed': 'Назови две-три конкретные перемены из сравнения периодов, с цифрами. '
                   'Отдели то, что видно в записях, от догадок: причину не утверждай как факт.',
    'drivers': 'Назови конкретные занятия, людей или погоду, которые чаще бывают в хорошие '
               'и в плохие дни, с цифрами. Связь не значит причину, скажи это мягко.',
    'rhythms': 'Опиши закономерность с цифрами: средние по дням недели, месяцам или сезонам. '
               'Если разница небольшая, так и скажи.',
    'themes': 'Назови две-четыре главные темы с долей записей, отметь, какие идут с тяжёлыми '
              'днями и что стало чаще в последнее время.',
    'topic': 'Ответь про эту тему по найденным записям: когда, как часто, в каком контексте. '
             'Короткие цитаты с датами.',
    'person': 'Опиши картину по данным: как часто, какой тон и как он менялся, настроение '
              'в дни с этим человеком, одна-две короткие цитаты с датами. Не оценивай '
              'и не суди этого человека.',
    'people': 'Назови людей из данных с их тоном и частотой упоминаний. Не суди никого.',
    'period': 'Перескажи период по записям: общий фон со средней оценкой, два-три '
              'заметных дня с датами, что повторялось.',
    'review': 'Итоги периода: средняя оценка и сравнение с предыдущим периодом, главные '
              'темы, что изменилось, светлые и тяжёлые моменты с датами. Без воды.',
    'compare': 'Сначала прямо скажи, какой период был лучше и на сколько (средние), потом '
               'чем они различались.',
    'progress': 'Ответь, есть ли изменение, по цифрам во времени (тренд, счёт по месяцам). '
                'Если данных мало для вывода, скажи об этом.',
    'diary_meta': 'Ответь прямо, цифрами из данных.',
    'chat_memory': 'Опирайся на историю этого чата выше. Если там ответа нет, честно скажи, '
                   'что не помнишь этого разговора.',
    'about_me': 'Опиши человека бережно, по профилю и записям, без диагнозов и ярлыков.',
}


def answer_guidance(scenario: str) -> str:
    """The closing lines of the system prompt: how to use the data above."""
    guide = ANSWER_GUIDE.get(scenario, '')
    lines = ['КАК ОТВЕТИТЬ:']
    if guide:
        lines.append(guide)
    if scenario not in ('conversation', 'chat_memory'):
        lines.append(_ANSWER_RULES)
    return '\n\n' + '\n'.join(lines)



# ── when a tool finds nothing ─────────────────────────────────

# First lines of the tools' "nothing here" answers.
_EMPTY = re.compile(r'^(?:Записей\b.*\b(?:не найдено|нет)\b|По теме .*не найдено|'
                    r'Упоминаний «.*» в разобранных записях нет|Люди в записях ещё не размечены)')


def is_empty(text: str | None) -> bool:
    return not text or bool(_EMPTY.match(text.strip()))


def widen(call: dict, today: date) -> tuple[dict, str] | None:
    """One step wider than a call that found nothing, and a note saying how.

    Without it the model reports "записей нет" when the entries are there,
    just not on that exact day, with that exact word, or under that filter.
    An empty month or year is left alone: that is itself the answer.
    """
    tool, args = call['tool'], dict(call['args'])

    def again(new_tool, new_args, note):
        return {'tool': new_tool, 'args': new_args}, f'По точному запросу ничего нет; {note}.'

    if tool == 'entries_query':
        for key, what in (('max_rating', 'без фильтра по оценке'), ('min_rating', 'без фильтра по оценке'),
                          ('weather', 'без фильтра по погоде'), ('weekday', 'без фильтра по дню недели')):
            if key in args:
                args.pop(key)
                return again(tool, args, f'ниже то же {what}')
        if args.get('start') or args.get('end'):
            if args.get('person') or args.get('word') or args.get('activity'):
                args.pop('start', None)
                args.pop('end', None)
                return again(tool, args, 'ниже поиск по всему дневнику, без периода')
        return None
    if tool == 'period_entries' and args.get('start'):
        try:
            a = date.fromisoformat(args['start'])
            b = date.fromisoformat(args.get('end') or args['start'])
        except ValueError:
            return None
        if (b - a).days <= 7:
            a, b = a - timedelta(days=7), min(today, b + timedelta(days=7))
            return again(tool, {'start': a.isoformat(), 'end': b.isoformat()},
                         'ниже записи за неделю до и после')
        return None
    if tool == 'search_topic' and args.get('query'):
        words = [w for w in re.findall(r'\w+', args['query']) if len(w) > 2][:4]
        if words:
            return again('entries_query', {'word': '|'.join(words)},
                         'ниже записи, где встречаются эти слова')
        return None
    if tool in ('person_deep', 'person_history') and args.get('name'):
        return again('entries_query', {'person': args['name']},
                     'ниже записи, где это имя встречается в тексте')
    if tool == 'on_this_day':
        d = today.replace(year=today.year - 1) if not (today.month == 2 and today.day == 29) \
            else date(today.year - 1, 2, 28)
        return again('period_entries', {'start': (d - timedelta(days=7)).isoformat(),
                                        'end': (d + timedelta(days=7)).isoformat()},
                     'ниже записи за неделю вокруг этой даты год назад')
    return None
