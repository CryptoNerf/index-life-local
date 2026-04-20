"""
Routes for the module status page.
Shows which modules are installed/available and how to install missing ones.
Supports in-app installation with live progress via SSE.
"""
import importlib
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

from flask import (
    Blueprint, render_template, current_app, Response, request, jsonify, stream_with_context,
)

from app.modules import discover_modules

log = logging.getLogger(__name__)

bp = Blueprint('modules', __name__)

# Human-readable descriptions for each module
MODULE_INFO = {
    'insights': {
        'title': 'Insights',
        'description': 'Minimalist visualizations of your mood data — heatmaps, trends and more. Some charts require the AI Psychologist module.',
        'size': '—',
    },
    'assistant': {
        'title': 'AI Psychologist',
        'description': 'Chat with an AI psychologist that understands your diary entries. Uses Qwen3.5-9B model with local GPU inference.',
        'size': '~5 GB (model download)',
    },
    'voice': {
        'title': 'Voice Dictation',
        'description': 'Dictate diary entries with your voice. Uses Whisper speech recognition.',
        'size': '~1 GB (model download)',
    },
    'deep_mind': {
        'title': 'Neural Map',
        'description': 'Visualize emotional themes from your diary as a neural topic map.',
        'size': '~50 MB',
    },
}

# Maximum number of lines kept in terminal buffer (prevent memory bloat)
_MAX_LINES = 2000

# Regex to strip ANSI escape sequences from subprocess output
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

# Global install state — survives across requests
_install_lock = threading.Lock()
_install_status = {
    'running': False,
    'module': None,
    'lines': [],
    'done': False,
    'success': False,
    'verified': False,
    'error': None,
}


# ── Helpers ───────────────────────────────────────────────────

def _detect_profile() -> str:
    """Auto-detect the best GPU profile for the current platform."""
    if platform.system() == 'Darwin' and platform.machine() == 'arm64':
        return 'metal'
    if shutil.which('nvidia-smi'):
        return 'vulkan'
    return 'cpu'


def _find_python() -> str:
    """Find a Python executable matching the frozen app's version.

    Native extensions (.so/.dylib) are ABI-specific, so the venv must
    use the same major.minor Python as the frozen app.
    """
    if not getattr(sys, 'frozen', False):
        return sys.executable

    app_ver = f'{sys.version_info.major}.{sys.version_info.minor}'

    if platform.system() == 'Darwin':
        exact = [
            f'/opt/homebrew/bin/python{app_ver}',
            f'/usr/local/bin/python{app_ver}',
        ]
        fallback = [
            '/opt/homebrew/bin/python3.14',
            '/opt/homebrew/bin/python3.13',
            '/opt/homebrew/bin/python3.12',
            '/opt/homebrew/bin/python3.11',
            '/opt/homebrew/bin/python3.10',
            '/opt/homebrew/bin/python3',
            '/usr/local/bin/python3',
            '/usr/bin/python3',
        ]
        candidates = exact + [c for c in fallback if c not in exact]
    elif platform.system() == 'Windows':
        candidates = [f'python{app_ver}', 'py', 'python3', 'python']
    else:
        candidates = [f'python{app_ver}', 'python3', 'python']

    found = None
    for c in candidates:
        path = shutil.which(c)
        if path:
            found = path
            break

    if not found:
        raise FileNotFoundError(
            f'Python not found. Install Python {app_ver} from python.org '
            f'or via Homebrew (brew install python@{app_ver}).'
        )

    # Warn if version doesn't match (native .so won't load)
    try:
        out = subprocess.check_output(
            [found, '--version'], text=True, stderr=subprocess.STDOUT,
        ).strip()
        ver = out.split()[-1].rsplit('.', 1)[0]  # "Python 3.12.13" → "3.12"
        if ver != app_ver:
            log.warning(
                'Found Python %s but app was built with %s — '
                'native modules may not load.',
                ver, app_ver,
            )
    except Exception:
        pass

    return found


