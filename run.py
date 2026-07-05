# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""
Entry point for local index.life diary application
Starts Flask server and opens a native WKWebView window (pywebview).
Falls back to browser if pywebview is not installed (dev mode without it).
"""
import sys
import os
import logging
import threading
import time

# Force PyInstaller to bundle these stdlib C extensions.
# They are needed by venv ML packages (torch needs cmath,
# sklearn needs ctypes.util, etc.) but nothing in our own code
# imports them, so PyInstaller would otherwise strip them.
import cmath as _cmath  # noqa: F401
import ctypes as _ctypes  # noqa: F401
import ctypes.util as _ctypes_util  # noqa: F401
import decimal as _decimal  # noqa: F401
import pickle as _pickle  # noqa: F401
import pickletools as _pickletools  # noqa: F401
import csv as _csv  # noqa: F401
import statistics as _statistics  # noqa: F401
import fractions as _fractions  # noqa: F401

from app import create_app
from config import Config


# ASCII Art Banner
BANNER = """

  ,,                    ,,                         ,,    ,,      ,...
  db                  `7MM                       `7MM    db    .d' ""
                        MM                         MM          dM`
`7MM  `7MMpMMMb.   ,M""bMM  .gP"Ya `7M'   `MF'     MM  `7MM   mMMmm.gP"Ya
  MM    MM    MM ,AP    MM ,M'   Yb  `VA ,V'       MM    MM    MM ,M'   Yb
  MM    MM    MM 8MI    MM 8M""""""    XMX         MM    MM    MM 8M""""""
  MM    MM    MM `Mb    MM YM.    ,  ,V' VA.  ,,   MM    MM    MM YM.    ,
.JMML..JMML  JMML.`Wbmd"MML.`Mbmmd'.AM.   .MA.db .JMML..JMML..JMML.`Mbmmd'

"""


# Keep the log bounded: it lives in the data dir and is copied into every
# backup, so an unrotated file would bloat both over months of use.
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


def _make_rotating_handler(log_file: str):
    """Build the rotating file handler used for the frozen-app log.

    encoding=utf-8 is required: the app logs Russian text and a GUI process
    launched from Finder/Explorer can have a non-UTF-8 locale, which would
    otherwise raise on the first write.
    """
    from logging.handlers import RotatingFileHandler
    handler = RotatingFileHandler(
        log_file, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(name)s %(levelname)s: %(message)s'))
    return handler


def setup_logging():
    """Configure logging."""
    if getattr(sys, 'frozen', False):
        from logging.handlers import RotatingFileHandler
        # Use the same resolver as the rest of the app so logs end up next
        # to diary.db (portable on Windows, Application Support on macOS).
        from config import _resolve_data_dir
        log_dir = str(_resolve_data_dir())
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'index-life.log')

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        # Guard so a second setup_logging() call can't stack handlers.
        if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            root.addHandler(_make_rotating_handler(log_file))

        logging.info('=== index.life starting (frozen) ===')
        logging.info('sys.executable: %s', sys.executable)
        logging.info('sys.frozen: %s', getattr(sys, 'frozen', False))
        logging.info('sys._MEIPASS: %s', getattr(sys, '_MEIPASS', 'not set'))

    # Suppress Flask request logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)


def _wait_for_flask(url: str, timeout: float = 15.0) -> bool:
    """Poll until Flask is accepting connections."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.15)
    return False


def _run_flask(app) -> None:
    """Run Flask server in a background daemon thread."""
    try:
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=False,
            use_reloader=False,
        )
    except Exception as exc:
        logging.getLogger(__name__).error('Flask thread error: %s', exc)


def _unblock_self() -> None:
    """Strip the 'Mark of the Web' from our own bundled files (Windows).

    Windows tags every file extracted from a downloaded .zip with a
    Zone.Identifier stream ("came from the internet"). .NET Framework then
    refuses to load such assemblies, so pywebview's pythonnet/WebView2 backend
    fails (RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize)
    and the app drops to a browser-style window. Removing the tag from our own
    files — the same thing `Unblock-File` does — lets the native window work
    with no action from the user.

    Frozen Windows builds only. Needs write access to the bundle (true for the
    portable layout). Guarded by a sentinel so it only scans once per extract.
    """
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return
    meipass = getattr(sys, '_MEIPASS', None)
    if not meipass or not os.path.isdir(meipass):
        return
    sentinel = os.path.join(meipass, '.motw_cleared')
    if os.path.exists(sentinel):
        return
    cleared = 0
    targets = [os.path.join(root, name)
               for root, _dirs, files in os.walk(meipass) for name in files]
    targets.append(sys.executable)
    for path in targets:
        try:
            os.remove(path + ':Zone.Identifier')
            cleared += 1
        except OSError:
            pass  # no Zone.Identifier on this file, or not removable
    try:
        with open(sentinel, 'w', encoding='utf-8') as fh:
            fh.write('1')
    except OSError:
        pass
    logging.getLogger(__name__).info(
        'MOTW unblock: cleared %d Zone.Identifier stream(s)', cleared)


