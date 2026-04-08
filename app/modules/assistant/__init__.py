"""AI Psychologist module using llama-cpp-python."""
import importlib.util
import sys
from flask import Blueprint

bp = Blueprint(
    'assistant',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/assistant/static'
)

REQUIRED_IMPORTS = [
    'llama_cpp',
    'sentence_transformers',
    'numpy',
]

# Package names on disk (dist-info directory prefixes)
_DIST_NAMES = {
    'llama_cpp': 'llama_cpp_python',
    'sentence_transformers': 'sentence_transformers',
    'numpy': 'numpy',
}


def check_dependencies():
    """Check if required packages are available.

    In frozen builds, native .so files may be compiled for a different
    Python ABI, so __import__() would crash even though the package is
    correctly installed.  We fall back to checking for the dist-info
    directory on sys.path instead.
    """
    missing = []
    for name in REQUIRED_IMPORTS:
        try:
            __import__(name)
        except (ImportError, OSError):
            # In frozen builds, check if the package directory exists on
            # sys.path even if we can't import its native extension
            if getattr(sys, 'frozen', False) and _find_package_on_path(name):
                continue
            missing.append(name)
    return missing


def _find_package_on_path(import_name: str) -> bool:
    """Check if a package directory or dist-info exists on sys.path."""
    from pathlib import Path
    dist_name = _DIST_NAMES.get(import_name, import_name)
    for p in sys.path:
        d = Path(p)
        if not d.is_dir():
            continue
        # Check for package directory (e.g. llama_cpp/)
        if (d / import_name).is_dir():
            return True
        # Check for dist-info (e.g. llama_cpp_python-0.3.20.dist-info/)
        if any(d.glob(f'{dist_name}-*.dist-info')):
            return True
    return False


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp, url_prefix='/assistant')