def _find_install_script() -> Path:
    """Locate tools/install_modules.py."""
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable)
        exe_resolved = exe.resolve()
        log.info('_find_install_script: exe=%s resolved=%s', exe, exe_resolved)

        candidates = []

        # sys._MEIPASS (PyInstaller data dir)
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            mp = Path(meipass)
            candidates.append(mp / 'tools' / 'install_modules.py')
            candidates.append(mp / '_internal' / 'tools' / 'install_modules.py')

        # Exe dir (both resolved and unresolved)
        for base in {exe_resolved.parent, exe.parent}:
            candidates.extend([
                base / '_internal' / 'tools' / 'install_modules.py',
                base / 'tools' / 'install_modules.py',
            ])

        # Walk up to Contents/ and check subdirs
        for base in {exe_resolved.parent, exe.parent}:
            contents = base.parent
            if contents.name in ('Contents', 'Frameworks', 'Resources'):
                if contents.name != 'Contents':
                    contents = contents.parent
                for subdir in ('Frameworks', 'Resources', 'MacOS'):
                    d = contents / subdir
                    candidates.extend([
                        d / '_internal' / 'tools' / 'install_modules.py',
                        d / 'tools' / 'install_modules.py',
                    ])

        # Deduplicate
        seen = set()
        unique = []
        for c in candidates:
            s = str(c)
            if s not in seen:
                seen.add(s)
                unique.append(c)
        candidates = unique
    else:
        from config import BASE_DIR
        candidates = [BASE_DIR / 'tools' / 'install_modules.py']

    for c in candidates:
        if c.exists():
            log.info('_find_install_script: found at %s', c)
            return c

    checked = '\n'.join(f'  - {c}' for c in candidates)
    log.error('_find_install_script: NOT FOUND.\n%s', checked)
    raise FileNotFoundError('Install script not found in the application bundle.')


def _ensure_venv_on_path():
    """Add modules_venv site-packages to sys.path if not already there.

    Also applies stdlib and frozen-package fixes needed for PyInstaller
    builds — identical to what create_app() does at startup, but callable
    mid-session after an install creates the venv.
    """
    import site as _site
    data_dir = current_app.config.get('DATA_DIR')
    if not data_dir:
        return
    modules_venv = Path(data_dir) / 'modules_venv'
    if not modules_venv.is_dir():
        return

    if sys.platform == 'win32':
        sp = modules_venv / 'Lib' / 'site-packages'
    else:
        lib_dir = modules_venv / 'lib'
        sp = None
        if lib_dir.is_dir():
            for d in sorted(lib_dir.iterdir(), reverse=True):
                candidate = d / 'site-packages'
                if candidate.is_dir():
                    sp = candidate
                    break

    if sp and sp.is_dir():
        if str(sp) not in sys.path:
            sys.path.insert(0, str(sp))
            _site.addsitedir(str(sp))
            log.info('Added modules_venv to sys.path: %s', sp)

        if getattr(sys, 'frozen', False):
            from app import _add_system_stdlib, _unfreeze_venv_packages
            _add_system_stdlib(modules_venv)
            _unfreeze_venv_packages(sp)


def _check_module_deps(module_name: str) -> list[str]:
    """Check if a module's dependencies are installed."""
    _ensure_venv_on_path()
    try:
        mod = importlib.import_module(f'app.modules.{module_name}')
        if hasattr(mod, 'check_dependencies'):
            return mod.check_dependencies() or []
    except Exception:
        pass
    return ['unknown']


def _get_install_instructions() -> dict:
    """Platform-specific manual install instructions."""
    system = platform.system()
    arch = platform.machine()

    if system == 'Darwin' and arch == 'arm64':
        return {
            'platform': 'macOS Apple Silicon',
            'method': 'Run in Terminal: bash install_macos_arm.sh',
        }
    elif system == 'Windows':
        return {
            'platform': 'Windows',
            'method': 'Run install_modules.bat next to the application.',
        }
    return {
        'platform': f'{system} ({arch})',
        'method': 'Run: python tools/install_modules.py --module assistant --profile auto',
    }


