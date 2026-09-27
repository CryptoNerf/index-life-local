"""Answer eval: whole replies, on a made-up diary whose facts are known.

The router eval (run.py) checks which data a question fetches. This one
checks what reaches the reply. It builds a database from the synthetic
two-year diary in tests/assistant_diary.py (patterns planted: hard Mondays,
running that stopped a month ago, a slump every February, Сергей turning
negative, "переезд" appearing lately…), with real embeddings and monthly
summaries, then asks each question through the app's own reply path
(routes._gather_evidence → _grounded_system → the model) under both routers.

Per reply it checks:
- facts: the planted facts the question is about appear in the answer;
- dates: every specific date the answer cites is in what the model was
  given (the system prompt), else it is counted as made up;
- length, long dashes, time.

    venv/bin/python tools/assistant_eval/answers.py [--router both|legacy|scenario]
        [--only N] [--out answers.md]

Close the app's chat first: two copies of the model do not fit in 16 GB.
"""
import argparse
import json
import re
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from app.modules import _add_local_modules_site_packages  # noqa: E402
_add_local_modules_site_packages()

import assistant_diary  # noqa: E402

MONTHS_GEN = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
              'августа', 'сентября', 'октября', 'ноября', 'декабря']


# ── the diary ─────────────────────────────────────────────────

# A day left unwritten, so that one question finds nothing on its exact date
# and the reply depends on the search widening.
SKIPPED_DAYS_AGO = 2


def diary_days():
    """The synthetic diary, moved so that it ends today, one day left out."""
    shift = date.today() - assistant_diary.TODAY
    skipped = date.today() - timedelta(days=SKIPPED_DAYS_AGO)
    days = assistant_diary.make_diary()
    for d in days:
        d.date = d.date + shift
    return [d for d in days if d.date != skipped]


def build_db(app, days):
    """Fill an empty database with the diary and everything derived from it."""
    from app import db
    from app.models import (DailySignal, EntryActivity, EntryEmbedding, EntryPerson,
                            EntrySummary, MoodEntry, PeriodSummary, SyncMeta)
    from app.modules.assistant import memory

    stamp = f'{date.today().isoformat()}:{len(days)}'
    with app.app_context():
        db.create_all()
        row = db.session.get(SyncMeta, 'answers_eval_built')
        if row and row.value == stamp:
            return
        for model in (EntryEmbedding, EntrySummary, EntryActivity, EntryPerson,
                      DailySignal, PeriodSummary, MoodEntry, SyncMeta):
            model.query.delete()
        db.session.commit()

        entries = []
        for d in days:
            e = MoodEntry(date=d.date, rating=d.rating, note=d.note, deleted=False)
            db.session.add(e)
            entries.append((e, d))
        db.session.flush()
        for e, d in entries:
            db.session.add(EntrySummary(entry_id=e.id, summary=d.summary,
                                        themes=json.dumps(list(d.themes), ensure_ascii=False)))
            for a in d.activities:
                db.session.add(EntryActivity(entry_id=e.id, activity=a))
            for name, tones in d.people.items():
                db.session.add(EntryPerson(entry_id=e.id, mention=name, tone=tones[0]))
            db.session.add(DailySignal(date=d.date, source='weather', metric='condition',
                                       value_text=d.weather))
            db.session.add(DailySignal(date=d.date, source='weather', metric='temp_c',
                                       value_num=round(d.temp, 1)))
        db.session.commit()

        print(f'Embedding {len(entries)} entries …', flush=True)
        model = memory._get_embed_model()
        texts = [f'{e.date.isoformat()} Настроение: {e.rating}/10. {(e.note or "").strip()}'
                 for e, _ in entries]
        vecs = model.encode([f'passage: {t}' for t in texts], normalize_embeddings=True,
                            batch_size=64)
        for (e, _), t, v in zip(entries, texts, vecs):
            db.session.add(EntryEmbedding(entry_id=e.id, embedding=v.astype('float32').tobytes(),
                                          text_hash=memory._text_hash(t)))
        db.session.commit()
        memory._invalidate_embedding_cache()

        # Monthly summaries, as the background job would write them (plainer).
        by_month: dict[str, list] = {}
        for d in days:
            by_month.setdefault(d.date.strftime('%Y-%m'), []).append(d)
        for key, ds in by_month.items():
            themes: dict[str, int] = {}
            for d in ds:
                for t in d.themes:
                    themes[t] = themes.get(t, 0) + 1
            top = ', '.join(f'{t} ({n})' for t, n in sorted(themes.items(), key=lambda kv: -kv[1])[:3])
            runs = sum('бег' in d.activities for d in ds)
            rain = sum(d.weather == 'Rain' for d in ds)
            avg = sum(d.rating for d in ds) / len(ds)
            db.session.add(PeriodSummary(
                period_type='month', period_key=key, avg_rating=round(avg, 2), entry_count=len(ds),
                summary=f'Средняя оценка {avg:.1f}. Чаще всего темы: {top}. '
                        f'Бег {runs} раз, дождливых дней {rain}.'))
        db.session.add(SyncMeta(key='answers_eval_built', value=stamp))
        db.session.commit()


