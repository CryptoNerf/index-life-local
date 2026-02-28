"""
Module discovery and registration.
A module is detected by folder presence under app/modules/.
Each module must have __init__.py with init_app(app) function.
"""
import importlib
import logging
import os
import site
import sys
from pathlib import Path

MODULES_DIR = Path(__file__).parent
log = logging.getLogger(__name__)


def _add_local_modules_site_packages() -> None:
    """Allow optional module deps installed in a local venv to be discovered."""
    venv_raw = os.environ.get('INDEXLIFE_MODULES_VENV', '').strip()
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = MODULES_DIR.parent.parent

    venv_dir = Path(venv_raw) if venv_raw else (base_dir / 'modules_venv')
    if not venv_dir.exists():
        return

    cfg = venv_dir / 'pyvenv.cfg'
    if cfg.exists():
        try:
            content = cfg.read_text(encoding='utf-8', errors='ignore').splitlines()
            version_line = next((line for line in content if line.lower().startswith('version')), '')
            if version_line:
                _, value = version_line.split('=', 1)
                parts = value.strip().split('.')
                if len(parts) >= 2:
                    major = int(parts[0])
                    minor = int(parts[1])
                    if (major, minor) != (sys.version_info.major, sys.version_info.minor):
                        log.warning(
                            'Module venv Python version %s.%s does not match app Python %s.%s. '
                            'Module deps may fail to import.',
                            major, minor, sys.version_info.major, sys.version_info.minor
                        )
        except Exception as exc:
            log.warning('Failed to inspect modules venv: %s', exc)

    candidates = []
    win_site = venv_dir / 'Lib' / 'site-packages'
    if win_site.exists():
        candidates.append(win_site)
    for path in venv_dir.glob('lib/python*/site-packages'):
        if path.exists():
            candidates.append(path)

    for sp in candidates:
        site.addsitedir(str(sp))


def discover_modules():
    """Return list of module names whose folders exist."""
    found = []
    for module_path in MODULES_DIR.iterdir():
        if not module_path.is_dir():
            continue
        name = module_path.name
        if name.startswith('_'):
            continue
        if name == '__pycache__':
            continue
        init_path = module_path / '__init__.py'
        if init_path.exists():
            found.append(name)
    return sorted(found)


def register_modules(app):
    """Import and register each discovered module."""
    _add_local_modules_site_packages()
    discovered = discover_modules()
    active = []

    for name in discovered:
        try:
            mod = importlib.import_module(f'app.modules.{name}')
        except ImportError as e:
            app.logger.warning(
                f'Module "{name}" folder found but could not import: {e}. '
                f'Install its dependencies: pip install -r app/modules/{name}/requirements.txt '
                'or run install_modules.'
            )
            continue
        except Exception as e:
            app.logger.error(f'Module "{name}" failed to import: {e}')
            continue

        if hasattr(mod, 'check_dependencies'):
            try:
                missing = mod.check_dependencies() or []
            except Exception as e:
                app.logger.error(f'Module "{name}" dependency check failed: {e}')
                continue

            if missing:
                missing_list = ', '.join(missing)
                app.logger.warning(
                    f'Module "{name}" dependencies missing: {missing_list}. '
                    f'Install via: pip install -r app/modules/{name}/requirements.txt '
                    'or run install_modules.'
                )
                continue

        try:
            mod.init_app(app)
            active.append(name)
            app.logger.info(f'Module loaded: {name}')
        except ImportError as e:
            app.logger.warning(
                f'Module "{name}" folder found but could not import: {e}. '
                f'Install its dependencies: pip install -r app/modules/{name}/requirements.txt '
                'or run install_modules.'
            )
        except Exception as e:
            app.logger.error(f'Module "{name}" failed to initialize: {e}')

    app.config['ACTIVE_MODULES'] = active
