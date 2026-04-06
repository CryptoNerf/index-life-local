"""
Routes for the module status page.
Shows which modules are installed/available and how to install missing ones.
Supports in-app installation with live progress via SSE.
"""
import logging
import platform
import subprocess
import sys
import threading
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

# Global install state
_install_lock = threading.Lock()
_install_status = {
    'running': False,
    'module': None,
    'lines': [],
    'done': False,
    'success': False,
    'error': None,
}


def _detect_profile() -> str:
    """Auto-detect the best GPU profile for the current platform."""
    system = platform.system()
    arch = platform.machine()

    if system == 'Darwin' and arch == 'arm64':
        return 'metal'

    # Check for NVIDIA GPU
    import shutil
    if shutil.which('nvidia-smi'):
        return 'vulkan'  # pre-built, no SDK needed

    return 'cpu'


def _find_python() -> str:
    """Find the Python executable to use for module installation."""
    # In source context, use the same Python running Flask
    if not getattr(sys, 'frozen', False):
        return sys.executable

    # In EXE context, try to find system Python
    candidates = []
    if platform.system() == 'Darwin':
        candidates = [
            '/opt/homebrew/bin/python3.12',
            '/opt/homebrew/bin/python3.13',
            '/opt/homebrew/bin/python3',
            '/usr/local/bin/python3',
        ]
    elif platform.system() == 'Windows':
        candidates = [
            'py', 'python3', 'python',
        ]
    else:
        candidates = ['python3', 'python']

    import shutil
    for c in candidates:
        path = shutil.which(c)
        if path:
            return path

    return sys.executable


def _find_install_script() -> Path:
    """Locate tools/install_modules.py."""
    if getattr(sys, 'frozen', False):
        # EXE context
        base = Path(sys.executable).parent
        candidates = [
            base / '_internal' / 'tools' / 'install_modules.py',
            base / 'tools' / 'install_modules.py',
        ]
    else:
        # Source context
        from config import BASE_DIR
        candidates = [
            BASE_DIR / 'tools' / 'install_modules.py',
        ]

    for c in candidates:
        if c.exists():
            return c

    raise FileNotFoundError('install_modules.py not found')


def _get_install_instructions() -> dict:
    """Platform-specific install instructions."""
    system = platform.system()
    arch = platform.machine()

    if system == 'Darwin' and arch == 'arm64':
        return {
            'platform': 'macOS Apple Silicon',
            'method': 'Double-click "Install Modules.command" from the DMG or the app folder.',
            'alt': 'Or run in Terminal: bash install_macos_arm.sh',
        }
    elif system == 'Darwin':
        return {
            'platform': 'macOS Intel',
            'method': 'Run in Terminal: bash install.sh',
            'alt': None,
        }
    elif system == 'Windows':
        return {
            'platform': 'Windows',
            'method': 'Double-click "Install Modules.bat" next to the application.',
            'alt': 'Or run in PowerShell: python tools/install_modules.py --module assistant --module deep_mind',
        }
    else:
        return {
            'platform': f'{system} ({arch})',
            'method': 'Run: bash install.sh',
            'alt': 'Or: python tools/install_modules.py --module assistant --module deep_mind',
        }


@bp.route('/modules')
def modules_page():
    """Show module status and install instructions."""
    discovered = discover_modules()
    active = current_app.config.get('ACTIVE_MODULES', [])

    modules = []
    for name in discovered:
        info = MODULE_INFO.get(name, {})
        modules.append({
            'name': name,
            'title': info.get('title', name.replace('_', ' ').title()),
            'description': info.get('description', ''),
            'size': info.get('size', ''),
            'active': name in active,
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
            })

    install = _get_install_instructions()
    profile = _detect_profile()

    return render_template('modules.html',
                           modules=modules,
                           install=install,
                           install_running=_install_status['running'],
                           profile=profile,
                           current_year=date.today().year)


@bp.route('/modules/install', methods=['POST'])
def install_module_route():
    """Start installing a module. Returns immediately; progress via SSE."""
    global _install_status

    if _install_status['running']:
        return jsonify({'error': 'Installation already in progress'}), 409

    module_name = request.form.get('module', '').strip()
    if module_name not in MODULE_INFO:
        return jsonify({'error': f'Unknown module: {module_name}'}), 400

    profile = request.form.get('profile', 'auto')

    with _install_lock:
        _install_status = {
            'running': True,
            'module': module_name,
            'lines': [],
            'done': False,
            'success': False,
            'error': None,
        }

    # Run in background thread
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
        python = _find_python()
        script = _find_install_script()

        cmd = [python, str(script), '--module', module_name]
        if module_name == 'assistant':
            cmd += ['--profile', profile]

        _install_status['lines'].append(f'$ {" ".join(cmd)}\n')

        env = None
        # For Metal on macOS, set CMAKE flags
        if profile == 'metal':
            import os
            env = os.environ.copy()
            env['CMAKE_ARGS'] = env.get('CMAKE_ARGS', '') + ' -DGGML_METAL=on'
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

        _install_status['success'] = proc.returncode == 0
        if proc.returncode != 0:
            _install_status['error'] = f'Process exited with code {proc.returncode}'
            _install_status['lines'].append(f'\nInstallation failed (exit code {proc.returncode})\n')
        else:
            _install_status['lines'].append('\nInstallation complete! Restart the app to activate the module.\n')

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
    import time

    def generate():
        last_index = 0
        while True:
            lines = _install_status['lines']
            while last_index < len(lines):
                line = lines[last_index].rstrip('\n')
                yield f'data: {line}\n\n'
                last_index += 1

            if _install_status['done']:
                status = 'success' if _install_status['success'] else 'error'
                yield f'event: done\ndata: {status}\n\n'
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
def install_status():
    """JSON endpoint for polling install status."""
    return jsonify({
        'running': _install_status['running'],
        'module': _install_status['module'],
        'done': _install_status['done'],
        'success': _install_status['success'],
        'error': _install_status['error'],
        'line_count': len(_install_status['lines']),
    })
