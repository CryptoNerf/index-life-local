"""Background analysis pipeline for the deep-mind module."""
import logging
import threading
from datetime import datetime

log = logging.getLogger(__name__)

_lock = threading.Lock()

_status = {
    'running': False,
    'stage': '',
    'progress': 0,
    'clusters_found': 0,
    'clusters_visible': 0,
    'clusters_hidden': 0,
    'last_run': None,
    'error': '',
}
_status_lock = threading.Lock()


def get_status():
    with _status_lock:
        return dict(_status)


def _set(**kwargs):
    with _status_lock:
        _status.update(kwargs)


def analyze_async(app):
    """Spawn background thread for the full clustering + naming pipeline."""
    thread = threading.Thread(target=_run, args=(app,), daemon=True)
    thread.start()


def _run(app):
    if not _lock.acquire(timeout=2):
        log.info('deep-mind analysis already running, skipping')
        return

    _set(running=True, stage='clustering', progress=5, error='')
    try:
        with app.app_context():
            from .clustering import run_clustering_pipeline
            from .analysis import save_clusters_to_db
            from app.modules.assistant.routes import _get_llm

            _set(stage='clustering', progress=10)
            result = run_clustering_pipeline()
            n = len(result['clusters'])
            log.info('deep-mind: %d clusters from %d entries', n, result['total_entries'])

            if n == 0:
                _set(running=False, stage='done', progress=100,
                     clusters_found=0, clusters_visible=0,
                     clusters_hidden=0, last_run=_now())
                return

            _set(stage='loading_llm', progress=20)
            llm = _get_llm()

            def on_progress(i, total):
                _set(stage=f'naming:{i}/{total}',
                     progress=25 + int(70 * i / total))

            _set(stage=f'naming:0/{n}', progress=25)
            saved = save_clusters_to_db(result, llm, progress_cb=on_progress)

            from .analysis import MIN_TOPIC_ENTRIES, _is_insufficient_label
            visible = [
                c for c in saved
                if (c.entry_count or 0) >= MIN_TOPIC_ENTRIES
                and not _is_insufficient_label(c.label)
            ]
            hidden = max(0, len(saved) - len(visible))

            _set(running=False, stage='done', progress=100,
                 clusters_found=len(saved),
                 clusters_visible=len(visible),
                 clusters_hidden=hidden,
                 last_run=_now())
            log.info('deep-mind analysis complete')

    except Exception as e:
        log.error('deep-mind analysis failed: %s', e, exc_info=True)
        _set(running=False, stage='error', progress=0, error=str(e))
    finally:
        _lock.release()


def _now():
    return datetime.utcnow().isoformat()