# ── dates in text ─────────────────────────────────────────────

_MONTH_RE = '|'.join(MONTHS_GEN[1:])


def cited_dates(text: str) -> list[tuple[int | None, int, int]]:
    """(year or None, month, day) for every specific date in `text`."""
    out = []
    for y, m, d in re.findall(r'\b(20\d\d)-(\d\d)-(\d\d)\b', text):
        out.append((int(y), int(m), int(d)))
    for d, m, y in re.findall(r'\b(\d{1,2})\.(\d{2})\.(20\d\d)\b', text):
        out.append((int(y), int(m), int(d)))
    for d, mon, y in re.findall(r'\b(\d{1,2})\s+(' + _MONTH_RE + r')(?:\s+(20\d\d))?', text, re.I):
        out.append((int(y) if y else None, MONTHS_GEN.index(mon.lower()), int(d)))
    return out


def date_alternatives(d: date) -> str:
    """A regex for `d` written any of the usual ways."""
    return (rf'{d.isoformat()}|{d.day:02d}\.{d.month:02d}|\b{d.day}\s+{MONTHS_GEN[d.month]}')


def ungrounded(text: str, context: str) -> list[str]:
    """Dates the answer cites that the model was never shown."""
    shown = cited_dates(context)
    full = {(y, m, d) for y, m, d in shown if y}
    day_month = {(m, d) for _, m, d in shown}
    bad = []
    for y, m, d in cited_dates(text):
        ok = (y, m, d) in full if y else (m, d) in day_month
        if not ok:
            bad.append(f'{y or "?"}-{m:02d}-{d:02d}')
    return bad


# ── questions ─────────────────────────────────────────────────

