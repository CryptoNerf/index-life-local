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


def setup_logging():
    """Configure logging."""
    if getattr(sys, 'frozen', False):
        # Use the same resolver as the rest of the app so logs end up next
        # to diary.db (portable on Windows, Application Support on macOS).
        from config import _resolve_data_dir
        log_dir = str(_resolve_data_dir())
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'index-life.log')
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format='%(asctime)s %(name)s %(levelname)s: %(message)s',
        )
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
    # Right now: save-file dialog for markdown export. WKWebView ignores
    # `Content-Disposition: attachment`, so without this bridge the
    # exported markdown would render inline with no way to go back.
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
        logging.getLogger(__name__).error(
            'Native window failed to start: %s', e, exc_info=True)
        import traceback
        print('\n[Error] Native window failed to start:', file=sys.stderr)
        traceback.print_exc()
        _browser_fallback(str(e))


if __name__ == '__main__':
    main()