def _append_line(text: str):
    """Append a line to the install buffer, stripping ANSI codes and limiting size."""
    cleaned = _ANSI_RE.sub('', text)
    _install_status['lines'].append(cleaned)
    # Keep buffer bounded
    if len(_install_status['lines']) > _MAX_LINES:
        _install_status['lines'] = _install_status['lines'][-_MAX_LINES:]


# ── Routes ────────────────────────────────────────────────────

@bp.route('/modules')
def modules_page():
    """Show module status and install instructions."""
    discovered = discover_modules()
    active = current_app.config.get('ACTIVE_MODULES', [])

    modules = []
    for name in discovered:
        info = MODULE_INFO.get(name, {})
        deps_ok = len(_check_module_deps(name)) == 0
        modules.append({
            'name': name,
            'title': info.get('title', name.replace('_', ' ').title()),
            'description': info.get('description', ''),
            'size': info.get('size', ''),
            'active': name in active,
            'installed_needs_restart': deps_ok and name not in active,
        })

    # Add known modules not yet discovered (folder doesn't exist)
    for name, info in MODULE_INFO.items():
        if name not in discovered:
            modules.append({
                'name': name,
                'title': info.get('title', name),
                'description': info.get('description', ''),
                'size': info.get('size', ''),
                'active': False,
                'installed_needs_restart': False,
            })

    install = _get_install_instructions()
    profile = _detect_profile()

    return render_template('modules.html',
                           modules=modules,
                           install=install,
                           install_status=_install_status,
                           profile=profile,
                           current_year=date.today().year)


@bp.route('/modules/install', methods=['POST'])
def install_module_route():
    """Start installing a module. Returns immediately; progress via SSE."""
    with _install_lock:
        if _install_status['running']:
            return jsonify({'error': 'Installation already in progress'}), 409

        module_name = request.form.get('module', '').strip()
        if module_name not in MODULE_INFO:
            return jsonify({'error': f'Unknown module: {module_name}'}), 400

        profile = request.form.get('profile', 'auto')

        # Reset state inside the lock — no race with readers
        _install_status.update({
            'running': True,
            'module': module_name,
            'lines': [],
            'done': False,
            'success': False,
            'verified': False,
            'error': None,
        })

    thread = threading.Thread(
        target=_run_install,
        args=(module_name, profile),
        daemon=True,
    )
    thread.start()

    return jsonify({'started': True, 'module': module_name})


def _run_install(module_name: str, profile: str):
    """Run install_modules.py in a subprocess, capturing output line by line."""
    try:
        # Insights has no pip deps — just create a sentinel file.
        if module_name == 'insights':
            from app.modules.insights import sentinel_path
            p = sentinel_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('enabled\n')
            _append_line(f'Enabled insights module (sentinel: {p})\n')
            _install_status['success'] = True
            _install_status['verified'] = True
            _append_line('\nInstallation complete!\n')
            return

        if getattr(sys, 'frozen', False):
            _append_line(f'App executable: {sys.executable}\n')

        python = _find_python()
        script = _find_install_script()

        cmd = [python, str(script), '--module', module_name]
        if module_name == 'assistant':
            cmd += ['--profile', profile]

        _append_line(f'$ {" ".join(cmd)}\n')

        env = os.environ.copy()
        if profile == 'metal':
            cmake = env.get('CMAKE_ARGS', '').strip()
            if '-DGGML_METAL=on' not in cmake:
                cmake = (cmake + ' -DGGML_METAL=on').strip()
            env['CMAKE_ARGS'] = cmake
            env['FORCE_CMAKE'] = '1'

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        for line in proc.stdout:
            _append_line(line)

        proc.wait()

        if proc.returncode == 0:
            _install_status['success'] = True
            _install_status['verified'] = True
            _append_line('\nInstallation complete!\n')
        else:
            _install_status['success'] = False
            _install_status['error'] = f'Process exited with code {proc.returncode}'
            _append_line(f'\nInstallation failed (exit code {proc.returncode})\n')

    except FileNotFoundError as exc:
        _install_status['success'] = False
        _install_status['error'] = str(exc)
        msg = str(exc)
        _append_line(f'\nError: {msg}\n')
        if 'python not found' in msg.lower():
            _append_line(
                'Python is required for module installation.\n'
                'Install Python 3.10+ from python.org or run: brew install python\n'
            )
    except Exception as exc:
        _install_status['success'] = False
        _install_status['error'] = str(exc)
        _append_line(f'\nError: {exc}\n')
    finally:
        _install_status['done'] = True
        _install_status['running'] = False