def questions(days):
    today = date.today()
    shift = today - assistant_diary.TODAY
    masha_first = assistant_diary.MASHA_FIRST + shift
    last_move = max(d.date for d in days if 'переезд' in d.themes)
    worst = min(d.rating for d in days)
    worst_days = [d.date for d in days if d.rating == worst]
    monday = today - timedelta(days=today.weekday())
    last_week = [d for d in days if monday - timedelta(days=7) <= d.date < monday]
    any_of = lambda ds: '|'.join(date_alternatives(x) for x in ds)  # noqa: E731
    return [
        # why / what changed
        {'q': 'Почему мне последнее время хуже?', 'facts': [r'бег|пробеж']},
        {'q': 'Что изменилось в моей жизни за последний месяц?', 'facts': [r'бег|пробеж']},
        # rhythms
        {'q': 'В какой день недели мне хуже всего?', 'facts': [r'понедельник']},
        {'q': 'Есть ли у меня сезонные спады?', 'facts': [r'феврал']},
        # drivers
        {'q': 'Что мне помогает чувствовать себя лучше?', 'facts': [r'бег|пробеж']},
        {'q': 'Чем мои хорошие дни отличаются от плохих?',
         'facts': [r'бег|пробеж', r'дожд|понедельник|дедлайн']},
        {'q': 'Влияет ли на меня погода?', 'facts': [r'дожд']},
        # people
        {'q': 'Как у меня отношения с Сергеем?', 'facts': [r'Серге', r'придир|негатив|напряж|конфликт|хуже|раздраж']},
        {'q': 'Что я писал про Машу?', 'facts': [r'Маш', r'гуля|прогул|тепл|разговор|говорили']},
        {'q': 'Когда я впервые упомянул Машу?', 'facts': [date_alternatives(masha_first)]},
        {'q': 'Кто на меня хорошо влияет?', 'facts': [r'Маш']},
        # themes and topics
        {'q': 'О чём я чаще всего пишу?', 'facts': [r'работ']},
        {'q': 'Что меня больше всего беспокоит по моим записям?', 'facts': [r'дедлайн|работ']},
        {'q': 'Когда я последний раз писал про переезд?', 'facts': [r'переезд', date_alternatives(last_move)]},
        {'q': 'Как часто я думаю о переезде?', 'facts': [r'переезд']},
        # periods
        {'q': 'Как прошла прошлая неделя?', 'facts': [any_of(d.date for d in last_week)]},
        {'q': 'Как прошёл мой февраль?', 'facts': [r'тяжел|тяжёл|спад|плох|низк|сил|сер']},
        {'q': 'Сравни этот месяц с прошлым', 'facts': [r'\d[.,]\d']},
        {'q': 'Подведи итоги лета', 'facts': [r'работ|бег|Маш|дожд']},
        {'q': 'Что было в дождливые дни на прошлой неделе?',
         'facts': [r'дожд', any_of(d.date for d in last_week if d.weather == 'Rain') or r'.']},
        # progress and meta
        {'q': 'Я стал реже бегать?', 'facts': [r'бег|пробеж', r'перестал|не бега|прекрат|пропал|реже|нет']},
        {'q': 'Сколько я уже веду дневник?', 'facts': [r'730|два года|2 года|двух лет|24 месяц|с 20\d\d']},
        {'q': 'Когда был мой самый худший день?', 'facts': [any_of(worst_days)]},
        # no diary needed, or not in that way
        {'q': 'Мне сегодня очень тревожно, не могу ни на чём сосредоточиться', 'facts': []},
        {'q': 'Привет!', 'facts': [], 'max_len': 500},
        # nothing on the exact day: the answer should say so, and use the days around it
        {'q': 'Что было позавчера?',
         'facts': [r'не (писал|было записи|нашл|нашёл|нашел|нахож|вижу)|нет запис|записи нет|пропуст|не заполн',
                   any_of(d.date for d in days
                          if 0 < abs((d.date - (today - timedelta(days=SKIPPED_DAYS_AGO))).days) <= 7)]},
        # nobody by that name: the answer should say so, not invent them
        {'q': 'Что я писал про Аркадия?',
         'facts': [r'не (упомина|нашл|нашёл|нашел|нахож|вижу|встреча|писал)|нет (упоминаний|записей)|ни разу']},
    ]


# ── running ───────────────────────────────────────────────────

def load_llm():
    from llama_cpp import Llama
    gguf = sorted((ROOT / 'app' / 'modules' / 'assistant' / 'models').glob('*.gguf'))
    print(f'Loading {gguf[0].name} …', flush=True)
    # The app's context size, so the prompt budget is the app's too.
    return Llama(model_path=str(gguf[0]), n_ctx=6144, n_gpu_layers=-1, verbose=False, seed=7)


def answer(llm, question: str, mode: str) -> dict:
    from app.modules.assistant import routes
    from app.modules.assistant.llm_text import strip_think
    t0 = time.perf_counter()
    gen = routes._gather_evidence(llm, question, [], mode=mode)
    calls = []
    try:
        while True:
            calls.append(next(gen))
    except StopIteration as stop:
        scenario, outputs = stop.value
    system = routes._grounded_system(llm, question, scenario, outputs)
    tone_line, tone = routes._tone_hint(question)
    messages = routes._trim_messages_to_fit(llm, [
        {'role': 'system', 'content': system + tone_line},
        {'role': 'user', 'content': question}])
    t1 = time.perf_counter()
    r = llm.create_chat_completion(messages=messages, max_tokens=700, seed=7,
                                   temperature=routes._reply_temperature(tone, False))
    t2 = time.perf_counter()
    text = strip_think(r['choices'][0]['message']['content'] or '').strip()
    return {'text': text, 'calls': calls, 'system': system,
            'scenario': scenario.scenario if scenario else None,
            'prep_s': t1 - t0, 'gen_s': t2 - t1,
            'tokens': r.get('usage', {}).get('completion_tokens'),
            'prompt_tokens': r.get('usage', {}).get('prompt_tokens')}


