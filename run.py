"""
Entry point for local index.life diary application
Starts Flask server and opens browser automatically
"""
import webbrowser
from threading import Timer
import sys
import os
import logging

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


def open_browser():
    """Open browser after a short delay"""
    url = f'http://{Config.HOST}:{Config.PORT}'
    print(f"\n  [>] Opening browser at {url}\n")
    webbrowser.open(url)


def setup_logging():
    """Configure logging."""
    # In frozen builds, write logs to a file for debugging
    if getattr(sys, 'frozen', False):
        if sys.platform == 'darwin':
            log_dir = os.path.expanduser('~/Library/Application Support/index.life')
        elif sys.platform == 'win32':
            log_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'index.life')
        else:
            log_dir = os.path.expanduser('~/.index-life')
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

    # Disable Flask's default request logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)


def main():
    """Main entry point"""
    # Enable UTF-8 output for Windows console
    if sys.platform == 'win32':
        try:
            # Set console to UTF-8 mode
            os.system('chcp 65001 > nul')
            # Also set stdout encoding
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass
    # Print beautiful banner
    print(BANNER)
    print(f"  Version: {Config.APP_VERSION}")
    print(f"  Database: {os.path.basename(Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', ''))}")
    print(f"  Server: http://{Config.HOST}:{Config.PORT}")
    print(f"\n  {'─' * 68}")
    print(f"  Press Ctrl+C to stop the server")
    print(f"  {'─' * 68}\n")

    # Reduce Flask logging noise
    setup_logging()

    # Create Flask app
    app = create_app()

    # Open browser after 1.5 seconds
    if Config.AUTO_OPEN_BROWSER:
        Timer(1.5, open_browser).start()

    try:
        # Run Flask development server
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=Config.DEBUG,
            use_reloader=False  # Disable reloader to prevent double browser opening
        )
    except KeyboardInterrupt:
        print("\n\n[Shutdown] Shutting down server...")
        sys.exit(0)
    except Exception as e:
        print(f"\n[Error] Error starting server: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
