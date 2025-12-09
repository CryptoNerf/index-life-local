"""
Entry point for local index.life diary application
Starts Flask server and opens browser automatically
"""
import webbrowser
from threading import Timer
import sys
import os
import logging

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
    """Configure logging to reduce Flask output noise"""
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
