"""A/B quality check: combined extraction vs the three standalone calls.

Runs SYNTHETIC Russian diary entries (no real diary data) through both
paths with the real local model and prints the results side by side, plus
wall-time totals. Use it to judge whether the combined prompt keeps
extraction quality before trusting it (ASSISTANT_COMBINED_EXTRACT=0
disables the combined path in the app).

Run from the repo root:  venv/bin/python tools/ab_extract.py [--entries N]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# llama-cpp-python lives in modules_venv (same trick create_app uses).
from app.modules import _add_local_modules_site_packages  # noqa: E402
_add_local_modules_site_packages()

from app.modules.assistant.prompts import (  # noqa: E402
    COMBINED_EXTRACT_PROMPT, SUMMARY_PROMPT, PEOPLE_PROMPT, ACTIVITIES_PROMPT,
)
from app.modules.assistant.memory import (  # noqa: E402
    _parse_combined_response, _parse_summary_response,
    _parse_people_response, _parse_activities_response,
)

# Synthetic entries covering the tricky extraction cases: role+name, rare
# names that must not be "russified", declensions, per-person tone vs day
# rating, animals/pronouns to ignore, and an emotions-only entry that must
# yield empty people/activities.
ENTRIES = [
    ('2026-06-01', 7,
     'Утром пробежка в парке, потом два часа писал код. Вечером звонила мама, '
     'долго разговаривали — стало теплее на душе. Кот опять разбил чашку.'),
    ('2026-06-02', 3,
     'Тяжёлый день. Поссорился с Димой из-за денег, до сих пор неприятно. '
     'Вечером зашла тётя Лена, принесла пирог — немного отвлёкся. '
     'Читал перед сном.'),
    ('2026-06-03', 8,
     'Гуляли с Мари по набережной, потом кино. Она рассказывала про свою '
     'новую работу. Отличный день!'),
    ('2026-06-04', 4,
     'Весь день тревога и усталость, ничего не делал. Мысли по кругу. '
     'Даже читать не смог.'),
    ('2026-06-05', 6,
     'Работа, потом спортзал. Начальник похвалил отчёт — приятно. '
     'Вечером готовил ужин, звонил брату Илье, он опять жаловался на всё '
     'подряд, устал от этого.'),
]


def load_llm():
    from llama_cpp import Llama
    model_dir = ROOT / 'app' / 'modules' / 'assistant' / 'models'
    gguf = sorted(model_dir.glob('*.gguf'))
    if not gguf:
        sys.exit(f'No .gguf model in {model_dir}')
    print(f'Loading {gguf[0].name} …', flush=True)
    return Llama(model_path=str(gguf[0]), n_ctx=4096, n_gpu_layers=-1,
                 verbose=False)


class Meter:
    """Accumulates tokens + wall time per path, and counts <think> leaks."""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.seconds = 0.0
        self.thinks = 0


def ask(llm, prompt, max_tokens, temperature, meter):
    t0 = time.time()
    r = llm.create_chat_completion(
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=max_tokens, temperature=temperature)
    meter.seconds += time.time() - t0
    usage = r.get('usage') or {}
    meter.prompt_tokens += usage.get('prompt_tokens', 0)
    meter.completion_tokens += usage.get('completion_tokens', 0)
    text = r['choices'][0]['message']['content'].strip()
    if '<think>' in text:
        meter.thinks += 1
    return text


def run_combined(llm, date, rating, note, meter):
    t0 = time.time()
    text = ask(llm, COMBINED_EXTRACT_PROMPT.format(
        date=date, rating=rating, note=note), 700, 0.2, meter)
    parsed = _parse_combined_response(text)
    return parsed, time.time() - t0


def run_individual(llm, date, rating, note, meter):
    t0 = time.time()
    s_text = ask(llm, SUMMARY_PROMPT.format(
        date=date, rating=rating, note=note), 320, 0.3, meter)
    summary, themes = _parse_summary_response(s_text)
    p_text = ask(llm, PEOPLE_PROMPT.format(
        date=date, rating=rating, note=note), 400, 0.2, meter)
    people = _parse_people_response(p_text)
    a_text = ask(llm, ACTIVITIES_PROMPT.format(
        date=date, rating=rating, note=note), 200, 0.2, meter)
    activities = _parse_activities_response(a_text)
    return ({'summary': summary, 'themes': themes,
             'people': people, 'activities': activities},
            time.time() - t0)


def fmt(parsed):
    if parsed is None:
        return '  !! PARSE FAILED (would fall back)'
    people = ', '.join(f"{p['mention']}({p['tone'][:3]})" for p in parsed['people']) or '—'
    acts = ', '.join(parsed['activities']) or '—'
    themes = ', '.join(parsed['themes']) or '—'
    return (f"  summary : {parsed['summary']}\n"
            f"  themes  : {themes}\n"
            f"  people  : {people}\n"
            f"  acts    : {acts}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entries', type=int, default=len(ENTRIES))
    args = ap.parse_args()

    llm = load_llm()
    meter_a, meter_b = Meter(), Meter()
    fails_a = 0
    for i, (date, rating, note) in enumerate(ENTRIES[:args.entries]):
        print(f'\n═══ {date} ({rating}/10): {note[:60]}…')
        # Alternate the order so llama.cpp's prefix-cache reuse between
        # consecutive calls can't systematically favor one path.
        if i % 2 == 0:
            combined, ta = run_combined(llm, date, rating, note, meter_a)
            individual, tb = run_individual(llm, date, rating, note, meter_b)
        else:
            individual, tb = run_individual(llm, date, rating, note, meter_b)
            combined, ta = run_combined(llm, date, rating, note, meter_a)
        if combined is None:
            fails_a += 1
        print(f'A · combined   ({ta:5.1f}s)\n{fmt(combined)}')
        print(f'B · individual ({tb:5.1f}s)\n{fmt(individual)}')

    n = args.entries
    print('\n═══ TOTALS ═══')
    for label, m in (('combined  ', meter_a), ('individual', meter_b)):
        print(f'{label}: {m.seconds:6.1f}s ({m.seconds / n:.1f}s/entry) · '
              f'prompt {m.prompt_tokens} tok · completion {m.completion_tokens} tok · '
              f'<think> leaks: {m.thinks}')
    print(f'parse fails (combined): {fails_a}/{n}')
    print(f'speedup   : ×{meter_b.seconds / max(meter_a.seconds, 0.01):.2f}')
    saved_prompt = meter_b.prompt_tokens - meter_a.prompt_tokens
    extra_completion = meter_a.completion_tokens - meter_b.completion_tokens
    print(f'prompt tokens saved by combining : {saved_prompt}')
    print(f'completion tokens added by JSON  : {extra_completion}')


if __name__ == '__main__':
    main()
