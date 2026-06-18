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


def _get_user_data_dir() -> Path:
    """Return the user data directory — the single resolver in paths.py.

    This used to be a second copy of config.py's logic that had drifted in
    the source (non-frozen) case (it returned the platform app-data dir
    where config returned the repo root). It now delegates so the two can't
    diverge again.
    """
    from paths import user_data_dir
    return user_data_dir()


def _add_local_modules_site_packages() -> None:
    """Allow optional module deps installed in a local venv to be discovered."""
    venv_raw = os.environ.get('INDEXLIFE_MODULES_VENV', '').strip()
    if getattr(sys, 'frozen', False):
        base_dir = _get_user_data_dir()
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
                            'Module venv Python %s.%s != app Python %s.%s — '
                            'skipping venv (user must reinstall modules).',
                            major, minor, sys.version_info.major, sys.version_info.minor
                        )
                        return
        except Exception as exc:
            log.warning('Failed to inspect modules venv: %s', exc)

    # In a frozen exe PyInstaller ships a stripped stdlib; heavy module deps
    # (torch, diskcache, …) need what it dropped. Prepend the system stdlib
    # located from the venv's pyvenv.cfg via the shared helper. We INSERT(0)
    # here; the app factory APPENDS instead (see app/__init__._add_system_stdlib).
    if getattr(sys, 'frozen', False):
        from paths import find_system_stdlib
        stdlib = find_system_stdlib(venv_dir)
        if stdlib is not None:
            sys.path.insert(0, str(stdlib))
            log.info('Added system stdlib: %s', stdlib)
        else:
            log.warning('Could not find system stdlib for %s', venv_dir)

    candidates = []
    win_site = venv_dir / 'Lib' / 'site-packages'
    if win_site.exists():
        candidates.append(win_site)
    for path in venv_dir.glob('lib/python*/site-packages'):
        if path.exists():
            candidates.append(path)

    for sp in candidates:
        site.addsitedir(str(sp))


def check_packages_in_venv(package_names: list[str]) -> list[str]:
    """Check if packages exist in the modules_venv site-packages (frozen builds).

    Returns list of missing package names.  Uses file-system checks only —
    no imports — to avoid triggering heavy import chains that conflict
    with PyInstaller's FrozenImporter.
    """
    data_dir = _get_user_data_dir()
    venv = data_dir / 'modules_venv'
    if not venv.is_dir():
        return list(package_names)

    # If the venv was built against a different Python minor version, its C
    # extensions (numpy, llama_cpp, torch) won't load in this interpreter.
    # Treat all modules as missing so the user is prompted to reinstall.
    cfg = venv / 'pyvenv.cfg'
    if cfg.exists():
        try:
            for line in cfg.read_text(encoding='utf-8', errors='ignore').splitlines():
                if line.strip().lower().startswith('version'):
                    _, val = line.split('=', 1)
                    parts = val.strip().split('.')
                    if len(parts) >= 2:
                        vmaj, vmin = int(parts[0]), int(parts[1])
                        if (vmaj, vmin) != (sys.version_info.major, sys.version_info.minor):
                            log.warning(
                                'modules_venv Python %d.%d != app Python %d.%d — '
                                'treating modules as needing reinstall',
                                vmaj, vmin, sys.version_info.major, sys.version_info.minor,
                            )
                            return list(package_names)
                    break
        except Exception as exc:
            log.warning('Failed to read modules_venv pyvenv.cfg: %s', exc)

    sp = None
    lib_dir = venv / 'lib'
    if lib_dir.is_dir():
        for d in sorted(lib_dir.iterdir(), reverse=True):
            candidate = d / 'site-packages'
            if candidate.is_dir():
                sp = candidate
                break
    if sp is None:
        sp = venv / 'Lib' / 'site-packages'
    if not sp.is_dir():
        return list(package_names)

    missing = []
    for name in package_names:
        pkg_dir = sp / name
        has_dir = pkg_dir.is_dir()
        has_file = (sp / f'{name}.py').exists()
        # Handle dashes vs underscores in dist-info names
        has_dist = any(sp.glob(f'{name.replace("_", "[-_]")}*dist-info'))
        if not (has_dir or has_file or has_dist):
            log.info('check_packages_in_venv: %s NOT found in %s', name, sp)
            missing.append(name)
    return missing


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
