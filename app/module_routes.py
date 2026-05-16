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

# Human-readable descriptions for each module.
# Title / description are translation KEYS (not literals) — resolved at
# render time via {{ t(mod.title) }} so a language toggle takes effect
# without restarting. Keep keys in sync with app/translations/*.json.
MODULE_INFO = {
    'graphics': {
        'title': 'modules.graphics.title',
        'description': 'modules.graphics.description',
        'size': '—',
    },
    'assistant': {
        'title': 'modules.assistant.title',
        'description': 'modules.assistant.description',
        'size': '~5 GB (model download)',
    },
    'deep_mind': {
        'title': 'modules.deep_mind.title',
        'description': 'modules.deep_mind.description',
        'size': '~50 MB',
        'requires': ['assistant'],
    },
    'customization': {
        'title': 'modules.customization.title',
        'description': 'modules.customization.description',
        'size': '—',
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


def _verify_python_version(path: str, app_ver: str) -> bool:
    """Return True if `path` is a Python interpreter whose major.minor == app_ver."""
    try:
        out = subprocess.check_output(
            [path, '--version'], text=True, stderr=subprocess.STDOUT, timeout=10,
        ).strip()
        ver = out.split()[-1].rsplit('.', 1)[0]  # "Python 3.12.13" → "3.12"
        return ver == app_ver
    except Exception:
        return False


# Known-good python.org installer URLs keyed by "major.minor".
# ABI compat is guaranteed across patch versions within the same minor,
# so the patch version here can lag the frozen app's patch without issue.
_PY_INSTALLER_URLS = {
    '3.12': {
        'patch': '3.12.8',
        'x64': 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe',
        'x86': 'https://www.python.org/ftp/python/3.12.8/python-3.12.8.exe',
    },
}


def _download_with_progress(url: str, dest: Path, label: str = '') -> None:
    """Download `url` to `dest`, emitting progress lines to the install buffer."""
    import urllib.request

    _append_line(f'Downloading {label or url}\n')
    last_pct = {'v': -1}

    def _hook(block_num, block_size, total_size):
        if total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(100, int(downloaded * 100 / total_size))
        if pct >= last_pct['v'] + 5 or pct == 100:
            mb_done = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            _append_line(f'  {pct:3d}%  {mb_done:.1f} / {mb_total:.1f} MB\n')
            last_pct['v'] = pct

    urllib.request.urlretrieve(url, str(dest), reporthook=_hook)


def _install_python_windows(app_ver: str) -> str | None:
    """Download and silently install Python matching app_ver on Windows.

    Streams progress to the install buffer so the UI terminal shows what's
    happening. Returns the path to the installed python.exe, or None if
    anything failed.
    """
    entry = _PY_INSTALLER_URLS.get(app_ver)
    if not entry:
        _append_line(f'No installer URL configured for Python {app_ver}\n')
        return None

    arch = 'x86'
    if os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() == 'AMD64':
        arch = 'x64'
    if os.environ.get('PROCESSOR_ARCHITEW6432', '').upper() == 'AMD64':
        arch = 'x64'

    url = entry.get(arch) or entry['x64']
    patch = entry['patch']

    _append_line(
        f'\nPython {app_ver} not found on this system. '
        f'Downloading Python {patch} installer ({arch})...\n'
    )

    import tempfile
    installer = Path(tempfile.gettempdir()) / url.rsplit('/', 1)[-1]

    try:
        _download_with_progress(url, installer, label=f'Python {patch} ({arch})')
    except Exception as exc:
        _append_line(f'Download failed: {exc}\n')
        return None

    if not installer.exists() or installer.stat().st_size < 1_000_000:
        _append_line('Downloaded installer is missing or too small; aborting.\n')
        return None

    _append_line(f'\nRunning Python {patch} installer silently (this may take a minute)...\n')
    try:
        result = subprocess.run(
            [
                str(installer),
                '/quiet',
                'PrependPath=1',
                'Include_test=0',
                'InstallAllUsers=0',
                'Include_pip=1',
                'Include_launcher=1',
            ],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            _append_line(f'Installer exited with code {result.returncode}\n')
            if result.stdout:
                _append_line(result.stdout + '\n')
            if result.stderr:
                _append_line(result.stderr + '\n')
            return None
    except Exception as exc:
        _append_line(f'Installer failed: {exc}\n')
        return None
    finally:
        try:
            installer.unlink()
        except Exception:
            pass

    _append_line(f'Python {patch} installed successfully.\n\n')

    # PATH in this process won't pick up the new install — check the
    # well-known per-user install location directly.
    app_major, app_minor = app_ver.split('.')
    candidates = [
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Python'
        / f'Python{app_major}{app_minor}' / 'python.exe',
        Path(f'C:/Python{app_major}{app_minor}/python.exe'),
        Path(f'C:/Program Files/Python{app_major}{app_minor}/python.exe'),
    ]
    for p in candidates:
        if p.exists() and _verify_python_version(str(p), app_ver):
            _append_line(f'Located interpreter: {p}\n')
            return str(p)

    # Fallback: the py launcher may have been registered.
    py_launcher = shutil.which('py')
    if py_launcher:
        try:
            resolved = subprocess.check_output(
                [py_launcher, f'-{app_ver}', '-c',
                 'import sys;print(sys.executable)'],
                text=True, stderr=subprocess.DEVNULL, timeout=10,
            ).strip()
            if resolved and Path(resolved).exists() and \
                    _verify_python_version(resolved, app_ver):
                _append_line(f'Located interpreter via py launcher: {resolved}\n')
                return resolved
        except Exception:
            pass

    _append_line(
        'Installation reported success but python.exe could not be located.\n'
    )
    return None


def _find_python() -> str:
    """Find a Python executable matching the frozen app's version exactly.

    Native extensions (.so/.dylib/.pyd) are ABI-specific, so the venv
    must use the SAME major.minor Python as the frozen app. On Windows
    this means resolving `py` launcher with `-<version>` rather than just
    invoking the launcher default.
    """
    if not getattr(sys, 'frozen', False):
        return sys.executable

    app_ver = f'{sys.version_info.major}.{sys.version_info.minor}'  # e.g. "3.12"

    if platform.system() == 'Darwin':
        candidates = [
            f'/opt/homebrew/bin/python{app_ver}',
            f'/usr/local/bin/python{app_ver}',
        ]
        for c in candidates:
            if Path(c).exists() and _verify_python_version(c, app_ver):
                return c
        # Fallback: let shutil.which find anything matching the major.minor
        p = shutil.which(f'python{app_ver}')
        if p and _verify_python_version(p, app_ver):
            return p
        raise FileNotFoundError(
            f'Python {app_ver} not found. Install it via '
            f'`brew install python@{app_ver}` and retry.'
        )

    if platform.system() == 'Windows':
        # 1. Try `py -<ver>` launcher (most reliable on Windows — resolves
        #    to the specific registered interpreter regardless of PATH).
        py_launcher = shutil.which('py')
        if py_launcher:
            try:
                resolved = subprocess.check_output(
                    [py_launcher, f'-{app_ver}', '-c',
                     'import sys;print(sys.executable)'],
                    text=True, stderr=subprocess.DEVNULL, timeout=10,
                ).strip()
                if resolved and Path(resolved).exists() and \
                        _verify_python_version(resolved, app_ver):
                    return resolved
            except Exception:
                pass

        # 2. Direct `python3.12` in PATH
        direct = shutil.which(f'python{app_ver}')
        if direct and _verify_python_version(direct, app_ver):
            return direct

        # 3. Known install locations
        import os as _os
        app_major, app_minor = sys.version_info.major, sys.version_info.minor
        known_paths = [
            Path(_os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Python'
            / f'Python{app_major}{app_minor}' / 'python.exe',
            Path(f'C:/Python{app_major}{app_minor}/python.exe'),
            Path(f'C:/Program Files/Python{app_major}{app_minor}/python.exe'),
        ]
        for p in known_paths:
            if p.exists() and _verify_python_version(str(p), app_ver):
                return str(p)

        # 4. Not found anywhere — try an automatic install from python.org.
        installed = _install_python_windows(app_ver)
        if installed:
            return installed

        raise FileNotFoundError(
            f'Python {app_ver} is required but not found, and the automatic '
            f'installer failed. Install it from '
            f'https://www.python.org/downloads/release/python-3128/ '
            f'(check "Add to PATH"), then try again.'
        )

    # Linux / other
    for c in [f'python{app_ver}', 'python3', 'python']:
        path = shutil.which(c)
        if path and _verify_python_version(path, app_ver):
            return path
    raise FileNotFoundError(
        f'Python {app_ver} not found. Install it via your package manager '
        f'(e.g. `apt install python{app_ver}`) and retry.'
    )


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

    def _unmet(info: dict) -> list[str]:
        return [r for r in info.get('requires', []) if r not in active]

    def _labels(names: list[str]) -> list[str]:
        return [MODULE_INFO.get(r, {}).get('title', r) for r in names]

    modules = []
    for name in discovered:
        # Hide modules not registered in MODULE_INFO — lets us take a
        # module out of circulation without deleting its code.
        if name not in MODULE_INFO:
            continue
        info = MODULE_INFO[name]
        deps_ok = len(_check_module_deps(name)) == 0
        unmet = _unmet(info)
        modules.append({
            'name': name,
            'title': info.get('title', name.replace('_', ' ').title()),
            'description': info.get('description', ''),
            'size': info.get('size', ''),
            'active': name in active,
            'installed_needs_restart': deps_ok and name not in active,
            'unmet_requires': unmet,
            'requires_labels': _labels(unmet),
        })

    # Add known modules not yet discovered (folder doesn't exist)
    for name, info in MODULE_INFO.items():
        if name not in discovered:
            unmet = _unmet(info)
            modules.append({
                'name': name,
                'title': info.get('title', name),
                'description': info.get('description', ''),
                'size': info.get('size', ''),
                'active': False,
                'installed_needs_restart': False,
                'unmet_requires': unmet,
                'requires_labels': _labels(unmet),
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

        # Module-level dependencies: refuse install when a required module
        # isn't currently active. Prevents users from installing deep_mind
        # (which needs assistant's LLM at runtime) before assistant.
        active_mods = current_app.config.get('ACTIVE_MODULES', [])
        requires = MODULE_INFO[module_name].get('requires', [])
        unmet = [r for r in requires if r not in active_mods]
        if unmet:
            labels = [MODULE_INFO.get(r, {}).get('title', r) for r in unmet]
            return jsonify({
                'error': f'Requires active module(s): {", ".join(labels)}'
            }), 400

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
        # Sentinel-only modules (no pip deps) — just create the marker file.
        if module_name in ('graphics', 'customization'):
            from importlib import import_module
            mod = import_module(f'app.modules.{module_name}')
            p = mod.sentinel_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('enabled\n')
            _append_line(f'Enabled {module_name} module (sentinel: {p})\n')
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

        # Force UTF-8 for the child's stdout/stderr. Without this, piped
        # Python on Windows picks the ANSI codepage (e.g. cp1251 on RU
        # systems) and any non-ASCII character in install output crashes
        # the script with UnicodeEncodeError.
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            env=env,
        )

        for line in proc.stdout:
            _append_line(line)

        proc.wait()

        if proc.returncode == 0:
            # Sentinel-gated modules need explicit activation after pip
            # succeeds — without it, deep_mind would auto-activate whenever
            # assistant's transitive deps (numpy/sklearn) are present.
            if module_name == 'deep_mind':
                try:
                    from app.modules.deep_mind import sentinel_path
                    p = sentinel_path()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text('enabled\n')
                    _append_line(f'Activated deep_mind (sentinel: {p})\n')
                except Exception as exc:
                    _append_line(f'Warning: could not activate deep_mind: {exc}\n')

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
        return jsonify({'reset': True, 'existed': True})
    except Exception as rm_exc:
        # Windows: .pyd files loaded by the current process (e.g. hf_xet,
        # numpy) hold a lock and can't be deleted. Renaming the parent
        # folder still works, and the stale dir will be removed at the
        # next app start (see _cleanup_stale_modules_venv in app/__init__.py).
        import time as _time
        stale = venv.with_name(f'modules_venv.stale-{int(_time.time())}')
        try:
            venv.rename(stale)
            log.info('reset_modules: renamed %s -> %s (pending delete on restart)',
                     venv, stale)
            return jsonify({
                'reset': True,
                'existed': True,
                'deferred': True,
                'message': (
                    'Modules environment is in use by the running app and will '
                    'be cleaned up on the next restart. Please restart the app '
                    'now to complete the reset.'
                ),
            })
        except Exception as mv_exc:
            # Even rename failed — Windows is holding the folder very tightly
            # (DLLs mapped + AV scanning + open handles deep inside). Last
            # resort: drop a sentinel so the next app start wipes the venv
            # BEFORE any module is imported and DLLs locked again.
            log.warning('reset_modules: rmtree failed (%s) and rename failed (%s); deferring to startup',
                        rm_exc, mv_exc)
            sentinel = Path(data_dir) / 'modules_venv_reset_pending'
            try:
                sentinel.write_text('1', encoding='utf-8')
            except Exception as sw_exc:
                log.error('reset_modules: could not write reset sentinel: %s', sw_exc)
                return jsonify({
                    'error': f'Could not reset modules_venv: {rm_exc}. '
                             f'Restart the application and try again.'
                }), 500
            return jsonify({
                'reset': True,
                'existed': True,
                'deferred': True,
                'message': (
                    "Modules environment is in use by Windows (DLLs are "
                    "loaded). Please CLOSE the application completely and "
                    "open it again — the cleanup will finish automatically "
                    "on the next start. Then you can reinstall the module."
                ),
            })
