"""
Lightweight update checker — compares local version against the latest GitHub release.
Non-blocking: runs in a background thread, sets a flag in app.config if newer version exists.
"""
import logging
import threading
import urllib.request
import json

log = logging.getLogger(__name__)

GITHUB_REPO = 'CryptoNerf/index-life-local'
RELEASES_URL = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'


def _parse_version(tag: str) -> tuple:
    """Convert 'v2.1.0' or '2.1.0' into (2, 1, 0) for comparison."""
    tag = tag.lstrip('vV')
    parts = []
    for p in tag.split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_update(app) -> None:
    """Fetch latest release from GitHub and set UPDATE_AVAILABLE in app.config."""
    def _run():
        try:
            req = urllib.request.Request(
                RELEASES_URL,
                headers={'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'index.life-updater'}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            remote_tag = data.get('tag_name', '')
            local_version = app.config.get('APP_VERSION', '0.0.0')

            if _parse_version(remote_tag) > _parse_version(local_version):
                release_url = data.get('html_url', f'https://github.com/{GITHUB_REPO}/releases/latest')
                app.config['UPDATE_AVAILABLE'] = {
                    'version': remote_tag.lstrip('vV'),
                    'url': release_url,
                }
                log.info('Update available: %s → %s', local_version, remote_tag)
            else:
                app.config['UPDATE_AVAILABLE'] = None
        except Exception as exc:
            log.debug('Update check failed (non-critical): %s', exc)
            app.config['UPDATE_AVAILABLE'] = None

    t = threading.Thread(target=_run, daemon=True)
    t.start()