@bp.route('/modules/install/stream')
def install_stream():
    """SSE endpoint — streams install output to the browser."""
    def generate():
        last_index = 0
        while True:
            lines = _install_status['lines']
            while last_index < len(lines):
                line = lines[last_index].rstrip('\n').replace('\r', '')
                yield f'data: {line}\n\n'
                last_index += 1

            if _install_status['done']:
                if _install_status['verified']:
                    yield 'event: done\ndata: verified\n\n'
                elif _install_status['success']:
                    yield 'event: done\ndata: success\n\n'
                else:
                    yield 'event: done\ndata: error\n\n'
                break

            time.sleep(0.3)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@bp.route('/modules/install/status')
def install_status_route():
    """JSON endpoint for polling install status."""
    include_lines = request.args.get('lines', '0') == '1'
    result = {
        'running': _install_status['running'],
        'module': _install_status['module'],
        'done': _install_status['done'],
        'success': _install_status['success'],
        'verified': _install_status['verified'],
        'error': _install_status['error'],
        'line_count': len(_install_status['lines']),
    }
    if include_lines:
        result['lines'] = _install_status['lines']
    return jsonify(result)


@bp.route('/modules/restart', methods=['POST'])
def restart_app():
    """Restart the application to activate newly installed modules."""
    import signal

    def _do_restart():
        time.sleep(0.5)  # let the HTTP response reach the browser
        frozen = getattr(sys, 'frozen', False)
        exe = Path(sys.executable).resolve()

        if sys.platform == 'darwin' and frozen:
            # Walk up to the .app bundle
            app_path = exe
            while app_path.parent != app_path:
                if app_path.suffix == '.app' and app_path.is_dir():
                    break
                app_path = app_path.parent
            if app_path.suffix == '.app':
                log.info('Restart: launching %s after 2s delay', app_path)
                # Wait for us to die before relaunching — avoids port conflict
                # on rebind.
                subprocess.Popen(
                    ['bash', '-c', f'sleep 2 && open "{app_path}"'],
                    start_new_session=True,
                )
            else:
                log.warning('Restart: could not find .app bundle from %s', exe)
        elif sys.platform == 'win32' and frozen:
            log.info('Restart: launching %s after 2s delay', exe)
            # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP so the child
            # survives parent termination and has no console ties.
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            cmd = f'timeout /t 2 /nobreak >nul & start "" "{exe}"'
            subprocess.Popen(
                cmd,
                shell=True,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )

        log.info('Restart: sending SIGTERM to pid %d', os.getpid())
        os.kill(os.getpid(), signal.SIGTERM)

    thread = threading.Thread(target=_do_restart, daemon=True)
    thread.start()
    return jsonify({'restarting': True})


@bp.route('/modules/reset', methods=['POST'])
def reset_modules():
    """Delete modules_venv so modules can be reinstalled from a clean state.

    Used as an escape hatch when an install is corrupted or the venv's
    Python version is incompatible. Downloaded AI models are preserved —
    only the Python environment is wiped.
    """
    with _install_lock:
        if _install_status['running']:
            return jsonify({'error': 'Install in progress — cannot reset now'}), 409

    data_dir = current_app.config.get('DATA_DIR')
    if not data_dir:
        return jsonify({'error': 'DATA_DIR not configured'}), 500

    venv = Path(data_dir) / 'modules_venv'
    if not venv.is_dir():
        return jsonify({'reset': True, 'existed': False})

    try:
        shutil.rmtree(venv)
        log.info('reset_modules: wiped %s', venv)
    except Exception as exc:
        log.error('reset_modules: failed to remove %s: %s', venv, exc)
        return jsonify({'error': f'Failed to remove venv: {exc}'}), 500

    return jsonify({'reset': True, 'existed': True})
