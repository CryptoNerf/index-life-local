"""
Entry point for local index.life diary application
Starts Flask server and opens browser automatically
"""
import webbrowser
from threading import Timer
import sys
import os

from app import create_app
from config import Config


def open_browser():
    """Open browser after a short delay"""
    url = f'http://{Config.HOST}:{Config.PORT}'
    print(f"\n[Browser] Opening browser at {url}")
    webbrowser.open(url)


def main():
    """Main entry point"""
    print("="*60)
    print(f"[Start] Starting {Config.APP_NAME} v{Config.APP_VERSION}")
    print("="*60)
    print(f"[DB] Database: {Config.SQLALCHEMY_DATABASE_URI}")
    print(f"[Server] Server: http://{Config.HOST}:{Config.PORT}")
    print("="*60)
    print("\n[Info] Press Ctrl+C to stop the server\n")

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
