"""AI Psychologist chat routes with streaming and multi-layer memory."""
import json
import os
import platform
import shutil
import subprocess
import ctypes
import threading
from pathlib import Path
from flask import render_template, request, Response, stream_with_context, jsonify, current_app
from app import db
from app.models import ChatMessage, UserPsychProfile, MoodEntry
from .prompts import CRISIS_KEYWORDS, CRISIS_RESPONSE, SYSTEM_PROMPT
from . import bp

# Ensure CUDA runtime DLLs are findable on Windows
if os.name == 'nt':
    _cuda_path = os.environ.get('CUDA_PATH', '')
    if not _cuda_path:
        # Fallback: scan common CUDA install location
        _cuda_base = Path(r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA')
        if _cuda_base.is_dir():
            _versions = sorted(_cuda_base.iterdir(), reverse=True)
            if _versions:
                _cuda_path = str(_versions[0])
    if _cuda_path:
        _cuda_bin = Path(_cuda_path) / 'bin' / 'x64'
        if _cuda_bin.is_dir() and str(_cuda_bin) not in os.environ.get('PATH', ''):
            os.environ['PATH'] = str(_cuda_bin) + ';' + os.environ.get('PATH', '')

_llm = None
_llm_n_ctx = None
_llm_lock = threading.Lock()
_llm_loading = False

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
_DEFAULT_GPU_CTX = 4096
_DEFAULT_CPU_CTX = 8192
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


def _set_default_env(name: str, value: str) -> None:
    if name not in os.environ or os.environ.get(name, '').strip() == '':
        os.environ[name] = value


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


def _count_tokens(llm, text: str) -> int:
    try:
        tokens = llm.tokenize(text.encode('utf-8'))
        return len(tokens)
    except Exception:
        return max(1, len(text) // 4)


def _truncate_to_tokens(llm, text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ''
    try:
        tokens = llm.tokenize(text.encode('utf-8'))
        if len(tokens) <= max_tokens:
            return text
        truncated = llm.detokenize(tokens[:max_tokens])
        if isinstance(truncated, bytes):
            return truncated.decode('utf-8', errors='ignore')
        if isinstance(truncated, str):
            return truncated
    except Exception:
        pass
    approx_chars = max(0, max_tokens * 4)
    return text[:approx_chars]


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
    return SYSTEM_PROMPT.format(
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
    global _llm
    global _llm_n_ctx
    if _llm is None:
        with _llm_lock:
            if _llm is not None:
                return _llm
            global _llm_loading
            _llm_loading = True
        import logging
        import inspect
        log = logging.getLogger(__name__)
        from llama_cpp import Llama
        import llama_cpp

        profile_name = _auto_select_profile()
        if profile_name:
            log.info(f'LLM hardware profile applied: {profile_name}')

        model_dir = Path(__file__).parent / 'models'
        gguf_files = list(model_dir.glob('*.gguf'))
        if not gguf_files:
            raise FileNotFoundError(
                f'No .gguf model file found in {model_dir}. '
                'Place a GGUF model file there.'
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

        try:
            require_gpu = _env_bool('LLM_REQUIRE_GPU', False)

            # Try GPU configs if CUDA is available
            if llama_cpp.llama_supports_gpu_offload():
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
                # Prefer keeping more layers on GPU by shrinking context first.
                for n_gpu in gpu_layer_candidates:
                    for ctx in ctx_candidates:
                        try:
                            _llm = Llama(**build_kwargs(ctx, n_gpu))
                            _llm_n_ctx = ctx
                            log.info(f'Model loaded with GPU: n_gpu_layers={n_gpu}, n_ctx={ctx}')
                            return _llm
                        except Exception as e:
                            log.warning(f'GPU config (n_gpu_layers={n_gpu}, n_ctx={ctx}) failed: {e}')
                            _llm = None

            if require_gpu and _llm is None:
                raise RuntimeError('GPU offload required but GPU initialization failed.')

            # Fallback: CPU only
            _llm = Llama(**build_kwargs(cpu_ctx, 0))
            _llm_n_ctx = cpu_ctx
            log.info(f'Model loaded on CPU: n_ctx={cpu_ctx}')
        finally:
            _llm_loading = False
    return _llm


def _check_crisis(text: str) -> bool:
    """Check if message contains crisis indicators."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in CRISIS_KEYWORDS)


@bp.route('/')
def chat():
    """Render the chat page."""
    # Load persistent chat history for display
    messages = ChatMessage.query.order_by(ChatMessage.created_at).all()
    history = [{'role': m.role, 'content': m.content} for m in messages]
    return render_template('assistant/chat.html', history=history)


@bp.route('/stream', methods=['POST'])
def stream():
    """Streaming endpoint: streams AI response token by token."""
    data = request.get_json(silent=True) or {}
    user_message = data.get('message', '').strip()

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
        try:
            llm = _get_llm()

            # Build context using multi-layer memory
            from .memory import assemble_context
            system = assemble_context(user_message)

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
            messages.append({'role': 'user', 'content': user_message})

            messages = _trim_messages_to_fit(llm, messages)

            max_tokens = _get_max_tokens()
            chat_kwargs = {
                'messages': messages,
                'stream': True,
                'temperature': 0.7,
            }
            if max_tokens is not None:
                chat_kwargs['max_tokens'] = max_tokens

            response = llm.create_chat_completion(**chat_kwargs)

            full_response = ''
            for chunk in response:
                delta = chunk['choices'][0].get('delta', {})
                token = delta.get('content', '')
                if token:
                    full_response += token
                    yield f'data: {json.dumps({"token": token})}\n\n'

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

            # Save assistant response to DB
            if full_response:
                db.session.add(ChatMessage(role='assistant', content=full_response))
                db.session.commit()

            yield 'data: [DONE]\n\n'

        except FileNotFoundError as e:
            yield f'data: {json.dumps({"error": str(e)})}\n\n'
            yield 'data: [DONE]\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"error": f"Model error: {e}"})}\n\n'
            yield 'data: [DONE]\n\n'

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
    import logging
    log = logging.getLogger(__name__)

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
    reindex_all_async(current_app._get_current_object())
    return jsonify({'status': 'started', 'message': 'Reindexing started in background'})


@bp.route('/reset-profile', methods=['POST'])
def reset_profile():
    """Delete the psychological profile so it gets rebuilt."""
    profile = UserPsychProfile.query.first()
    if profile:
        db.session.delete(profile)
        db.session.commit()
    return jsonify({'status': 'ok', 'message': 'Profile reset. It will rebuild on next entry.'})


@bp.route('/clear-chat', methods=['POST'])
def clear_chat():
    """Clear all chat history."""
    ChatMessage.query.delete()
    db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/status')
def status():
    """Return processing status for the UI."""
    total_entries = MoodEntry.query.count()
    from app.models import EntryEmbedding, EntrySummary
    embedded = EntryEmbedding.query.count()
    summarized = EntrySummary.query.count()
    profile = UserPsychProfile.query.first()

    return jsonify({
        'total_entries': total_entries,
        'embedded': embedded,
        'summarized': summarized,
        'profile_version': profile.version if profile else 0,
        'profile_entries_analyzed': profile.entries_analyzed if profile else 0,
        'llm_loading': _llm_loading,
    })
