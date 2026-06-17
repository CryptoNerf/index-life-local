"""Background analysis pipeline for the deep-mind module."""
import logging
import os
import threading
from app.timeutil import utcnow

log = logging.getLogger(__name__)

# Automatic analysis (fired after an entry save) is debounced: a full
# re-cluster plus an LLM rename of every topic costs minutes of model time,
# so redoing it on every single save is wasteful. An automatic run proceeds
# only once this many new entries have been added since the last completed
# run. We deliberately do NOT gate on elapsed time — with the typical
# one-entry-a-day use a time gate would fire a rebuild basically every day,
# which is the very waste this debounce exists to avoid. The manual
# "Analyze" button passes force=True to bypass the threshold. Env-tunable.
_MIN_NEW_ENTRIES = int(os.getenv('DEEP_MIND_MIN_NEW_ENTRIES', '5'))

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


def analyze_async(app, force: bool = False):
    """Spawn background thread for the full clustering + naming pipeline.

    `force=True` (the manual "Analyze" button) always runs. `force=False`
    (automatic, after an entry save) is debounced via `_should_auto_run`.
    """
    thread = threading.Thread(target=_run, args=(app,),
                              kwargs={'force': force}, daemon=True)
    thread.start()


def _run(app, force: bool = False):
    if not _lock.acquire(timeout=2):
        log.info('deep-mind analysis already running, skipping')
        return

    try:
        with app.app_context():
            # Debounce automatic runs. Checked inside the lock + context so
            # the gate read is consistent, and a skipped run never flips the
            # status to "running" (the UI keeps showing the last result).
            if not force and not _should_auto_run():
                log.info('deep-mind: auto-analysis debounced — skipping')
                return

            _set(running=True, stage='clustering', progress=5, error='')
            from .clustering import run_clustering_pipeline
            from .analysis import save_clusters_to_db
            from app.modules.assistant.routes import _get_llm

            _set(stage='clustering', progress=10)
            result = run_clustering_pipeline()
            n = len(result['clusters'])
            log.info('deep-mind: %d clusters from %d entries', n, result['total_entries'])

            if n == 0:
                _record_run()
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

            _record_run()
            _set(running=False, stage='done', progress=100,
                 clusters_found=len(saved),
                 clusters_visible=len(visible),
                 clusters_hidden=hidden,
                 last_run=_now())
            log.info('deep-mind analysis complete')

    except Exception as e:
        # Roll back any pending state from a failed commit so the session
        # is clean before teardown closes it. Without this, a partial
        # cluster INSERT can leave the SQLite write transaction half-open.
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass
        log.error('deep-mind analysis failed: %s', e, exc_info=True)
        _set(running=False, stage='error', progress=0, error=str(e))
    finally:
        _lock.release()


def _now():
    return utcnow().isoformat()


# ── Debounce bookkeeping (persisted in sync_meta, survives restart) ─────────

def _meta_get(key: str) -> str | None:
    from app import db
    from app.models import SyncMeta
    row = db.session.get(SyncMeta, key)
    return row.value if row else None


def _meta_set(key: str, value: str) -> None:
    from app import db
    from app.models import SyncMeta
    row = db.session.get(SyncMeta, key)
    if row:
        row.value = value
    else:
        db.session.add(SyncMeta(key=key, value=value))
    db.session.commit()


def _should_auto_run() -> bool:
    """Decide whether an automatic (non-forced) analysis is worth its cost.

    Purely count-based: proceeds only once at least _MIN_NEW_ENTRIES new
    non-deleted entries have been added since the last completed run. The
    first run (nothing recorded yet) always proceeds so the map populates
    immediately; the manual "Analyze" button bypasses the threshold with
    force=True.

    Must be called inside an app context. Any bookkeeping error fails open
    (returns True) so a metadata hiccup never permanently blocks the map
    from refreshing.
    """
    from app.models import MoodEntry
    try:
        current_count = MoodEntry.query.filter_by(deleted=False).count()
        recorded = _meta_get('deep_mind_last_analyze_count')
    except Exception:
        return True
    if recorded is None:
        return True  # never analysed on this install yet
    try:
        last_count = int(recorded)
    except (TypeError, ValueError):
        return True
    return (current_count - last_count) >= _MIN_NEW_ENTRIES


def _record_run() -> None:
    """Persist the entry count at this run for the debounce gate.

    Records the same metric `_should_auto_run` reads (non-deleted entry
    count) so the two stay in sync. Must run inside an app context; a write
    failure is logged but never aborts the analysis that just succeeded.
    """
    from app.models import MoodEntry
    try:
        count = MoodEntry.query.filter_by(deleted=False).count()
        _meta_set('deep_mind_last_analyze_count', str(count))
    except Exception as exc:
        log.warning('deep-mind: could not record analyze run: %s', exc)
