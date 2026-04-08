"""
Routes for the module status page.
Shows which modules are installed/available and how to install missing ones.
Supports in-app installation with live progress via SSE.
"""
import importlib
import logging
import os
import platform
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
    use the same major.minor Python as the frozen app.  If the exact
    version isn't available we fall back to any Python 3.10+.
    """
    if not getattr(sys, 'frozen', False):
        return sys.executable

    # Version the frozen app was built with
    app_ver = f'{sys.version_info.major}.{sys.version_info.minor}'

    if platform.system() == 'Darwin':
        # Try exact version first (Homebrew, then system)
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

    # Warn if version doesn't match
    try:
        out = subprocess.check_output([found, '--version'], text=True, stderr=subprocess.STDOUT).strip()
        # "Python 3.12.13" → "3.12"
        ver = out.split()[-1].rsplit('.', 1)[0]
        if ver != app_ver:
            log.warning(
                'Found Python %s but app requires %s. '
                'Native modules may not load. Install: brew install python@%s',
                ver, app_ver, app_ver,
            )
    except Exception:
        pass

    return found


def _find_install_script() -> Path:
    """Locate tools/install_modules.py."""
    import logging
    _log = logging.getLogger(__name__)

    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable)
        exe_resolved = exe.resolve()  # resolve symlinks
        _log.info('_find_install_script: sys.executable=%s resolved=%s', exe, exe_resolved)

        candidates = []

        # Try sys._MEIPASS first (PyInstaller sets this)
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            mp = Path(meipass)
            candidates.append(mp / 'tools' / 'install_modules.py')
            candidates.append(mp / '_internal' / 'tools' / 'install_modules.py')

        # Resolved exe location (Contents/Frameworks/ on macOS after symlink resolve)
        for base in {exe_resolved.parent, exe.parent}:
            candidates.extend([
                base / '_internal' / 'tools' / 'install_modules.py',
                base / 'tools' / 'install_modules.py',
            ])

        # Walk up to Contents/ and check all subdirectories
        for base in {exe_resolved.parent, exe.parent}:
            contents = base.parent  # likely Contents/
            if contents.name == 'Contents' or contents.name == 'Frameworks':
                if contents.name == 'Frameworks':
                    contents = contents.parent
                for subdir in ('Frameworks', 'Resources', 'MacOS'):
                    d = contents / subdir
                    candidates.extend([
                        d / '_internal' / 'tools' / 'install_modules.py',
                        d / 'tools' / 'install_modules.py',
                    ])

        # Deduplicate while preserving order
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
            _log.info('_find_install_script: found at %s', c)
            return c

    # Log all checked paths for debugging
    checked = '\n'.join(f'  - {c}' for c in candidates)
    _log.error('_find_install_script: NOT FOUND. Checked:\n%s', checked)
    raise FileNotFoundError(f'install_modules.py not found. Checked:\n{checked}')


def _ensure_venv_on_path():
    """Add modules_venv site-packages to sys.path if not already there.

    This is needed when the venv was created *after* the app started
    (i.e. by the in-app installer).  create_app() adds it at startup,
    but if it didn't exist then, we must pick it up now.
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

    if sp and sp.is_dir() and str(sp) not in sys.path:
        sys.path.insert(0, str(sp))
        _site.addsitedir(str(sp))
        log.info('Added modules_venv to sys.path: %s', sp)


def _check_module_deps(module_name: str) -> list[str]:
    """Check if a module's dependencies are installed. Returns list of missing packages."""
    # Ensure freshly-created venv is visible to this process
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
    else:
        return {
            'platform': f'{system} ({arch})',
            'method': 'Run: python tools/install_modules.py --module assistant --profile auto',
        }


# ── Routes ────────────────────────────────────────────────────

@bp.route('/modules')
def modules_page():
    """Show module status and install instructions."""
    discovered = discover_modules()
    active = current_app.config.get('ACTIVE_MODULES', [])

    modules = []
    for name in discovered:
        info = MODULE_INFO.get(name, {})
        # Check if deps are installed but module isn't active (needs restart)
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
    global _install_status

    with _install_lock:
        if _install_status['running']:
            return jsonify({'error': 'Installation already in progress'}), 409

        module_name = request.form.get('module', '').strip()
        if module_name not in MODULE_INFO:
            return jsonify({'error': f'Unknown module: {module_name}'}), 400

        profile = request.form.get('profile', 'auto')

        _install_status = {
            'running': True,
            'module': module_name,
            'lines': [],
            'done': False,
            'success': False,
            'verified': False,
            'error': None,
        }

    thread = threading.Thread(
        target=_run_install,
        args=(module_name, profile),
        daemon=True,
    )
    thread.start()

    return jsonify({'started': True, 'module': module_name})


def _run_install(module_name: str, profile: str):
    """Run install_modules.py in a subprocess, capturing output line by line."""
    global _install_status

    try:
        if getattr(sys, 'frozen', False):
            _install_status['lines'].append(f'App executable: {sys.executable}\n')

        python = _find_python()
        script = _find_install_script()

        cmd = [python, str(script), '--module', module_name]
        if module_name == 'assistant':
            cmd += ['--profile', profile]

        _install_status['lines'].append(f'$ {" ".join(cmd)}\n')

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
            _install_status['lines'].append(line)

        proc.wait()

        if proc.returncode == 0:
            _install_status['success'] = True
            _install_status['verified'] = True
            _install_status['lines'].append('\nInstallation complete!\n')
            _install_status['lines'].append('Quit and reopen the application to activate the module.\n')
        else:
            _install_status['success'] = False
            _install_status['error'] = f'Process exited with code {proc.returncode}'
            _install_status['lines'].append(f'\nInstallation failed (exit code {proc.returncode})\n')
            _install_status['lines'].append('You can retry or use the manual install method.\n')

    except FileNotFoundError as exc:
        _install_status['success'] = False
        _install_status['error'] = str(exc)
        msg = str(exc)
        _install_status['lines'].append(f'\nError: {msg}\n')
        if 'python not found' in msg.lower():
            _install_status['lines'].append(
                'Python is required for module installation.\n'
                'Install Python 3.10+ from python.org or run: brew install python\n'
            )
        elif 'install_modules' in msg.lower():
            _install_status['lines'].append(
                'Install script not found in the application bundle.\n'
                'Try reinstalling the application or use the manual install method.\n'
            )
    except Exception as exc:
        _install_status['success'] = False
        _install_status['error'] = str(exc)
        _install_status['lines'].append(f'\nError: {exc}\n')
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
                # Escape newlines for SSE (each data line must be one SSE data field)
                line = lines[last_index].rstrip('\n').replace('\r', '')
                yield f'data: {line}\n\n'
                last_index += 1

            if _install_status['done']:
                if _install_status['verified']:
                    yield f'event: done\ndata: verified\n\n'
                elif _install_status['success']:
                    yield f'event: done\ndata: success\n\n'
                else:
                    yield f'event: done\ndata: error\n\n'
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
    # If ?lines=1, also include all buffered output lines
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
        time.sleep(0.5)  # let the response reach the browser
        if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
            # macOS .app: find the .app bundle path and reopen it
            exe = Path(sys.executable).resolve()
            # Walk up to find the .app directory
            app_path = exe
            while app_path.parent != app_path:
                if app_path.suffix == '.app':
                    break
                app_path = app_path.parent
            if app_path.suffix == '.app':
                subprocess.Popen(['open', '-n', str(app_path)])
        # Shut down the current process
        os.kill(os.getpid(), signal.SIGTERM)

    thread = threading.Thread(target=_do_restart, daemon=True)
    thread.start()
    return jsonify({'restarting': True})
