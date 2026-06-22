# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""AI Psychologist chat routes with streaming and multi-layer memory."""
import json
import logging
import os
import sys
import platform
import shutil
import subprocess
import ctypes
import threading
from pathlib import Path
from flask import render_template, request, Response, stream_with_context, jsonify, current_app
from app import db
from app.models import ChatMessage, UserPsychProfile, MoodEntry
from .prompts import (
    CRISIS_KEYWORDS, CRISIS_RESPONSE, SYSTEM_PROMPT,
    DIARY_ACCESS_PRESENT, DIARY_ACCESS_EMPTY,
)
from .llm_text import (
    strip_think as _strip_think,
    count_tokens as _count_tokens,
    truncate_to_tokens as _truncate_to_tokens,  # default keep='head' — matches prior behaviour
)
from . import bp

log = logging.getLogger(__name__)

# Ensure CUDA runtime DLLs are findable on Windows (not needed for Vulkan/CPU)
if os.name == 'nt':
    try:
        _cuda_path = os.environ.get('CUDA_PATH', '')
        if not _cuda_path:
            _cuda_base = Path(r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA')
            if _cuda_base.is_dir():
                _versions = sorted(_cuda_base.iterdir(), reverse=True)
                if _versions:
                    _cuda_path = str(_versions[0])
        if _cuda_path:
            _cuda_bin = Path(_cuda_path) / 'bin' / 'x64'
            if _cuda_bin.is_dir() and str(_cuda_bin) not in os.environ.get('PATH', ''):
                os.environ['PATH'] = str(_cuda_bin) + ';' + os.environ.get('PATH', '')
    except Exception:
        pass  # CUDA not available; Vulkan/CPU will work without it

_llm = None
_llm_n_ctx = None
_llm_lock = threading.Lock()
_llm_inference_lock = threading.Lock()  # Protects all create_chat_completion calls


# ── Tool routing for the AI psychologist chat ─────────────────────────
# A small extra LLM call decides whether the user's message needs a
# specific data lookup (person history, period, topic search) before
# the main reply is generated. The result is appended to the system
# prompt as additional grounded context so the model doesn't have to
# rely only on what semantic-search happened to surface.

_VALID_TOOLS = (
    'person_history', 'period_entries', 'search_topic',
    'mood_trend', 'compare_periods',
    'activity_impact', 'people_overview', 'best_worst_days',
    'diary_stats', 'on_this_day', 'weather_impact',
)

_ROUTER_PROMPT = """Ты — маршрутизатор для AI-психолога. Реши, какие данные из дневника нужно подтянуть, чтобы ответить на текущее сообщение пользователя.

Сегодняшняя дата: {today}. Используй её для расчёта относительных периодов ("3 месяца назад", "на прошлой неделе" и т.д.).

{prior_context}Текущее сообщение:
{message}

Доступные инструменты:
- person_history — все записи, где упомянут конкретный человек (имя или роль). Для вопросов про конкретного человека.
- period_entries — все записи за указанный период (год обязателен, месяц опционален). Для вопросов о времени: "этот месяц", "март 2025".
- search_topic — семантический поиск по теме/чувству/паттерну. Для абстрактных вопросов.
- mood_trend — динамика настроения за последние N дней. Для вопросов "как дела", "что в последнее время", "стало хуже/лучше".
- compare_periods — сравнение двух периодов. Для вопросов "прошлый месяц был лучше?".
- activity_impact — какие занятия/активности связаны с ростом или падением настроения. Для "что мне помогает?", "от чего мне лучше/хуже?", "что меня радует/выматывает?".
- people_overview — обзор ВСЕХ людей в дневнике с тоном упоминаний (не один человек). Для "кто на меня хорошо/плохо влияет?", "расскажи про людей вокруг меня".
- best_worst_days — лучшие и худшие дни по оценке. Для "когда мне было лучше/хуже всего?", "мой лучший день".
- diary_stats — общая статистика: сколько записей, как давно ведётся дневник, серии подряд. Для "сколько я веду дневник?", "какая у меня статистика", "сколько я уже записал".
- on_this_day — записи за сегодняшнюю дату в прошлые годы. Для "что было год назад?", "что у меня было в этот день раньше?".
- weather_impact — связь настроения с погодой (температура, тип погоды). Для "влияет ли на меня погода?", "в дождь мне хуже?", "зависит ли настроение от погоды?".
- none — данных из дневника не нужно. Для приветствий, благодарностей, мета-вопросов.

Можно выбрать от ОДНОГО до ТРЁХ инструментов, если вопрос составной (например, и про человека, и про период). Не больше трёх.

Ответь СТРОГО JSON-массивом из 0–3 элементов, без markdown, без пояснений. Примеры:
- "Что я писал про маму в марте?" → [{{"tool": "person_history", "args": {{"name": "мама"}}}}, {{"tool": "period_entries", "args": {{"year": 2025, "month": 3}}}}]
- "Как я последнее время?" → [{{"tool": "mood_trend", "args": {{"window_days": 30}}}}]
- "Что у меня с тревожностью?" → [{{"tool": "search_topic", "args": {{"query": "тревожность стресс беспокойство"}}}}]
- "Что мне помогает чувствовать себя лучше?" → [{{"tool": "activity_impact", "args": {{}}}}]
- "Кто на меня плохо влияет?" → [{{"tool": "people_overview", "args": {{}}}}]
- "Когда мне было хуже всего?" → [{{"tool": "best_worst_days", "args": {{"top_n": 5}}}}]
- "Сколько я уже веду дневник?" → [{{"tool": "diary_stats", "args": {{}}}}]
- "Что у меня было в этот день год назад?" → [{{"tool": "on_this_day", "args": {{}}}}]
- "Влияет ли на меня погода?" → [{{"tool": "weather_impact", "args": {{}}}}]
- "Привет" → []
- "Этот месяц лучше прошлого?" → [{{"tool": "compare_periods", "args": {{"period_a": "2025-02", "period_b": "2025-03"}}}}]
- "Что у меня с работой?" → [{{"tool": "search_topic", "args": {{"query": "работа"}}}}]"""


def _route_to_tools(llm, user_message: str,
                    prior_user_message: str | None = None) -> list[dict]:
    """Decide which tools (0-2) the user's message needs.

    `prior_user_message` is the user's previous turn — gives the router
    multi-turn context (so "расскажи подробнее" doesn't lose the topic
    from the previous question).

    Returns a list of {tool, args}; empty list when no tools are warranted
    or on parse failure (chat continues without extra grounding).
    """
    msg = user_message.strip()
    # Trivial-length messages almost never benefit from tool calls.
    if len(msg) < 14:
        return []

    prior_context = ''
    if prior_user_message:
        clean = prior_user_message.strip()
        if clean and len(clean) >= 4:
            # Cap to avoid blowing up router prompt
            if len(clean) > 400:
                clean = clean[:400] + '...'
            prior_context = f'Предыдущее сообщение пользователя (для контекста):\n{clean}\n\n'

    from datetime import datetime
    prompt = _ROUTER_PROMPT.format(
        today=datetime.now().strftime('%Y-%m-%d'),
        prior_context=prior_context,
        message=msg,
    )
    try:
        with _llm_inference_lock:
            result = llm.create_chat_completion(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=200,
                temperature=0.1,
            )
        text = result['choices'][0]['message']['content'].strip()
        text = _strip_think(text)
        # Find the JSON array — model occasionally adds preamble
        start = text.find('[')
        end = text.rfind(']')
        if start == -1 or end == -1 or end < start:
            return []
        data = json.loads(text[start:end + 1])
        if not isinstance(data, list):
            return []
        out = []
        for item in data[:3]:  # hard cap at 3 tools
            if not isinstance(item, dict):
                continue
            tool = item.get('tool')
            args = item.get('args') or {}
            if tool in _VALID_TOOLS and isinstance(args, dict):
                out.append({'tool': tool, 'args': args})
        return out
    except Exception as exc:
        log.warning(f'Tool router failed: {exc}')
        return []


def _execute_tool(tool_name: str, args: dict) -> str | None:
    """Run a tool and return its formatted result, or None on failure."""
    try:
        from .tools import (
            tool_topic_search, tool_person_history, tool_period_entries,
            tool_mood_trend, tool_compare_periods,
            tool_activity_impact, tool_people_overview, tool_best_worst_days,
            tool_diary_stats, tool_on_this_day, tool_weather_impact,
        )
        if tool_name == 'activity_impact':
            return tool_activity_impact()
        if tool_name == 'weather_impact':
            return tool_weather_impact()
        if tool_name == 'people_overview':
            return tool_people_overview()
        if tool_name == 'best_worst_days':
            top_n = (args or {}).get('top_n', 5)
            return tool_best_worst_days(top_n)
        if tool_name == 'diary_stats':
            return tool_diary_stats()
        if tool_name == 'on_this_day':
            return tool_on_this_day()
        if tool_name == 'person_history':
            name = str((args or {}).get('name') or '').strip()
            if not name:
                return None
            return tool_person_history(name)
        if tool_name == 'period_entries':
            year = (args or {}).get('year')
            month = (args or {}).get('month')
            if year is None:
                return None
            return tool_period_entries(year, month)
        if tool_name == 'search_topic':
            query = str((args or {}).get('query') or '').strip()
            if not query:
                return None
            return tool_topic_search(query)
        if tool_name == 'mood_trend':
            window = (args or {}).get('window_days', 30)
            return tool_mood_trend(window)
        if tool_name == 'compare_periods':
            a = str((args or {}).get('period_a') or '').strip()
            b = str((args or {}).get('period_b') or '').strip()
            if not a or not b:
                return None
            return tool_compare_periods(a, b)
    except Exception as exc:
        log.warning(f'Tool exec failed for {tool_name}: {exc}')
    return None
_llm_loading = False
_llm_loading_stage = ''  # e.g. 'importing', 'gpu:35/8192', 'cpu:8192'
_llm_loading_progress = 0  # 0-100

# Default configs; can be overridden via env:
#   LLM_N_CTX, LLM_CPU_N_CTX, LLM_N_GPU_LAYERS
#   LLM_N_THREADS, LLM_N_THREADS_BATCH
#   LLM_N_BATCH, LLM_N_UBATCH
#   LLM_F16_KV, LLM_USE_MMAP, LLM_USE_MLOCK
#   LLM_HW_PROFILE (e.g., 8GB_16GB)
#   LLM_AUTO_HW_PROFILE (true/false)
#   LLM_REQUIRE_GPU (true/false) - disable CPU fallback if GPU offload is unavailable
#   LLM_GPU_FIRST (true/false) - try reduced GPU contexts before CPU fallback
#   LLM_GPU_CTX_STEP (int) - step size for GPU context fallback
#   LLM_MIN_GPU_CTX (int) - minimum GPU context for fallback
#   LLM_ENABLE_THINKING (true/false) - enable <think> reasoning blocks for chat
#   LLM_MAX_THINK_CHARS (int) - soft cap on think block length (when enabled)
_DEFAULT_GPU_CTX = 6144
_DEFAULT_CPU_CTX = 6144
_DEFAULT_GPU_LAYER_CANDIDATES = [-1, 35, 28, 25, 20, 15]


def _env_int(name: str, default: int, min_value: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if min_value is not None and value < min_value:
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == '':
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


_thinking_state = threading.local()


def _set_default_env(name: str, value: str) -> None:
    if name not in os.environ or os.environ.get(name, '').strip() == '':
        os.environ[name] = value


def _get_request_thinking(default: bool | None = None) -> bool:
    if hasattr(_thinking_state, 'enabled'):
        return bool(_thinking_state.enabled)
    if default is None:
        return _env_bool('LLM_ENABLE_THINKING', False)
    return default


def _set_request_thinking(value: bool | None) -> None:
    _thinking_state.enabled = value


def _clear_request_thinking() -> None:
    if hasattr(_thinking_state, 'enabled'):
        delattr(_thinking_state, 'enabled')


def _apply_profile_settings(
    name: str,
    n_ctx: int,
    reserve_tokens: int,
    n_batch: int,
    n_ubatch: int,
    n_gpu_layers: int | None,
) -> str:
    _set_default_env('LLM_N_CTX', str(n_ctx))
    _set_default_env('LLM_RESERVE_TOKENS', str(reserve_tokens))
    _set_default_env('LLM_N_BATCH', str(n_batch))
    _set_default_env('LLM_N_UBATCH', str(n_ubatch))
    if n_gpu_layers is not None:
        _set_default_env('LLM_N_GPU_LAYERS', str(n_gpu_layers))
    return name


def _apply_hw_profile(profile_name: str) -> str | None:
    profile = (profile_name or '').strip().lower()
    if not profile:
        return None

    if profile in {
        '8gb_16gb', '8gb-16gb', '8gb_vram_16gb_ram', '8gb_vram_16gb',
        '8gbvram_16gbram', '8gb', '8gb_vram'
    }:
        return _apply_profile_settings('8GB_16GB', 6144, 768, 256, 128, None)

    return None


def _gpu_ctx_candidates(base_ctx: int) -> list[int]:
    candidates = [base_ctx]
    if not _env_bool('LLM_GPU_FIRST', True):
        return candidates
    step = _env_int('LLM_GPU_CTX_STEP', 1024, min_value=256)
    min_ctx = _env_int('LLM_MIN_GPU_CTX', 3072, min_value=256)
    ctx = base_ctx - step
    while ctx >= min_ctx:
        if ctx not in candidates:
            candidates.append(ctx)
        ctx -= step
    return candidates


def _detect_total_ram_gb() -> float | None:
    try:
        if os.name == 'nt':
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullTotalPhys / (1024 ** 3)
            return None

        # Unix / macOS
        if hasattr(os, 'sysconf'):
            page_size = os.sysconf('SC_PAGE_SIZE')
            pages = os.sysconf('SC_PHYS_PAGES')
            return (page_size * pages) / (1024 ** 3)
    except Exception:
        return None

    # macOS fallback
    try:
        out = subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True).strip()
        if out.isdigit():
            return int(out) / (1024 ** 3)
    except Exception:
        pass
    return None


def _detect_nvidia_vram_gb() -> float | None:
    smi = shutil.which('nvidia-smi')
    if not smi:
        return None
    try:
        out = subprocess.check_output(
            [smi, '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        values = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                values.append(int(line))
            except ValueError:
                continue
        if not values:
            return None
        return max(values) / 1024.0
    except Exception:
        return None


def _auto_select_profile() -> str | None:
    if not _env_bool('LLM_AUTO_HW_PROFILE', True):
        return None
    # If user explicitly set a profile, prefer that
    explicit = os.environ.get('LLM_HW_PROFILE', '').strip()
    if explicit:
        return _apply_hw_profile(explicit)

    system = platform.system().lower()
    machine = platform.machine().lower()
    ram_gb = _detect_total_ram_gb()
    vram_gb = _detect_nvidia_vram_gb()

    # Apple Silicon (M-series)
    if system == 'darwin' and machine in {'arm64', 'aarch64'}:
        if ram_gb and ram_gb >= 24:
            return _apply_profile_settings('M_SERIES_24GB', 8192, 1024, 128, 64, None)
        return _apply_profile_settings('M_SERIES_16GB', 6144, 768, 128, 64, None)

    # Windows / Linux: prefer VRAM-based profile if available
    if vram_gb is not None:
        if vram_gb >= 12:
            return _apply_profile_settings('GPU_12GB', 8192, 1024, 256, 128, None)
        if vram_gb >= 8:
            return _apply_profile_settings('GPU_8GB', 6144, 768, 256, 128, None)
        if vram_gb >= 6:
            return _apply_profile_settings('GPU_6GB', 4096, 512, 128, 64, None)
        return _apply_profile_settings('GPU_LOW', 3072, 384, 64, 32, None)

    # RAM-based fallback
    if ram_gb is not None:
        if ram_gb >= 32:
            return _apply_profile_settings('RAM_32GB', 6144, 768, 128, 64, None)
        if ram_gb >= 16:
            return _apply_profile_settings('RAM_16GB', 4096, 512, 128, 64, None)
        return _apply_profile_settings('RAM_8GB', 3072, 384, 64, 32, None)

    return None


def _get_max_tokens(default_value: int | None = None) -> int | None:
    raw = os.environ.get('LLM_MAX_TOKENS')
    if raw is None or raw == '':
        return default_value
    try:
        value = int(raw)
    except ValueError:
        return default_value
    # 0 or negative = no explicit limit
    if value <= 0:
        return None
    return value


def _ends_with_terminal_punct(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return True
    terminal_chars = {'.', '!', '?', '…', ')', '"', '»', '”'}
    return stripped[-1] in terminal_chars


def _needs_continuation(llm, text: str) -> bool:
    if not text or len(text) < 40:
        return False
    if _ends_with_terminal_punct(text):
        return False
    reserve = _env_int('LLM_RESERVE_TOKENS', 512, min_value=0)
    out_tokens = _count_tokens(llm, text)
    # Only continue if we likely hit the length limit.
    if reserve > 0 and out_tokens < max(64, reserve - 8):
        return False
    return True


def _get_continue_prompt() -> str:
    return os.environ.get(
        'LLM_CONTINUE_PROMPT',
        'Продолжи предыдущий ответ. Не начинай заново. Заверши мысль.'
    )


def _get_final_answer_instruction() -> str:
    return os.environ.get(
        'LLM_FINAL_ANSWER_INSTRUCTION',
        'Дай только итоговый ответ по сути запроса. Без рассуждений, без заголовков '
        'вида "Thinking Process", без <think> и без перечисления правил.'
    )


def _get_thinking_instruction() -> str:
    return os.environ.get(
        'LLM_THINKING_INSTRUCTION',
        'ПРАВИЛА РАЗМЫШЛЕНИЯ (<think>):\n'
        '- Язык размышлений: ТОЛЬКО РУССКИЙ. НИКОГДА не думай на английском.\n'
        '- ЗАПРЕЩЕНО цитировать или перечислять правила из этой инструкции.\n'
        '- Думай ТОЛЬКО о сути вопроса: что спрашивают и как лучше ответить.\n'
        '- Максимум 3-5 коротких предложений.\n'
        '- После </think> ОБЯЗАТЕЛЬНО дай полный ответ.'
    )


def _build_continuation_messages(llm, system_text: str, assistant_text: str) -> list[dict]:
    n_ctx = _llm_n_ctx or _env_int('LLM_N_CTX', _DEFAULT_GPU_CTX, min_value=256)
    reserve = _env_int('LLM_RESERVE_TOKENS', 512, min_value=0)
    safety = 8
    budget = n_ctx - reserve - safety
    if budget < 128:
        budget = max(32, n_ctx - safety)

    user_text = _get_continue_prompt()

    def msg_tokens(content: str) -> int:
        return _count_tokens(llm, content) + 4

    sys_text = system_text or _base_system_prompt()
    sys_tokens = msg_tokens(sys_text)
    user_tokens = msg_tokens(user_text)
    assistant_tokens = msg_tokens(assistant_text)

    # If too long, drop to base system prompt
    if sys_tokens + assistant_tokens + user_tokens > budget:
        sys_text = _base_system_prompt()
        sys_tokens = msg_tokens(sys_text)

    # If still too long, truncate assistant text to fit
    if sys_tokens + assistant_tokens + user_tokens > budget:
        target = max(0, budget - sys_tokens - user_tokens - 4)
        assistant_text = _truncate_to_tokens(llm, assistant_text, target)

    return [
        {'role': 'system', 'content': sys_text},
        {'role': 'assistant', 'content': assistant_text},
        {'role': 'user', 'content': user_text},
    ]


def _base_system_prompt() -> str:
    """Minimal system prompt used as a fallback when context must be
    trimmed/continued. Pick the diary-access framing from real data so a
    trimmed prompt never claims entries exist when the diary is empty.
    """
    from datetime import datetime
    try:
        has_data = MoodEntry.query.filter_by(deleted=False).count() > 0
    except Exception:
        has_data = True  # safer to assume data than to deny a real diary
    return SYSTEM_PROMPT.format(
        today=datetime.now().strftime('%Y-%m-%d'),
        diary_access_section=DIARY_ACCESS_PRESENT if has_data else DIARY_ACCESS_EMPTY,
        profile_section='',
        timeline_section='',
        relevant_section='',
        recent_section='',
    )


def _trim_messages_to_fit(llm, messages: list[dict]) -> list[dict]:
    if not messages:
        return messages

    n_ctx = _llm_n_ctx or _env_int('LLM_N_CTX', _DEFAULT_GPU_CTX, min_value=256)
    reserve = _env_int('LLM_RESERVE_TOKENS', 512, min_value=0)
    safety = 8
    budget = n_ctx - reserve - safety
    if budget < 128:
        budget = max(32, n_ctx - safety)

    system = messages[0]
    tail = messages[1:]
    last = tail[-1] if tail else None

    def msg_tokens(msg: dict) -> int:
        return _count_tokens(llm, msg.get('content', '')) + 4

    sys_tokens = msg_tokens(system)
    last_tokens = msg_tokens(last) if last else 0

    if last and sys_tokens + last_tokens > budget:
        system = {'role': 'system', 'content': _base_system_prompt()}
        sys_tokens = msg_tokens(system)

    if last and sys_tokens + last_tokens > budget:
        target = max(0, budget - last_tokens - 4)
        system = {
            'role': 'system',
            'content': _truncate_to_tokens(llm, system.get('content', ''), target),
        }
        sys_tokens = msg_tokens(system)

    remaining = budget - sys_tokens
    trimmed_tail = []

    if last:
        if last_tokens > remaining:
            target = max(0, remaining - 4)
            last = {
                **last,
                'content': _truncate_to_tokens(llm, last.get('content', ''), target),
            }
            last_tokens = msg_tokens(last)
        trimmed_tail.append(last)
        remaining -= last_tokens

        for msg in reversed(tail[:-1]):
            tokens = msg_tokens(msg)
            if tokens <= remaining:
                trimmed_tail.append(msg)
                remaining -= tokens
            else:
                break
        trimmed_tail.reverse()

    return [system] + trimmed_tail


def _get_llm():
    """Lazy-load the GGUF model on first request. Tries GPU, falls back to CPU."""
    global _llm, _llm_n_ctx, _llm_loading, _llm_loading_stage, _llm_loading_progress
    if _llm is not None:
        return _llm
    with _llm_lock:
        # Double-check after acquiring lock
        if _llm is not None:
            return _llm
        _llm_loading = True
        _llm_loading_stage = 'importing'
        _llm_loading_progress = 5
        try:
            import inspect
            from llama_cpp import Llama
            import llama_cpp

            # Patch: enable per-request thinking mode for Qwen3.5
            # The GGUF chat template checks `enable_thinking` but llama-cpp-python
            # doesn't pass it to Jinja2 render, so thinking is always off.
            # We patch Jinja2ChatFormatter to inject a per-request boolean.
            try:
                from llama_cpp.llama_chat_format import Jinja2ChatFormatter
                if not getattr(Jinja2ChatFormatter.__call__, '_thinking_patched', False):
                    _orig_jinja2_call = Jinja2ChatFormatter.__call__

                    def _patched_jinja2_call(self, *args, **kwargs):
                        env = getattr(self, '_environment', None)
                        had_prev = False
                        prev = None
                        if env is not None and hasattr(env, 'globals'):
                            had_prev = 'enable_thinking' in env.globals
                            prev = env.globals.get('enable_thinking')
                            env.globals['enable_thinking'] = _get_request_thinking()
                        try:
                            return _orig_jinja2_call(self, *args, **kwargs)
                        finally:
                            if env is not None and hasattr(env, 'globals'):
                                if had_prev:
                                    env.globals['enable_thinking'] = prev
                                else:
                                    env.globals.pop('enable_thinking', None)

                    _patched_jinja2_call._thinking_patched = True
                    Jinja2ChatFormatter.__call__ = _patched_jinja2_call
                    log.info('Patched Jinja2ChatFormatter for toggleable thinking mode')
            except Exception as e:
                log.warning('Could not patch thinking mode: %s', e)

            _llm_loading_stage = 'detecting'
            _llm_loading_progress = 10
            profile_name = _auto_select_profile()
            if profile_name:
                log.info(f'LLM hardware profile applied: {profile_name}')

            # Search for model in user data dir first, then bundled location.
            # On Windows we check both next-to-exe (portable) and %APPDATA%
            # (legacy) so existing users don't have to re-download the model.
            gguf_files = []
            _search_dirs = [Path(__file__).parent / 'models']
            if getattr(sys, 'frozen', False):
                if sys.platform == 'darwin':
                    _search_dirs.insert(
                        0,
                        Path.home() / 'Library' / 'Application Support' / 'index.life'
                        / 'models' / 'assistant',
                    )
                elif sys.platform == 'win32':
                    exe_dir = Path(sys.executable).resolve().parent
                    appdata = Path(os.environ.get('APPDATA', str(Path.home()))) / 'index.life'
                    _search_dirs.insert(0, appdata / 'models' / 'assistant')
                    _search_dirs.insert(0, exe_dir / 'models' / 'assistant')
                else:
                    _search_dirs.insert(0, Path.home() / '.index-life' / 'models' / 'assistant')
            for model_dir in _search_dirs:
                if model_dir.exists():
                    gguf_files = list(model_dir.glob('*.gguf'))
                    if gguf_files:
                        break
            if not gguf_files:
                raise FileNotFoundError(
                    f'No .gguf model file found. Searched: {[str(d) for d in _search_dirs]}. '
                    'Install the assistant module from the Modules page.'
                )
            model_path = str(gguf_files[0])

            def filter_kwargs(kwargs: dict) -> dict:
                try:
                    sig = inspect.signature(Llama.__init__)
                except (TypeError, ValueError):
                    return kwargs
                if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    return kwargs
                params = set(sig.parameters)
                return {k: v for k, v in kwargs.items() if k in params}

            def build_kwargs(n_ctx: int, n_gpu_layers: int) -> dict:
                cpu_count = os.cpu_count() or 4
                n_threads = _env_int('LLM_N_THREADS', max(4, cpu_count), min_value=1)
                n_threads_batch = _env_int('LLM_N_THREADS_BATCH', n_threads, min_value=1)
                use_gpu = n_gpu_layers != 0
                n_batch_default = 256 if use_gpu else 128
                n_ubatch_default = 128 if use_gpu else 32
                kwargs = {
                    'model_path': model_path,
                    'n_ctx': n_ctx,
                    'n_threads': n_threads,
                    'n_threads_batch': n_threads_batch,
                    'n_batch': _env_int('LLM_N_BATCH', n_batch_default, min_value=1),
                    'n_ubatch': _env_int('LLM_N_UBATCH', n_ubatch_default, min_value=1),
                    'n_gpu_layers': n_gpu_layers,
                    'f16_kv': _env_bool('LLM_F16_KV', True),
                    'use_mmap': _env_bool('LLM_USE_MMAP', True),
                    'use_mlock': _env_bool('LLM_USE_MLOCK', False),
                    'verbose': False,
                }
                return filter_kwargs(kwargs)

            # Resolve context sizes
            gpu_ctx = _env_int('LLM_N_CTX', _DEFAULT_GPU_CTX, min_value=256)
            cpu_ctx = _env_int('LLM_CPU_N_CTX', _DEFAULT_CPU_CTX, min_value=256)

            gpu_offload = llama_cpp.llama_supports_gpu_offload()

            # Try GPU configs if CUDA is available
            if gpu_offload:
                raw_gpu_layers = os.environ.get('LLM_N_GPU_LAYERS')
                if raw_gpu_layers:
                    try:
                        gpu_layer_candidates = [int(raw_gpu_layers)]
                    except ValueError:
                        log.warning('Invalid LLM_N_GPU_LAYERS; using defaults.')
                        gpu_layer_candidates = _DEFAULT_GPU_LAYER_CANDIDATES
                else:
                    gpu_layer_candidates = _DEFAULT_GPU_LAYER_CANDIDATES

                ctx_candidates = _gpu_ctx_candidates(gpu_ctx)
                total_attempts = len(gpu_layer_candidates) * len(ctx_candidates)
                attempt = 0
                for n_gpu in gpu_layer_candidates:
                    for ctx in ctx_candidates:
                        attempt += 1
                        _llm_loading_stage = f'gpu:{n_gpu}/{ctx}'
                        _llm_loading_progress = 15 + int(65 * attempt / max(total_attempts, 1))
                        try:
                            _llm = Llama(**build_kwargs(ctx, n_gpu))
                            _llm_n_ctx = ctx
                            _llm_loading_progress = 100
                            _llm_loading_stage = 'ready'
                            log.info(f'Model loaded with GPU: n_gpu_layers={n_gpu}, n_ctx={ctx}')
                            return _llm
                        except Exception as e:
                            log.warning(f'GPU config (n_gpu_layers={n_gpu}, n_ctx={ctx}) failed: {e}')
                            _llm = None

            # Fallback: CPU only
            _llm_loading_stage = f'cpu:{cpu_ctx}'
            _llm_loading_progress = 85
            _llm = Llama(**build_kwargs(cpu_ctx, 0))
            _llm_n_ctx = cpu_ctx
            _llm_loading_progress = 100
            _llm_loading_stage = 'ready'
            log.info(f'Model loaded on CPU: n_ctx={cpu_ctx}')
        finally:
            _llm_loading = False
    return _llm


def _check_crisis(text: str) -> bool:
    """Check if message contains crisis indicators."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in CRISIS_KEYWORDS)


def _build_proactive_note() -> str:
    """A short, data-grounded line shown when the user opens an empty chat.

    DB-only (no LLM) so it never delays the page. Returns '' when there's
    no clear signal worth surfacing (incl. an empty diary — so we never
    invent observations about a diary that has no data).
    """
    from datetime import date as _date, timedelta
    from app.i18n import t as _t
    try:
        entries = (MoodEntry.query
                   .filter_by(deleted=False)
                   .order_by(MoodEntry.date)
                   .all())
    except Exception:
        return ''
    if not entries:
        return ''

    # 1) Logging-streak milestone — most rewarding, takes priority.
    dates = {e.date for e in entries}
    today = _date.today()
    streak = 0
    d = today if today in dates else today - timedelta(days=1)
    while d in dates:
        streak += 1
        d -= timedelta(days=1)
    if streak >= 7:
        return _t('assistant.proactive_streak', days=streak)

    # 2) Last-14-days mood trend vs the previous 14 days.
    recent_cut = today - timedelta(days=13)
    prev_cut = today - timedelta(days=27)
    recent = [e.rating for e in entries if e.date >= recent_cut]
    prev = [e.rating for e in entries if prev_cut <= e.date < recent_cut]
    if len(recent) >= 3 and len(prev) >= 3:
        delta = sum(recent) / len(recent) - sum(prev) / len(prev)
        if delta > 0.5:
            return _t('assistant.proactive_trend_up')
        if delta < -0.5:
            return _t('assistant.proactive_trend_down')
    return ''


@bp.route('/')
def chat():
    """Render the chat page."""
    messages = ChatMessage.query.order_by(ChatMessage.created_at).all()
    history = [{'role': m.role, 'content': m.content} for m in messages]

    # Pre-load topic message when arriving from deep-mind neural map
    preload_message = ''
    topic_id = request.args.get('topic', type=int)
    if topic_id:
        try:
            from app.models import MindCluster, MindClusterEntry
            cluster = db.session.get(MindCluster, topic_id)
            if cluster:
                member_ids = [
                    me.entry_id for me in
                    MindClusterEntry.query.filter_by(cluster_id=topic_id).limit(5).all()
                ]
                entries = MoodEntry.query.filter(
                    MoodEntry.id.in_(member_ids)
                ).order_by(MoodEntry.date.desc()).all()
                sample_dates = ', '.join(e.date.isoformat() for e in entries[:3])
                preload_message = (
                    f'Я хочу поговорить о теме "{cluster.label}". '
                    f'{cluster.description or ""} '
                    f'Эта тема прослеживается в моих записях от {sample_dates}. '
                    f'Помоги мне глубже разобраться в этом.'
                ).strip()
        except Exception:
            pass

    thinking_default = _env_bool('LLM_ENABLE_THINKING', False)

    # Proactive opener: only when starting a fresh chat (no history) and
    # there's a clear data signal. Never shown for an empty diary.
    proactive_note = _build_proactive_note() if not history else ''

    # User avatar URL
    from app.models import UserProfile
    profile = UserProfile.query.first()
    user_avatar = '/static/images/usernophoto.png'
    if profile and profile.photo_filename:
        photo_path = Path(current_app.config.get('UPLOAD_FOLDER', '')) / profile.photo_filename
        if photo_path.is_file():
            from flask import url_for
            user_avatar = url_for('main.profile_photo', filename=profile.photo_filename)

    return render_template('assistant/chat.html', history=history,
                           preload_message=preload_message,
                           thinking_default=thinking_default,
                           proactive_note=proactive_note,
                           user_avatar=user_avatar)


@bp.route('/stream', methods=['POST'])
def stream():
    """Streaming endpoint: streams the AI reply token by token.

    Generation runs inside the request. If the user navigates away, the
    connection drops and generation stops — at that moment we persist whatever
    was already produced, so the partial reply isn't lost (it just won't be
    completed).
    """
    data = request.get_json(silent=True) or {}
    user_message = data.get('message', '').strip()
    enable_thinking = data.get('enable_thinking', None)

    if not user_message:
        return Response('data: [DONE]\n\n', content_type='text/event-stream')

    # Save user message to DB
    db.session.add(ChatMessage(role='user', content=user_message))
    db.session.commit()

    # Crisis check
    if _check_crisis(user_message):
        def crisis_stream():
            db.session.add(ChatMessage(role='assistant', content=CRISIS_RESPONSE))
            db.session.commit()
            yield f'data: {json.dumps({"token": CRISIS_RESPONSE})}\n\n'
            yield 'data: [DONE]\n\n'
        return Response(
            stream_with_context(crisis_stream()),
            content_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
        )

    def generate():
        full_response = ''
        saved = False

        def _save_partial():
            # Persist the assistant reply once — at normal completion, or when
            # the client disconnects mid-stream (user navigated away). Keeps
            # the partial text instead of losing it.
            nonlocal saved
            if saved or not full_response:
                return
            try:
                save_text = _strip_think(full_response).strip() or full_response
                db.session.add(ChatMessage(role='assistant', content=save_text))
                db.session.commit()
                saved = True
            except Exception:
                # Don't lose the reply silently — log it, and roll back so the
                # session is clean for the teardown that follows.
                log.warning('Failed to persist assistant reply', exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass

        try:
            if enable_thinking is None:
                _clear_request_thinking()
            else:
                _set_request_thinking(bool(enable_thinking))
            thinking_enabled = _get_request_thinking()
            llm = _get_llm()

            # Tool routing — pre-fetch focused data (person history, period,
            # topic, mood trend, period comparison). Router picks 0–2 tools
            # in a single LLM call; result is appended to system prompt so
            # the reply grounds on facts rather than vibes.
            #
            # Multi-turn awareness: pass the previous user message so a
            # follow-up like "расскажи подробнее" still routes correctly.
            prior_user_msg = None
            try:
                prior = (ChatMessage.query
                         .filter_by(role='user')
                         .order_by(ChatMessage.created_at.desc())
                         .offset(1)  # the current message is at offset 0
                         .limit(1)
                         .first())
                if prior:
                    prior_user_msg = prior.content
            except Exception:
                # Non-fatal: the router just loses multi-turn context.
                log.warning('Could not load prior user message', exc_info=True)
            # prior_user_msg is a plain string — release connection before
            # the router LLM call so it doesn't block other writers.
            db.session.remove()

            tool_decisions = _route_to_tools(llm, user_message, prior_user_msg)
            tool_outputs: list[tuple[str, str]] = []  # [(tool_name, result_text)]
            for decision in tool_decisions:
                yield ('data: ' + json.dumps({
                    'tool': decision['tool'],
                    'args': decision['args'],
                }) + '\n\n')
                result_text = _execute_tool(decision['tool'], decision['args'])
                if result_text:
                    tool_outputs.append((decision['tool'], result_text))
            if tool_outputs:
                yield 'data: ' + json.dumps({'tool_done': True}) + '\n\n'
            # tool_outputs contains plain strings — release connection before
            # assemble_context which opens its own DB read.
            db.session.remove()

            # Detect emotional tone for adaptive responses
            from .memory import assemble_context, detect_emotional_tone
            user_tone, tone_confidence = detect_emotional_tone(user_message)
            n_ctx = _llm_n_ctx or _env_int('LLM_N_CTX', _DEFAULT_GPU_CTX, min_value=256)
            reserve = _env_int('LLM_RESERVE_TOKENS', 512, min_value=0)
            thinking_overhead = (_count_tokens(llm, _get_thinking_instruction()) + 10
                                 if thinking_enabled else 0)
            # Budget for system prompt: n_ctx minus output reserve, chat history (~1000),
            # thinking instruction, and safety margin
            system_budget = n_ctx - reserve - 1000 - thinking_overhead - 64
            system_base = assemble_context(user_message,
                                           max_system_tokens=max(512, system_budget))
            system = system_base

            # Append tool-fetched data to the system prompt as separate
            # sections so the model can ground its reply. Caps total tool
            # output to ~5000 chars (≈1000-1300 tokens) to leave room for
            # everything else; with 2 tools that's ~2500 chars each.
            if tool_outputs:
                per_tool_cap = 5000 // max(1, len(tool_outputs))
                sections = []
                for tname, text in tool_outputs:
                    chunk = text
                    if len(chunk) > per_tool_cap:
                        chunk = chunk[:per_tool_cap].rstrip() + '\n[обрезано]'
                    sections.append(
                        f'[{tname}]\n{chunk}'
                    )
                system += (
                    '\n\nДОПОЛНИТЕЛЬНЫЕ ДАННЫЕ ИЗ ДНЕВНИКА (получены '
                    'инструментами; используй конкретные даты и цитаты при '
                    'ответе, не пересказывай шаблонно):\n\n'
                    + '\n\n'.join(sections)
                )

            # Inject emotional tone hint
            if tone_confidence > 0.5 and user_tone in ('distressed', 'sad'):
                system += ('\n\nТОН ПОЛЬЗОВАТЕЛЯ: Пользователь сейчас в тяжёлом '
                           'эмоциональном состоянии. Будь особенно мягким и поддерживающим.')
            elif tone_confidence > 0.5 and user_tone == 'positive':
                system += ('\n\nТОН ПОЛЬЗОВАТЕЛЯ: Пользователь в хорошем настроении. '
                           'Можешь быть более свободным и лёгким в общении.')

            if thinking_enabled:
                system = system + '\n\n' + _get_thinking_instruction()

            messages = [{'role': 'system', 'content': system}]

            # Load recent chat history from DB (last 10 exchanges = 20 messages)
            recent_chat = (ChatMessage.query
                           .order_by(ChatMessage.created_at.desc())
                           .limit(20)
                           .all())
            recent_chat.reverse()
            # Skip the last one (it's the current user message we just saved)
            for msg in recent_chat[:-1]:
                messages.append({'role': msg.role, 'content': msg.content})
            if thinking_enabled:
                messages.append({'role': 'user', 'content':
                    user_message + '\n\n[Думай на РУССКОМ. Макс 3-5 предложений.]'})
            else:
                messages.append({'role': 'user', 'content': user_message})

            messages = _trim_messages_to_fit(llm, messages)

            # Calculate context usage and send to client
            total_ctx_tokens = sum(_count_tokens(llm, m.get('content', '')) + 4
                                   for m in messages)
            ctx_n_ctx = _llm_n_ctx or _env_int('LLM_N_CTX', _DEFAULT_GPU_CTX, min_value=256)
            ctx_pct = min(100, int(total_ctx_tokens * 100 / ctx_n_ctx))
            yield f'data: {json.dumps({"context": {"used": total_ctx_tokens, "max": ctx_n_ctx, "pct": ctx_pct, "msgs": len(messages) - 1}})}\n\n'

            # Cache the system-prompt token count so /context-usage can
            # show an honest estimate between messages. Without this it
            # used a fixed 800-token baseline, so users who compressed
            # the chat saw a misleading drop in the bar that bounced
            # straight back up the moment they sent the next message
            # (the real prompt is 2000-3000 tokens of retrieved entries
            # + profile + timeline, not 800).
            try:
                from app.models import SyncMeta
                sys_tokens_only = _count_tokens(llm, system) + 4
                row = db.session.get(SyncMeta, 'last_system_tokens')
                if row:
                    row.value = str(sys_tokens_only)
                else:
                    db.session.add(SyncMeta(
                        key='last_system_tokens',
                        value=str(sys_tokens_only),
                    ))
                db.session.commit()
            except Exception:
                db.session.rollback()

            # Adaptive temperature based on emotional tone
            if thinking_enabled:
                temperature = 0.4 if user_tone in ('distressed', 'sad') else 0.5
            else:
                temperature = 0.5 if user_tone in ('distressed', 'sad') else 0.7

            max_tokens = _get_max_tokens()
            chat_kwargs = {
                'messages': messages,
                'stream': True,
                'temperature': temperature,
            }
            if max_tokens is not None:
                chat_kwargs['max_tokens'] = max_tokens

            # Release DB connection before long LLM inference so background
            # threads (embedding, summary, etc.) are not blocked for the
            # entire generation time. All needed data is already in local
            # variables (messages, system, user_tone…).
            db.session.remove()

            # Acquire inference lock to prevent concurrent LLM access
            # (llama-cpp-python is not thread-safe)
            _llm_inference_lock.acquire()
            try:
                response = llm.create_chat_completion(**chat_kwargs)

                # The Qwen3.5 chat template injects <think>\n into the prompt
                # (not into the generated output), so we prepend <think> when
                # thinking is enabled to wrap reasoning for the UI.
                think_prefix_sent = False
                for chunk in response:
                    delta = chunk['choices'][0].get('delta', {})
                    token = delta.get('content', '')
                    if token:
                        if thinking_enabled and not think_prefix_sent:
                            if '<think>' not in token:
                                token = '<think>' + token
                            think_prefix_sent = True
                        full_response += token
                        yield f'data: {json.dumps({"token": token})}\n\n'

                if thinking_enabled and '<think>' in full_response and '</think>' not in full_response:
                    close_token = '\n</think>\n'
                    full_response += close_token
                    yield f'data: {json.dumps({"token": close_token})}\n\n'

                # If thinking mode produced only reasoning, request a final answer (non-streaming).
                if thinking_enabled:
                    try:
                        answer_only = _strip_think(full_response).strip()
                    except Exception:
                        answer_only = ''
                    if len(answer_only) < 10:
                        try:
                            _set_request_thinking(False)
                            final_system = system_base + '\n\n' + _get_final_answer_instruction()
                            final_messages = list(messages)
                            if final_messages:
                                final_messages[0] = {'role': 'system', 'content': final_system}
                            else:
                                final_messages = [
                                    {'role': 'system', 'content': final_system},
                                    {'role': 'user', 'content': user_message},
                                ]
                            final_kwargs = {
                                'messages': final_messages,
                                'stream': False,
                                'temperature': 0.3,
                            }
                            if max_tokens is not None:
                                final_kwargs['max_tokens'] = max_tokens
                            final_resp = llm.create_chat_completion(**final_kwargs)
                            final_text = final_resp['choices'][0]['message']['content']
                            if final_text:
                                if full_response and not full_response.endswith('\n'):
                                    full_response += '\n'
                                    yield 'data: ' + json.dumps({"token": "\n"}) + '\n\n'
                                full_response += final_text
                                yield f'data: {json.dumps({"token": final_text})}\n\n'
                        except Exception:
                            # Degraded, not fatal: the user keeps the thinking
                            # output, just without a re-asked final answer.
                            log.debug('Final-answer pass failed', exc_info=True)

                auto_continue = _env_bool('LLM_AUTO_CONTINUE', False)
                max_cont = _env_int('LLM_MAX_CONTINUATIONS', 2, min_value=0)
                cont_count = 0
                while auto_continue and cont_count < max_cont and _needs_continuation(llm, full_response):
                    cont_count += 1
                    yield f'data: {json.dumps({"event": "continuation", "count": cont_count})}\n\n'
                    continuation_messages = _build_continuation_messages(llm, system, full_response)
                    continue_kwargs = {
                        'messages': continuation_messages,
                        'stream': True,
                        'temperature': 0.7,
                    }
                    if max_tokens is not None:
                        continue_kwargs['max_tokens'] = max_tokens

                    response = llm.create_chat_completion(**continue_kwargs)
                    appended = False
                    for chunk in response:
                        delta = chunk['choices'][0].get('delta', {})
                        token = delta.get('content', '')
                        if token:
                            appended = True
                            full_response += token
                            yield f'data: {json.dumps({"token": token})}\n\n'
                    if not appended:
                        break
            finally:
                _llm_inference_lock.release()

            # Save assistant response to DB, then signal completion.
            _save_partial()
            yield 'data: [DONE]\n\n'

        except GeneratorExit:
            # Client navigated away mid-stream: generation stops here, but keep
            # whatever was already produced so the partial reply isn't lost.
            _save_partial()
            raise
        except FileNotFoundError as e:
            yield f'data: {json.dumps({"error": f"Модель не найдена: {e}", "error_type": "model_missing"})}\n\n'
            yield 'data: [DONE]\n\n'
        except MemoryError:
            yield f'data: {json.dumps({"error": "Недостаточно памяти. Попробуйте перезапустить приложение или закрыть другие программы.", "error_type": "memory"})}\n\n'
            yield 'data: [DONE]\n\n'
        except Exception as e:
            from app.i18n import t as _t
            error_msg = str(e).lower()
            if 'context' in error_msg or 'token' in error_msg:
                msg = _t('assistant.context_too_long')
            elif 'memory' in error_msg or 'allocat' in error_msg:
                msg = _t('assistant.out_of_memory')
            else:
                msg = _t('assistant.model_error', err=str(e))
            yield f'data: {json.dumps({"error": msg, "error_type": "general"})}\n\n'
            yield 'data: [DONE]\n\n'
        finally:
            _clear_request_thinking()

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@bp.route('/warmup', methods=['POST'])
def warmup():
    """Warm up the LLM and embedding model in background."""

    def _warm():
        try:
            _get_llm()
        except Exception as e:
            log.warning(f'LLM warmup failed: {e}')
        try:
            from .memory import _get_embed_model
            _get_embed_model()
        except Exception as e:
            log.warning(f'Embedding warmup failed: {e}')

    if not _env_bool('LLM_WARMUP_ON_LOAD', True):
        return jsonify({'status': 'disabled'})

    threading.Thread(target=_warm, daemon=True).start()
    return jsonify({'status': 'warming'})


@bp.route('/reindex', methods=['POST'])
def reindex():
    """Trigger full reindexing of all diary entries."""
    from .background import reindex_all_async
    started = reindex_all_async(current_app._get_current_object())
    if started:
        return jsonify({'status': 'started', 'message': 'Reindexing started in background'})
    return jsonify({'status': 'busy', 'message': 'Reindex already running'})


@bp.route('/sync', methods=['POST'])
def sync():
    """Process only entries missing embeddings or summaries."""
    from .background import sync_missing_async
    started = sync_missing_async(current_app._get_current_object())
    if started:
        return jsonify({'status': 'started', 'message': 'Sync started'})
    return jsonify({'status': 'busy', 'message': 'Background processing busy'})


@bp.route('/reset-profile', methods=['POST'])
def reset_profile():
    """Delete and rebuild the psychological profile."""
    from .background import rebuild_profile_async
    rebuild_profile_async(current_app._get_current_object())
    return jsonify({'status': 'started', 'message': 'Profile rebuilding...'})


@bp.route('/compress-chat', methods=['POST'])
def compress_chat():
    """Keep only the last 4 chat messages (2 exchanges) to free context."""
    keep = 4
    all_msgs = (ChatMessage.query
                .order_by(ChatMessage.created_at.desc())
                .all())
    if len(all_msgs) <= keep:
        return jsonify({'status': 'ok', 'removed': 0, 'remaining': len(all_msgs)})
    to_delete = all_msgs[keep:]
    for msg in to_delete:
        db.session.delete(msg)
    db.session.commit()
    return jsonify({'status': 'ok', 'removed': len(to_delete), 'remaining': keep})


@bp.route('/clear-chat', methods=['POST'])
def clear_chat():
    """Clear all chat history.

    Also writes a `chat_cleared_at` timestamp into sync_meta so the
    next sync pull can't silently re-import the messages we just
    removed: apply_snapshot filters chat messages whose `created_at`
    is older than this device's clear time. The chat continues to
    sync normally for any new messages exchanged after the clear.
    """
    from app.models import SyncMeta
    from app.timeutil import utcnow
    ChatMessage.query.delete()
    cleared_at = utcnow().isoformat()
    row = db.session.get(SyncMeta, 'chat_cleared_at')
    if row:
        row.value = cleared_at
    else:
        db.session.add(SyncMeta(key='chat_cleared_at', value=cleared_at))
    db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/context-usage')
def context_usage():
    """Estimate current context window fill level from chat history.

    Uses the cached system-prompt token count from the most recent
    /stream as the baseline (saved into SyncMeta under
    `last_system_tokens`). That number is much closer to what the next
    message will actually consume (~2000-3000 tokens) than the static
    800 we used before, so the bar doesn't lie to the user after they
    compress the chat.
    """
    n_ctx = _llm_n_ctx or _env_int('LLM_N_CTX', _DEFAULT_GPU_CTX, min_value=256)

    sys_baseline = 800
    try:
        from app.models import SyncMeta
        row = db.session.get(SyncMeta, 'last_system_tokens')
        if row and row.value and row.value.isdigit():
            sys_baseline = max(sys_baseline, int(row.value))
    except Exception:
        pass

    chat_msgs = (ChatMessage.query
                 .order_by(ChatMessage.created_at.desc())
                 .limit(20).all())
    chat_msgs.reverse()
    tokens = sys_baseline
    for msg in chat_msgs:
        content = msg.content or ''
        tokens += max(1, len(content) // 3) + 4  # ~3 chars/token for Russian
    pct = min(100, int(tokens * 100 / n_ctx))
    return jsonify({'pct': pct, 'used': tokens, 'max': n_ctx, 'msgs': len(chat_msgs)})


@bp.route('/status')
def status():
    """Return processing status for the UI."""
    total_entries = MoodEntry.query.count()
    from app.models import EntryEmbedding, EntrySummary
    embedded = EntryEmbedding.query.count()
    summarized = EntrySummary.query.count()
    profile = UserPsychProfile.query.first()
    from .background import get_reindex_status, get_sync_status
    reindex_status = get_reindex_status()
    sync_status = get_sync_status()

    # Chat message count for context indicator
    chat_count = ChatMessage.query.count()

    return jsonify({
        'total_entries': total_entries,
        'embedded': embedded,
        'summarized': summarized,
        'profile_version': profile.version if profile else 0,
        'profile_entries_analyzed': profile.entries_analyzed if profile else 0,
        'llm_loading': _llm_loading,
        'llm_loading_stage': _llm_loading_stage if _llm_loading else '',
        'llm_loading_progress': _llm_loading_progress if _llm_loading else 0,
        'llm_ready': _llm is not None,
        'reindex': reindex_status,
        'sync': sync_status,
        'chat_messages': chat_count,
        'n_ctx': _llm_n_ctx or _env_int('LLM_N_CTX', _DEFAULT_GPU_CTX, min_value=256),
    })
