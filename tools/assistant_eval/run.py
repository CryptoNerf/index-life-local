"""Router eval: the old tool router against the scenario router.

Runs every labelled question in cases.jsonl through both routers with the
real local model, turns their output into tool calls, and checks the calls
against what each question needs. No diary is read: the questions are
synthetic, and the tools are not executed, only chosen.

    venv/bin/python tools/assistant_eval/run.py [--limit N] [--router both|legacy|scenario]
                                                [--out results.json]

Metrics
- needs coverage: of the data kinds a question needs (a trend, a period, a
  person...), how many the chosen calls fetch. "chat" has no tool yet and
  is counted apart. "query" means an entries_query carrying every day
  filter the question names ("плохие дни", "по понедельникам", "в дождь").
- precise periods: of the covered period needs, how many calls fetch that
  period rather than a whole month or year around it.
- quiet: questions that need nothing (a greeting, "что ты умеешь?") and got
  no calls.
- extra calls: calls that fetch nothing the question needs.
- scenario accuracy (scenario router only): the gold scenario, or one of the
  acceptable alternatives.
- latency of the routing call, p50 and p95.

Close the app's chat first: two copies of the model do not fit in 16 GB.
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.modules import _add_local_modules_site_packages  # noqa: E402
_add_local_modules_site_packages()

from app import people_match  # noqa: E402
from app.modules.assistant import routes, scenarios  # noqa: E402
from app.modules.assistant.tools import _parse_period_spec  # noqa: E402

TODAY = date(2026, 9, 27)
KNOWN_PEOPLE = ['Маша', 'Сергей', 'Лёша', 'Мари', 'Дима', 'Илья', 'Лена']
KNOWN_ACTIVITIES = ['бег', 'спорт', 'работа', 'прогулка', 'чтение', 'учёба']
GAP_NEEDS = {'chat'}
TOOLS_FOR_NEED = {
    'trend': {'mood_trend', 'what_changed'},
    'compare': {'compare_periods', 'what_changed'},
    'activities': {'activity_impact', 'contrast_days'},
    'extremes': {'best_worst_days', 'contrast_days'},
    'people': {'people_overview'},
    'weather': {'weather_impact'},
    'stats': {'diary_stats'},
    'rhythm': {'rhythms'},
    'themes': {'themes'},
}


def load_llm():
    from llama_cpp import Llama
    gguf = sorted((ROOT / 'app' / 'modules' / 'assistant' / 'models').glob('*.gguf'))
    if not gguf:
        sys.exit('No .gguf model in app/modules/assistant/models')
    print(f'Loading {gguf[0].name} …', flush=True)
    return Llama(model_path=str(gguf[0]), n_ctx=4096, n_gpu_layers=-1, verbose=False)


def app_model_state() -> str:
    """'none' (app closed), 'idle' (open, model not loaded) or 'loaded'."""
    try:
        pids = subprocess.run(['pgrep', '-f', 'index.life.app/Contents/MacOS'],
                              capture_output=True, text=True).stdout.split()
    except OSError:
        return 'none'
    if not pids:
        return 'none'
    for pid in pids:
        files = subprocess.run(['lsof', '-p', pid], capture_output=True, text=True).stdout
        if '.gguf' in files:
            return 'loaded'
    return 'idle'


# ── what a call fetches ───────────────────────────────────────

def call_range(call):
    """(start, end) of the dates a period call fetches, or None."""
    args = call.get('args') or {}
    if call['tool'] == 'entries_query':
        if not (args.get('start') or args.get('end')):
            return None
        a = date.fromisoformat(args.get('start') or '2000-01-01')
        b = date.fromisoformat(args.get('end') or TODAY.isoformat())
        return (a, b)
    if call['tool'] == 'period_entries':
        if args.get('start'):
            spec = _parse_period_spec(f"{args['start']}..{args.get('end') or args['start']}")
        elif args.get('year') is not None:
            try:
                y = int(args['year'])
                m = args.get('month')
                spec = _parse_period_spec(f'{y}-{int(m):02d}' if m else str(y))
            except (TypeError, ValueError):
                spec = None
        else:
            spec = None
        return (spec[1], spec[2]) if spec else None
    if call['tool'] == 'on_this_day':
        d = TODAY.replace(year=TODAY.year - 1)
        return (d, d)
    return None


def expected_range(case):
    p = (case.get('slots') or {}).get('period')
    if not p or not p.get('start'):
        return None
    a = date.fromisoformat(p['start'])
    if p.get('end'):
        b = date.fromisoformat(p['end'])
    else:
        # Labels give the start; the end follows from the kind.
        kind = p.get('kind')
        if kind == 'month':
            b = _parse_period_spec(f'{a.year}-{a.month:02d}')[2]
        elif kind == 'year':
            b = date(a.year, 12, 31)
        elif kind == 'week':
            b = a + timedelta(days=6)
        elif kind == 'season':
            b = _parse_period_spec(f'{a.year + (a.month + 2 > 12)}-{(a.month + 1) % 12 + 1:02d}')[2]
        elif kind == 'recent':
            b = TODAY
        else:
            b = a
    return (a, min(b, TODAY))


def _same_person(a: str, b: str) -> bool:
    a, b = a.strip().lower().replace('ё', 'е'), b.strip().lower().replace('ё', 'е')
    if a == b:
        return True
    forms_b = {f.replace('ё', 'е') for f in people_match.name_forms(b)} | {b}
    return a in forms_b or people_match._lemma(a) == people_match._lemma(b)


def covers(need, call, case):
    tool = call['tool']
    args = call.get('args') or {}
    if need in TOOLS_FOR_NEED:
        return tool in TOOLS_FOR_NEED[need]
    if need == 'topic':
        return tool == 'search_topic' or (tool == 'entries_query' and bool(args.get('word')))
    if need.startswith('person:'):
        if tool in ('person_history', 'person_deep'):
            return _same_person(str(args.get('name') or ''), need[7:])
        return tool == 'entries_query' and _same_person(str(args.get('person') or ''), need[7:])
    if need == 'query':
        want = (case.get('slots') or {}).get('filters') or {}
        return tool == 'entries_query' and all(args.get(k) == v for k, v in want.items())
    if need == 'anniversary':
        r = call_range(call)
        d = TODAY.replace(year=TODAY.year - 1)
        return r is not None and r[0] <= d <= r[1]
    if need == 'period':
        r = call_range(call)
        if r is None:
            return False
        exp = expected_range(case)
        return exp is None or (r[0] <= exp[1] and exp[0] <= r[1])
    return False


def precise(call, case) -> bool:
    """The call fetches the labelled period, give or take three days."""
    r, exp = call_range(call), expected_range(case)
    if r is None or exp is None:
        return False
    slack = timedelta(days=3)
    return exp[0] - slack <= r[0] and r[1] <= exp[1] + slack


def score(case, calls):
    needs = case['needs']
    coverable = [n for n in needs if n not in GAP_NEEDS]
    covered = [n for n in coverable if any(covers(n, c, case) for c in calls)]
    useful = [c for c in calls if any(covers(n, c, case) for n in coverable)]
    period_calls = [c for c in calls if covers('period', c, case)] if 'period' in coverable else []
    return {
        'coverable': len(coverable),
        'covered': len(covered),
        'missed': [n for n in coverable if n not in covered],
        'gap': [n for n in needs if n in GAP_NEEDS],
        'extra': len(calls) - len(useful),
        'quiet_case': not needs,
        'quiet_ok': (not needs) and not calls,
        'period_labelled': 'period' in coverable and expected_range(case) is not None,
        'period_precise': any(precise(c, case) for c in period_calls),
    }


# ── routers ───────────────────────────────────────────────────

def run_legacy(llm, case):
    # The prompt reads the clock; pin it so the labels' dates hold.
    t0 = time.perf_counter()
    calls = routes._route_to_tools(llm, case['q'], case.get('prior'))
    return calls, time.perf_counter() - t0, None


def run_scenario(llm, case):
    t0 = time.perf_counter()
    prior = [case['prior']] if case.get('prior') else []
    d = scenarios.route(llm, case['q'], TODAY, prior_messages=prior,
                        known_people=KNOWN_PEOPLE, known_activities=KNOWN_ACTIVITIES)
    calls = scenarios.plan(d, case['q'], TODAY)
    return calls, time.perf_counter() - t0, d


def pct(a, b):
    return f'{100 * a / b:5.1f}%' if b else '   n/a'


def quantile(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def report(name, rows):
    cov = sum(r['score']['covered'] for r in rows)
    need = sum(r['score']['coverable'] for r in rows)
    full = sum(1 for r in rows if r['score']['covered'] == r['score']['coverable'])
    quiet_n = sum(1 for r in rows if r['score']['quiet_case'])
    quiet_ok = sum(1 for r in rows if r['score']['quiet_ok'])
    per_n = sum(1 for r in rows if r['score']['period_labelled'])
    per_ok = sum(1 for r in rows if r['score']['period_labelled'] and r['score']['period_precise'])
    extra = sum(r['score']['extra'] for r in rows)
    calls = sum(len(r['calls']) for r in rows)
    lat = [r['seconds'] for r in rows]
    print(f'\n== {name} ({len(rows)} questions)')
    print(f'  needs coverage   {pct(cov, need)}  ({cov}/{need})')
    print(f'  fully covered    {pct(full, len(rows))}  ({full}/{len(rows)} questions)')
    print(f'  precise periods  {pct(per_ok, per_n)}  ({per_ok}/{per_n})')
    print(f'  quiet when idle  {pct(quiet_ok, quiet_n)}  ({quiet_ok}/{quiet_n})')
    print(f'  calls / question {calls / max(1, len(rows)):.2f}, extra {extra}')
    print(f'  latency          p50 {quantile(lat, .5):.2f}s  p95 {quantile(lat, .95):.2f}s  '
          f'mean {statistics.mean(lat) if lat else 0:.2f}s')
    if rows and rows[0].get('decision') is not None:
        ok = sum(1 for r in rows if r['decision']['scenario'] == r['case']['scenario']
                 or r['decision']['scenario'] in (r['case'].get('alt') or []))
        strict = sum(1 for r in rows if r['decision']['scenario'] == r['case']['scenario'])
        src = {}
        for r in rows:
            src[r['decision']['source']] = src.get(r['decision']['source'], 0) + 1
        print(f'  scenario         {pct(ok, len(rows))} with alternatives, {pct(strict, len(rows))} strict; '
              f'sources {src}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', default=str(Path(__file__).with_name('cases.jsonl')))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--router', choices=('both', 'legacy', 'scenario'), default='both')
    ap.add_argument('--out', default='')
    ap.add_argument('--force', action='store_true', help='run even if the app has the model loaded')
    args = ap.parse_args()

    state = app_model_state()
    if state == 'loaded' and not args.force:
        sys.exit('index.life has the model loaded; close it first (two models do not fit in memory).')
    if state == 'idle':
        print('index.life is open without the model; do not open its chat during the run.')

    cases = [json.loads(line) for line in open(args.cases, encoding='utf-8') if line.strip()]
    if args.limit:
        cases = cases[:args.limit]

    # Pin the legacy prompt's date; the scenario router takes TODAY directly.
    routes._ROUTER_PROMPT = routes._ROUTER_PROMPT.replace('{today}', TODAY.isoformat())

    llm = load_llm()
    llm.create_chat_completion(messages=[{'role': 'user', 'content': 'привет'}], max_tokens=1)

    names = ['legacy', 'scenario'] if args.router == 'both' else [args.router]
    rows = {n: [] for n in names}
    for i, case in enumerate(cases, 1):
        for n in names:
            fn = run_legacy if n == 'legacy' else run_scenario
            calls, secs, d = fn(llm, case)
            rows[n].append({'case': case, 'calls': calls, 'seconds': secs,
                            'decision': d.as_dict() if d else None,
                            'score': score(case, calls)})
        line = f'[{i:3}/{len(cases)}] {case["q"][:50]:50}'
        for n in names:
            r = rows[n][-1]
            mark = 'ok' if r['score']['covered'] == r['score']['coverable'] and not (
                r['score']['quiet_case'] and not r['score']['quiet_ok']) else '--'
            extra = f" {r['decision']['scenario']}" if r['decision'] else ''
            line += f'  {n[:3]} {mark} {r["seconds"]:.1f}s{extra}'
        print(line, flush=True)

    for n in names:
        report(n, rows[n])

    if 'scenario' in rows:
        print('\nScenario router misses (gold → predicted):')
        for r in rows['scenario']:
            d, c = r['decision'], r['case']
            if d['scenario'] != c['scenario'] and d['scenario'] not in (c.get('alt') or []):
                print(f"  {c['scenario']:12} → {d['scenario']:12} {c['q']}")
        print('\nScenario router uncovered needs:')
        for r in rows['scenario']:
            if r['score']['missed']:
                print(f"  {r['score']['missed']} {r['case']['q']}  calls={[c['tool'] for c in r['calls']]}")
    if 'legacy' in rows:
        print('\nLegacy router uncovered needs:')
        for r in rows['legacy']:
            if r['score']['missed'] or (r['score']['quiet_case'] and not r['score']['quiet_ok']):
                print(f"  {r['score']['missed'] or 'not quiet'} {r['case']['q']}  "
                      f"calls={[(c['tool'], c['args']) for c in r['calls']]}")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str),
                                  encoding='utf-8')
        print(f'\nWrote {args.out}')


if __name__ == '__main__':
    main()