def main():
    """Main entry point"""
    # Enable UTF-8 output for Windows console
    if sys.platform == 'win32':
        try:
            os.system('chcp 65001 > nul')
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    print(BANNER)
    print(f"  Version: {Config.APP_VERSION}")
    print(f"  Database: {os.path.basename(Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', ''))}")
    print(f"  Server: http://{Config.HOST}:{Config.PORT}")
    print(f"\n  {'─' * 68}")
    print(f"  Press Ctrl+C to stop the server")
    print(f"  {'─' * 68}\n")

    setup_logging()

    # Remove 'Mark of the Web' from our own files so pywebview's WebView2
    # backend can load (otherwise it fails and we fall back to a browser).
    _unblock_self()

    flask_app = create_app()

    # Use 127.0.0.1 explicitly for the webview URL — WKWebView can stall
    # on DNS resolution of "localhost" on some macOS configurations.
    server_url = f'http://127.0.0.1:{Config.PORT}'

    # Start Flask in a background daemon thread so the main thread
    # is free for the macOS UI run-loop (required by WKWebView / AppKit).
    flask_thread = threading.Thread(target=_run_flask, args=(flask_app,), daemon=True)
    flask_thread.start()

    # Give Flask a moment to bind the port before opening the window.
    if not _wait_for_flask(server_url):
        print('\n[Error] Flask did not start within timeout — check logs.')
        sys.exit(1)

    # --- Native window via pywebview (macOS WKWebView / Windows WebView2) ---
    try:
        import webview  # type: ignore
    except ImportError as e:
        logging.getLogger(__name__).error('pywebview import failed: %s', e)
        webview = None

    def _launch_app_mode_browser(url: str):
        """Open a chromeless 'app mode' window via Edge/Chrome.

        Looks like a native app (no tabs, no address bar) and uses the same
        Chromium/WebView2 engine — but needs no pywebview/pythonnet, so it
        works reliably on Windows where bundling pythonnet is fragile.
        Returns the Popen handle, or None if no suitable browser was found.
        """
        import shutil
        import subprocess
        import tempfile

        candidates: list[str] = []
        if sys.platform == 'win32':
            pf = os.environ.get('PROGRAMFILES', r'C:\Program Files')
            pf86 = os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')
            local = os.environ.get('LOCALAPPDATA', '')
            candidates = [
                os.path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                os.path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                os.path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
                os.path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            ]
            if local:
                candidates.append(os.path.join(local, 'Google', 'Chrome', 'Application', 'chrome.exe'))
        elif sys.platform == 'darwin':
            candidates = [
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
            ]
        else:  # linux
            for name in ('microsoft-edge', 'google-chrome', 'chromium', 'chromium-browser'):
                found = shutil.which(name)
                if found:
                    candidates.append(found)

        browser = next((c for c in candidates if c and os.path.exists(c)), None)
        if browser is None:
            for name in ('msedge', 'chrome', 'google-chrome', 'chromium'):
                found = shutil.which(name)
                if found:
                    browser = found
                    break
        if not browser:
            return None

        # Dedicated profile (in temp) so it opens a fresh standalone window
        # instead of merging into the user's existing browser session.
        profile_dir = os.path.join(tempfile.gettempdir(), 'index_life_app_window')
        try:
            return subprocess.Popen([
                browser,
                f'--app={url}',
                f'--user-data-dir={profile_dir}',
                '--no-first-run',
                '--no-default-browser-check',
            ])
        except Exception as exc:
            logging.getLogger(__name__).warning('app-mode browser failed: %s', exc)
            return None

    def _browser_fallback(reason: str | None = None):
        import webbrowser
        if reason:
            logging.getLogger(__name__).warning(
                'Native window unavailable, falling back: %s', reason)
            print(f"\n  [!] Native window unavailable: {reason}")

        # Prefer a chromeless app-mode window (looks native) over a plain tab.
        if _launch_app_mode_browser(server_url) is not None:
            logging.getLogger(__name__).info('Opened app-mode browser window')
            print(f"  [>] Opened app window at {server_url}\n")
        else:
            print(f"  [>] Opening browser at {server_url}\n")
            webbrowser.open(server_url)
        try:
            flask_thread.join()
        except KeyboardInterrupt:
            print('\n\n[Shutdown] Shutting down...')
            sys.exit(0)

    if webview is None:
        _browser_fallback('pywebview not installed')
        return

    import signal
    signal.signal(signal.SIGINT, lambda *_: os._exit(0))
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))

    # JS ↔ native bridge for things the WebView can't do on its own.
    # save_text_file       — Save dialog for exports (markdown / theme JSON).
    #                        WKWebView ignores Content-Disposition: attachment,
    #                        so without this the exported file renders inline
    #                        with no way to go back.
    # open_file_dialog     — Open dialog with extension filtering. The HTML
    #                        <input type="file" accept=...> filter routes
    #                        through UTType lookup, and not every extension
    #                        we care about (notably .woff / .woff2) has a
    #                        registered UTI on every macOS version — when
    #                        the lookup fails for any item, WKWebView
    #                        silently widens the dialog to "all files".
    #                        Going through Cocoa NSOpenPanel directly via
    #                        pywebview gives reliable filtering.
    class JsApi:
        def save_text_file(self, content: str, suggested_name: str) -> str | None:
            """Open native Save dialog; write `content` to the chosen path.
            Returns the resolved path on success, None when cancelled.
            """
            try:
                paths = window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=suggested_name or 'export.txt',
                )
                if not paths:
                    return None
                # pywebview returns either a single string or a list.
                target = paths[0] if isinstance(paths, (list, tuple)) else paths
                with open(target, 'w', encoding='utf-8') as f:
                    f.write(content)
                return str(target)
            except Exception as exc:
                logging.getLogger(__name__).error('save_text_file failed: %s', exc)
                return None

        def select_folder(self) -> str | None:
            """Open a native folder-picker; return the chosen path or None.

            Used by the sync page: cloud-client mirror paths are deep and
            obscure (~/Library/CloudStorage/...), so folders must be
            pickable, not typed. There is no browser fallback — a web page
            cannot read a filesystem path from a folder input — so the UI
            only shows the button when this bridge exists.
            """
            try:
                paths = window.create_file_dialog(webview.FOLDER_DIALOG)
                if not paths:
                    return None
                target = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(target)
            except Exception as exc:
                logging.getLogger(__name__).error('select_folder failed: %s', exc)
                return None

        def open_file_dialog(self, label: str, extensions: list[str],
                             max_bytes: int | None = None) -> dict | None:
            """Open native Open dialog filtered to `extensions`; return the
            picked file as `{ name, base64 }` so the caller can upload via
            the normal multipart POST endpoints without duplicating their
            validation / resize / hashing logic in Python.

            On cancel returns None. On size cap exceeded returns
            `{ 'error': '...' }` so the JS side can surface it inline.
            """
            try:
                # pywebview's file_types is a tuple of "Label (*.ext;*.ext)" strings.
                ext_pattern = ';'.join('*' + e if e.startswith('.') else '*.' + e
                                       for e in extensions)
                type_label = f'{label} ({ext_pattern})'
                paths = window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=False,
                    file_types=(type_label,),
                )
                if not paths:
                    return None
                path = paths[0] if isinstance(paths, (list, tuple)) else paths
                if max_bytes is not None:
                    try:
                        if os.path.getsize(path) > max_bytes:
                            mb = max_bytes // (1024 * 1024)
                            return {'error': f'File too large (max {mb} MB)'}
                    except OSError:
                        pass
                with open(path, 'rb') as f:
                    blob = f.read()
                import base64
                return {
                    'name': os.path.basename(path),
                    'base64': base64.b64encode(blob).decode('ascii'),
                }
            except Exception as exc:
                logging.getLogger(__name__).error('open_file_dialog failed: %s', exc)
                return None

    window = webview.create_window(
        'index.life',
        server_url,
        width=1280,
        height=800,
        min_size=(900, 600),
        easy_drag=False,
        text_select=True,
        js_api=JsApi(),
    )

    # Clean shutdown when user closes the window — avoids crash-prone
    # PyObjC cleanup on macOS. Only called on real user close, not errors.
    window.events.closing += lambda: os._exit(0)

    start_kwargs = {}
    if sys.platform == 'win32':
        # Force the WebView2/EdgeChromium backend so Windows uses the modern
        # engine and never silently falls back to the broken MSHTML (IE)
        # renderer. Requires the WebView2 Runtime (preinstalled on Windows 11;
        # Edge installs it on Windows 10). If it's missing, start() raises and
        # we drop to a real browser — a better experience than MSHTML.
        start_kwargs['gui'] = 'edgechromium'

    try:
        webview.start(**start_kwargs)
    except SystemExit:
        os._exit(0)
    except Exception as e:
        # On Windows pywebview needs pythonnet/WebView2, which often can't load
        # in a downloaded build — fall back to the app-mode window. Keep the
        # full traceback in the log file, but don't dump it to the console:
        # the app still opens fine via the fallback, so a scary wall of text
        # would only worry the user.
        logging.getLogger(__name__).warning(
            'Native window (pywebview) unavailable: %s', e, exc_info=True)
        _browser_fallback(str(e))


if __name__ == '__main__':
    main()