def check(item: dict, res: dict) -> dict:
    text = res['text']
    missed = [f for f in item['facts'] if not re.search(f, text, re.I)]
    bad_dates = ungrounded(text, res['system'])
    too_long = 'max_len' in item and len(text) > item['max_len']
    return {'facts_ok': not missed, 'missed': missed, 'bad_dates': bad_dates,
            'dates': len(cited_dates(text)), 'too_long': too_long,
            'dashes': text.count('—'), 'chars': len(text)}


def report(name, rows):
    n = len(rows)
    with_facts = [r for r in rows if r['item']['facts']]
    facts = sum(r['check']['facts_ok'] for r in with_facts)
    dates = sum(r['check']['dates'] for r in rows)
    bad = sum(len(r['check']['bad_dates']) for r in rows)
    print(f'\n== {name} ({n} questions)')
    print(f'  planted facts in the answer  {facts}/{len(with_facts)}')
    print(f'  dates cited {dates}, not in what the model was shown {bad}')
    print(f'  answers with long dashes {sum(r["check"]["dashes"] > 0 for r in rows)}, '
          f'too long {sum(r["check"]["too_long"] for r in rows)}')
    print(f'  chars p50 {statistics.median(r["check"]["chars"] for r in rows):.0f}; '
          f'prep p50 {statistics.median(r["res"]["prep_s"] for r in rows):.1f}s, '
          f'answer p50 {statistics.median(r["res"]["gen_s"] for r in rows):.1f}s; '
          f'prompt tokens p50 {statistics.median(r["res"]["prompt_tokens"] or 0 for r in rows):.0f}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--router', choices=('both', 'legacy', 'scenario'), default='both')
    ap.add_argument('--only', type=int, default=0, help='first N questions')
    ap.add_argument('--match', default='', help='only questions matching this regex')
    ap.add_argument('--db', default=str(ROOT / 'tools' / 'assistant_eval' / '.answers_diary.db'))
    ap.add_argument('--out', default='', help='write every answer to this Markdown file')
    args = ap.parse_args()

    # The router eval next to this file (a bare `import run` finds the app's
    # own run.py at the repo root first).
    import importlib.util
    spec = importlib.util.spec_from_file_location('router_eval', Path(__file__).with_name('run.py'))
    router_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(router_eval)
    if router_eval.app_model_state() == 'loaded':
        sys.exit('index.life has the model loaded; close it first.')

    from flask import Flask
    from app import db
    from app import models as _models  # noqa: F401 (registers the tables)
    flask_app = Flask('answers_eval')
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{args.db}'
    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(flask_app)

    days = diary_days()
    build_db(flask_app, days)
    items = questions(days)
    if args.match:
        items = [i for i in items if re.search(args.match, i['q'], re.I)]
    if args.only:
        items = items[:args.only]
    modes = ['legacy', 'scenario'] if args.router == 'both' else [args.router]

    llm = load_llm()
    rows = {m: [] for m in modes}
    with flask_app.app_context():
        for i, item in enumerate(items, 1):
            for m in modes:
                res = answer(llm, item['q'], m)
                chk = check(item, res)
                rows[m].append({'item': item, 'res': res, 'check': chk})
                print(f'[{i:2}/{len(items)}] {m[:3]} {"ok" if chk["facts_ok"] else "--"} '
                      f'dates {chk["dates"]}/{len(chk["bad_dates"])} bad '
                      f'{res["gen_s"]:.0f}s  {item["q"][:50]}', flush=True)

    for m in modes:
        report(m, rows[m])

    if args.out:
        lines = ['# Answer eval', '']
        for i, item in enumerate(items):
            lines += [f'## {item["q"]}', '']
            for m in modes:
                r = rows[m][i]
                c = r['check']
                lines += [f'**{m}** ({r["res"]["scenario"] or "-"}; '
                          f'{", ".join(x["tool"] for x in r["res"]["calls"]) or "no tools"}; '
                          f'facts {"ok" if c["facts_ok"] else "missed " + str(c["missed"])}; '
                          f'bad dates {c["bad_dates"] or "none"})', '', r['res']['text'], '']
        Path(args.out).write_text('\n'.join(lines), encoding='utf-8')
        print(f'\nWrote {args.out}')


if __name__ == '__main__':
    main()
