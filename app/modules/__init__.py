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
    """Return user data directory (same logic as app/__init__.py)."""
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'index.life'
    elif sys.platform == 'win32':
        return Path(os.environ.get('APPDATA', str(Path.home()))) / 'index.life'
    return Path.home() / '.index-life'


def _add_local_modules_site_packages() -> None:
    """Allow optional module deps installed in a local venv to be discovered."""
    venv_raw = os.environ.get('INDEXLIFE_MODULES_VENV', '').strip()
    if getattr(sys, 'frozen', False):
        # Frozen builds store venv in user data dir, not inside .app bundle
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
                            'Module venv Python version %s.%s does not match app Python %s.%s. '
                            'Module deps may fail to import.',
                            major, minor, sys.version_info.major, sys.version_info.minor
                        )
        except Exception as exc:
            log.warning('Failed to inspect modules venv: %s', exc)

    # In frozen exe, PyInstaller bundles a stripped stdlib.  Heavy deps like
    # torch need modules that were excluded (pickletools, importlib.resources …).
    # Use pyvenv.cfg "home" key to find the system Python and add its stdlib.
    if getattr(sys, 'frozen', False) and cfg.exists():
        try:
            home_line = next(
                (l for l in cfg.read_text(encoding='utf-8', errors='ignore').splitlines()
                 if l.strip().lower().startswith('home')), ''
            )
            if home_line:
                _, home_val = home_line.split('=', 1)
                python_home = Path(home_val.strip())
                # pyvenv.cfg "home" points to the bin/ dir containing python exe.
                # Stdlib locations vary by platform:
                #   Windows:  home/../Lib/
                #   macOS:    home/../lib/python3.X/
                #   Linux:    home/../lib/python3.X/
                # Also check Homebrew Frameworks path on macOS.
                stdlib_found = False
                search_roots = [python_home.parent, python_home]

                # macOS Homebrew: Frameworks/Python.framework/Versions/3.X/lib/
                fw = python_home.parent / 'Frameworks' / 'Python.framework'
                if fw.is_dir():
                    for ver_dir in sorted(fw.glob('Versions/3.*'), reverse=True):
                        search_roots.insert(0, ver_dir)

                for root in search_roots:
                    # Windows: root/Lib
                    win_lib = root / 'Lib'
                    if win_lib.is_dir() and (win_lib / 'os.py').exists():
                        sys.path.insert(0, str(win_lib))
                        log.info('Added system stdlib: %s', win_lib)
                        stdlib_found = True
                        break
                    # Unix: root/lib/python3.X
                    for p in sorted(root.glob('lib/python3.*'), reverse=True):
                        if p.is_dir() and (p / 'os.py').exists():
                            sys.path.insert(0, str(p))
                            log.info('Added system stdlib: %s', p)
                            stdlib_found = True
                            break
                    if stdlib_found:
                        break

                if not stdlib_found:
                    log.warning('Could not find system stdlib from pyvenv.cfg home=%s', python_home)
        except Exception as exc:
            log.warning('Failed to add system stdlib: %s', exc)

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
