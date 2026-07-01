"""
Background processing for new diary entries.
Runs embedding, summarization, and profile updates in a separate thread.
"""
import logging
import os
import threading
import time

from app import db
from app.models import MoodEntry, EntrySummary, EntryPerson, EntryActivity

log = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, ''))
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


# Background extraction is deliberately gentle so a fresh launch — or a DB with
# many unprocessed entries — never pegs the CPU and freezes the laptop:
#   • it waits a few seconds after launch so the window/UI come up first;
#   • it pauses between entries, giving the OS/UI headroom between LLM calls.
# The chat LLM keeps all of its threads, so this throttling does NOT slow the
# AI psychologist — only the off-screen backfill. Both knobs are env-tunable.
def _backfill_start_delay() -> float:
    return _env_float('ASSISTANT_BACKFILL_DELAY', 8.0)


def _extract_yield() -> float:
    return _env_float('ASSISTANT_EXTRACT_YIELD', 0.3)

_lock = threading.Lock()
_reindex_state_lock = threading.Lock()
_reindex_in_progress = False
_reindex_status = {
    'running': False,
    'phase': '',
    'current': 0,
    'total': 0,
    'message': '',
    'error': '',
    'started_at': None,
    'updated_at': None,
}


def _set_reindex_status(**updates):
    with _reindex_state_lock:
        for key, value in updates.items():
            if key in _reindex_status:
                _reindex_status[key] = value
        _reindex_status['updated_at'] = time.time()


def get_reindex_status():
    with _reindex_state_lock:
        return dict(_reindex_status)


# ── Sync (missing-only) progress ────────────────────────────────
# Mirrors _reindex_status so the UI can poll the same way. `embedded` /
# `summarized` count successful writes; `failed` counts entries where
# either step raised. `errors` keeps the most recent few failure messages
# so the user can see what went wrong without opening the terminal.
_sync_state_lock = threading.Lock()
_sync_status = {
    'running': False,
    'phase': '',           # scanning | processing | done | done_with_errors | error
    'current': 0,
    'total': 0,
    'embedded': 0,
    'summarized': 0,
    'failed': 0,
    'errors': [],          # last 5 short messages
    'message': '',
    'started_at': None,
    'updated_at': None,
}


def _set_sync_status(**updates):
    with _sync_state_lock:
        for key, value in updates.items():
            if key in _sync_status:
                _sync_status[key] = value
        _sync_status['updated_at'] = time.time()


def get_sync_status():
    with _sync_state_lock:
        return dict(_sync_status)


def process_entry_async(app, entry_id: int):
    """Spawn a background thread to process a new/updated entry."""
    thread = threading.Thread(
        target=_process_entry,
        args=(app, entry_id),
        daemon=True,
    )
    thread.start()


def reindex_all_async(app) -> bool:
    """Spawn a background thread to reindex all entries from scratch."""
    global _reindex_in_progress
    with _reindex_state_lock:
        if _reindex_in_progress:
            log.warning('Reindex already running, skipping.')
            return False
        _reindex_in_progress = True
        _reindex_status['running'] = True
        _reindex_status['phase'] = 'starting'
        _reindex_status['current'] = 0
        _reindex_status['total'] = 0
        _reindex_status['message'] = 'Reindex queued'
        _reindex_status['error'] = ''
        _reindex_status['started_at'] = time.time()
        _reindex_status['updated_at'] = time.time()

    thread = threading.Thread(
        target=_reindex_all,
        args=(app,),
        daemon=True,
    )
    thread.start()
    return True


def warmup_async(app):
    """Warm up models in a background thread."""
    thread = threading.Thread(
        target=_warmup,
        args=(app,),
        daemon=True,
    )
    thread.start()


# ── Per-chart re-extraction status ─────────────────────────────────
# Lightweight progress dicts so the chart pages can poll re-extraction
# progress without depending on _reindex_status (which is reserved for
# the full assistant reindex). Single-user app — no race protection.
_people_extract_status = {'running': False, 'processed': 0, 'total': 0, 'started_at': None}
_activities_extract_status = {'running': False, 'processed': 0, 'total': 0, 'started_at': None}


def get_people_extract_status() -> dict:
    return dict(_people_extract_status)


def get_activities_extract_status() -> dict:
    return dict(_activities_extract_status)


def _run_extraction(app, entry_ids: list, extract_fn, label: str, status: dict | None = None):
    """Iterate entry_ids on the shared LLM lock, with cooperative yield.

    Each entry runs in its own app_context so the DB connection is fully
    released between entries. Without this, a single long-lived context
    keeps the SQLAlchemy session (and underlying SQLite connection) open
    across multi-second LLM calls, causing "database is locked" for every
    other writer (Flask requests, other background threads).
    """
    if not entry_ids:
        return

    if not _lock.acquire(timeout=300):
        log.warning(f'{label}: lock busy, giving up')
        return

    lock_held = True
    try:
        # Load (or reuse cached) LLM once before the loop.
        with app.app_context():
            from .routes import _get_llm
            try:
                llm = _get_llm()
            except Exception as e:
                log.error(f'{label}: cannot load LLM: {e}')
                return

        total = len(entry_ids)
        processed = 0
        for entry_id in entry_ids:
            # Fresh context per entry: DB connection released after each
            # commit, no stale transaction held during LLM inference.
            with app.app_context():
                entry = db.session.get(MoodEntry, entry_id)
                if entry is None:
                    processed += 1
                    continue
                try:
                    extract_fn(entry, llm)
                except Exception as e:
                    # Roll back any pending state from a failed commit so the
                    # session is clean before teardown closes it.
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    log.warning(f'{label}: failed for entry {entry_id}: {e}')
            processed += 1
            if status is not None:
                status['processed'] = processed
            if processed % 10 == 0:
                log.info(f'{label}: {processed}/{total}')

            # Cooperative yield — let process_entry_async cut in, and give the
            # OS/UI headroom between heavy LLM calls so the machine stays
            # responsive during a large startup backfill (ASSISTANT_EXTRACT_YIELD).
            _lock.release()
            lock_held = False
            time.sleep(_extract_yield())
            if not _lock.acquire(timeout=300):
                log.warning(f'{label}: could not reacquire lock, pausing')
                return
            lock_held = True

        log.info(f'{label} complete: {total} entries')
    finally:
        if lock_held:
            _lock.release()


def reextract_people_async(app) -> bool:
    """Wipe EntryPerson rows and re-run people extraction on all entries.

    Triggered from the /insights/people page when the user wants to
    rebuild this specific chart's data without running the full assistant
    reindex (which also redoes embeddings/summaries/profile). Returns
    False if a re-extract is already in progress.
    """
    if _people_extract_status['running']:
        return False
    thread = threading.Thread(target=_reextract_people, args=(app,), daemon=True)
    thread.start()
    return True


def _reextract_people(app):
    _people_extract_status.update({
        'running': True, 'processed': 0, 'total': 0, 'started_at': time.time(),
    })
    try:
        with app.app_context():
            EntryPerson.query.delete()
            db.session.commit()
            log.info('Cleared EntryPerson for re-extraction')
            entries = MoodEntry.query.filter(
                MoodEntry.note.isnot(None), MoodEntry.note != ''
            ).order_by(MoodEntry.date).all()
            entry_ids = [e.id for e in entries]
        _people_extract_status['total'] = len(entry_ids)
        from .memory import extract_people_mentions
        _run_extraction(
            app, entry_ids, extract_people_mentions,
            'People re-extract', status=_people_extract_status,
        )
    finally:
        _people_extract_status['running'] = False


def reextract_activities_async(app) -> bool:
    """Wipe EntryActivity rows and re-run activity extraction on all entries."""
    if _activities_extract_status['running']:
        return False
    thread = threading.Thread(target=_reextract_activities, args=(app,), daemon=True)
    thread.start()
    return True


def _reextract_activities(app):
    _activities_extract_status.update({
        'running': True, 'processed': 0, 'total': 0, 'started_at': time.time(),
    })
    try:
        with app.app_context():
            EntryActivity.query.delete()
            db.session.commit()
            log.info('Cleared EntryActivity for re-extraction')
            entries = MoodEntry.query.filter(
                MoodEntry.note.isnot(None), MoodEntry.note != ''
            ).order_by(MoodEntry.date).all()
            entry_ids = [e.id for e in entries]
        _activities_extract_status['total'] = len(entry_ids)
        from .memory import extract_activities
        _run_extraction(
            app, entry_ids, extract_activities,
            'Activities re-extract', status=_activities_extract_status,
        )
    finally:
        _activities_extract_status['running'] = False


def backfill_activities_async(app) -> bool:
    """One-time backfill of EntryActivity rows for entries missing them.

    Mirrors backfill_people_async — triggered at startup when assistant
    is active, gated by sync_meta flag so it only runs once per install.
    """
    thread = threading.Thread(target=_backfill_activities, args=(app,), daemon=True)
    thread.start()
    return True


def backfill_assistant_data_async(app) -> bool:
    """Run people + activities backfills sequentially in a SINGLE thread.

    Running them in parallel doubles startup contention on `_lock` and the
    LLM inference lock — every cooperative yield in `_run_extraction`
    bounces the lock between two backfills and any new-entry processing.
    Sequencing them serialises the work and lets new-entry processing
    cut in cleanly between cycles.
    """
    thread = threading.Thread(target=_backfill_sequential, args=(app,), daemon=True)
    thread.start()
    return True


def _backfill_sequential(app):
    # Hold off until the window/UI are up, so launch never feels like a freeze
    # even when this has lots of entries to process (ASSISTANT_BACKFILL_DELAY).
    delay = _backfill_start_delay()
    if delay > 0:
        time.sleep(delay)
    # Never let an automatic backfill be what loads the multi-GB LLM — loading
    # it onto the Metal GPU stalls the whole machine for a few seconds. If the
    # model isn't resident yet, defer: opening the assistant loads it and the
    # post-warmup catch-up re-triggers this once it's hot.
    from .routes import llm_is_loaded
    if not llm_is_loaded():
        log.info('backfill: LLM not loaded — deferring until the assistant is opened')
        return
    try:
        _backfill_people(app)
    except Exception as e:
        log.warning(f'People backfill crashed: {e}')
    try:
        _backfill_activities(app)
    except Exception as e:
        log.warning(f'Activities backfill crashed: {e}')


def _backfill_activities(app):
    """Run activity extraction on entries that have no EntryActivity rows yet.

    Checks pending entries on every startup — no persistent "done" flag. This
    keeps the backfill correct under DB swaps (importing an older DB with more
    entries reprocesses anything that's missing rows). The scan is a cheap
    set-difference on ids.
    """
    with app.app_context():
        entries = MoodEntry.query.order_by(MoodEntry.date).all()
        if not entries:
            return
        existing_ids = {r.entry_id for r in EntryActivity.query.with_entities(EntryActivity.entry_id).all()}
        pending_ids = [e.id for e in entries if e.id not in existing_ids and (e.note or '').strip()]

    if not pending_ids:
        return

    log.info(f'Activities backfill: {len(pending_ids)} entries pending')
    from .memory import extract_activities
    _run_extraction(app, pending_ids, extract_activities, 'Activities backfill')


def backfill_people_async(app) -> bool:
    """One-time backfill of EntryPerson rows for entries missing them.

    Triggered at startup when assistant is active. Skips silently if the
    backfill-complete flag is set in sync_meta. Processing happens in a
    thread so app startup isn't blocked.
    """
    thread = threading.Thread(target=_backfill_people, args=(app,), daemon=True)
    thread.start()
    return True


def _backfill_people(app):
    """Run people extraction on entries that have no EntryPerson rows yet.

    Checks pending entries on every startup — no persistent "done" flag. This
    keeps the backfill correct under DB swaps (importing an older DB with more
    entries reprocesses anything that's missing rows). The scan is a cheap
    set-difference on ids.
    """
    with app.app_context():
        entries = MoodEntry.query.order_by(MoodEntry.date).all()
        if not entries:
            return
        existing_ids = {r.entry_id for r in EntryPerson.query.with_entities(EntryPerson.entry_id).all()}
        pending_ids = [e.id for e in entries if e.id not in existing_ids and (e.note or '').strip()]

    if not pending_ids:
        return

    log.info(f'People backfill: {len(pending_ids)} entries pending')
    from .memory import extract_people_mentions
    _run_extraction(app, pending_ids, extract_people_mentions, 'People backfill')


def _process_entry(app, entry_id: int):
    """Process a single entry: embedding + summary + maybe profile update.

    Each step runs in its own app_context so the DB connection is released
    before the LLM call begins. This prevents "database is locked" errors
    when the user edits an entry while background processing is running —
    a single long app_context would hold the SQLAlchemy session (and its
    underlying SQLite connection) open across multi-second LLM inference.
    """
    if not _lock.acquire(timeout=120):
        log.warning('Background lock held for >120s, skipping entry %d', entry_id)
        return

    try:
        # 1. Embedding — fast, no LLM; own context so connection is freed immediately.
        with app.app_context():
            entry = db.session.get(MoodEntry, entry_id)
            if entry is None:
                return
            try:
                from .memory import update_embedding
                update_embedding(entry)
                log.info('Embedding updated for entry %d', entry_id)
            except Exception as e:
                # Roll back any pending state from the failed commit so the
                # session is clean before teardown closes it. Without this,
                # the next step's first SQL can hit a half-aborted session.
                try:
                    db.session.rollback()
                except Exception:
                    pass
                log.warning('Embedding failed for entry %d: %s', entry_id, e)

        # 2–6: Each step re-fetches the entry in a fresh context so no DB
        # connection is held while the LLM generates completions.

        # These steps need the LLM. Don't load it from here — saving an entry
        # must not stall the whole machine. Run them only if the model is
        # already resident; otherwise they're picked up by the post-warmup
        # catch-up (sync + backfill) once the user opens the assistant.
        from .routes import llm_is_loaded
        if not llm_is_loaded():
            log.info('entry %d: embedding done, LLM steps deferred (model not loaded)', entry_id)
            return

        # 2. Summary
        with app.app_context():
            entry = db.session.get(MoodEntry, entry_id)
            if entry is None:
                return
            try:
                from .memory import generate_entry_summary
                from .routes import _get_llm
                generate_entry_summary(entry, _get_llm())
                log.info('Summary generated for entry %d', entry_id)
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                log.warning('Summary failed for entry %d: %s', entry_id, e)

        # 3. People mentions (idempotent — replaces prior rows on re-run)
        with app.app_context():
            entry = db.session.get(MoodEntry, entry_id)
            if entry is None:
                return
            try:
                from .memory import extract_people_mentions
                from .routes import _get_llm
                extract_people_mentions(entry, _get_llm())
                log.info('People mentions extracted for entry %d', entry_id)
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                log.warning('People extraction failed for entry %d: %s', entry_id, e)

        # 4. Activities (idempotent like people)
        with app.app_context():
            entry = db.session.get(MoodEntry, entry_id)
            if entry is None:
                return
            try:
                from .memory import extract_activities
                from .routes import _get_llm
                extract_activities(entry, _get_llm())
                log.info('Activities extracted for entry %d', entry_id)
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                log.warning('Activities extraction failed for entry %d: %s', entry_id, e)

        # 5. Monthly summary for this entry's month
        with app.app_context():
            entry = db.session.get(MoodEntry, entry_id)
            if entry is None:
                return
            try:
                from .memory import generate_month_summary
                from .routes import _get_llm
                generate_month_summary(entry.date.year, entry.date.month, _get_llm())
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                log.warning('Month summary failed: %s', e)

        # 6. Profile update (every 5 entries)
        with app.app_context():
            try:
                from .memory import update_profile
                from .routes import _get_llm
                update_profile(_get_llm())
                log.info('Profile check complete')
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                log.warning('Profile update failed: %s', e)

    finally:
        _lock.release()


def _reindex_all(app):
    """Reindex all entries from scratch. Triggered manually."""
    global _reindex_in_progress
    if _lock.locked():
        log.warning('Background processing already running, waiting to start reindex.')
        _set_reindex_status(phase='waiting', message='Waiting for background processing to finish')
    _lock.acquire()

    try:
        with app.app_context():
            from .memory import (
                update_embedding, generate_entry_summary,
                generate_month_summary, update_profile,
            )
            from .routes import _get_llm
            from app.models import EntryEmbedding, EntrySummary, PeriodSummary, UserPsychProfile

            total = MoodEntry.query.count()
            log.info(f'Reindex started: {total} entries')
            _set_reindex_status(phase='starting', current=0, total=total, message='Reindex started')

            # Full rebuild: clear assistant memory layers first
            try:
                EntryEmbedding.query.delete()
                EntrySummary.query.delete()
                EntryPerson.query.delete()
                EntryActivity.query.delete()
                PeriodSummary.query.delete()
                UserPsychProfile.query.delete()
                db.session.commit()
                log.info('Cleared embeddings, summaries, people, activities, period summaries, profile')
            except Exception as e:
                db.session.rollback()
                log.warning(f'Failed to clear assistant memory layers: {e}')

            # Work from IDs and re-fetch each entry fresh inside the loops.
            # The processors (update_embedding, generate_entry_summary, …) call
            # db.session.remove() internally, which detaches every other ORM
            # object; the clear-commit above also expires them. Iterating over
            # pre-loaded ORM objects would therefore raise DetachedInstanceError
            # on the 2nd entry. Plain int IDs are immune to that.
            entry_ids = [
                row[0] for row in
                MoodEntry.query.with_entities(MoodEntry.id)
                .order_by(MoodEntry.date).all()
            ]

            # Phase 1: Embeddings (fast, no LLM)
            _set_reindex_status(phase='embeddings', current=0, total=total, message='Embeddings')
            for i, eid in enumerate(entry_ids):
                try:
                    entry = db.session.get(MoodEntry, eid)
                    if entry is not None:
                        update_embedding(entry)
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    log.warning(f'Embedding failed for entry {eid}: {e}')
                if (i + 1) % 5 == 0 or (i + 1) == total:
                    _set_reindex_status(current=i + 1)
                if (i + 1) % 50 == 0:
                    log.info(f'Embeddings: {i + 1}/{total}')
            log.info(f'Embeddings done: {total}')

            # Phase 2: Summaries (needs LLM, slower)
            try:
                llm = _get_llm()
            except Exception as e:
                log.error(f'Cannot load LLM for summaries: {e}')
                return

            _set_reindex_status(phase='summaries', current=0, total=total, message='Summaries')
            for i, eid in enumerate(entry_ids):
                try:
                    entry = db.session.get(MoodEntry, eid)
                    if entry is not None:
                        generate_entry_summary(entry, llm)
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    log.warning(f'Summary failed for entry {eid}: {e}')
                if (i + 1) % 3 == 0 or (i + 1) == total:
                    _set_reindex_status(current=i + 1)
                if (i + 1) % 20 == 0:
                    log.info(f'Summaries: {i + 1}/{total}')
            log.info('Summaries done')

            # Phase 3: People extraction (needs LLM)
            from .memory import extract_people_mentions
            _set_reindex_status(phase='people', current=0, total=total, message='People mentions')
            for i, eid in enumerate(entry_ids):
                try:
                    entry = db.session.get(MoodEntry, eid)
                    if entry is not None:
                        extract_people_mentions(entry, llm)
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    log.warning(f'People extraction failed for entry {eid}: {e}')
                if (i + 1) % 3 == 0 or (i + 1) == total:
                    _set_reindex_status(current=i + 1)
                if (i + 1) % 20 == 0:
                    log.info(f'People: {i + 1}/{total}')
            log.info('People mentions done')

            # Phase 4: Activities extraction (needs LLM)
            from .memory import extract_activities
            _set_reindex_status(phase='activities', current=0, total=total, message='Activities')
            for i, eid in enumerate(entry_ids):
                try:
                    entry = db.session.get(MoodEntry, eid)
                    if entry is not None:
                        extract_activities(entry, llm)
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    log.warning(f'Activities extraction failed for entry {eid}: {e}')
                if (i + 1) % 3 == 0 or (i + 1) == total:
                    _set_reindex_status(current=i + 1)
                if (i + 1) % 20 == 0:
                    log.info(f'Activities: {i + 1}/{total}')
            log.info('Activities done')

            # Phase 5: Monthly summaries
            months = sorted({
                (d.year, d.month) for (d,) in
                MoodEntry.query.with_entities(MoodEntry.date).all()
            })
            _set_reindex_status(phase='monthly_summaries', current=0, total=len(months), message='Monthly summaries')
            for i, (year, month) in enumerate(months):
                try:
                    generate_month_summary(year, month, llm)
                except Exception as e:
                    log.warning(f'Month summary failed for {year}-{month}: {e}')
                _set_reindex_status(current=i + 1)
            log.info('Monthly summaries done')

            # Phase 6: Full profile rebuild
            try:
                _set_reindex_status(phase='profile', current=0, total=1, message='Profile rebuild')
                update_profile(llm, force_rebuild=True)
                _set_reindex_status(current=1)
                log.info('Profile rebuilt')
            except Exception as e:
                log.warning(f'Profile rebuild failed: {e}')
                _set_reindex_status(error=str(e))

            log.info('Reindex complete')
            _set_reindex_status(phase='done', message='Reindex complete')
    except Exception as e:
        # Surface the failure: a daemon-thread exception otherwise goes to
        # sys.stderr, which is invisible in a windowed (frozen) app — so the
        # reindex would just silently stop with no clue in the log file.
        log.error('Reindex crashed: %s', e, exc_info=True)
        _set_reindex_status(phase='error', error=str(e), message=f'Reindex failed: {e}')
    finally:
        _lock.release()
        with _reindex_state_lock:
            _reindex_in_progress = False
            _reindex_status['running'] = False
            _reindex_status['updated_at'] = time.time()


def sync_missing_async(app) -> bool:
    """Spawn a background thread to process only entries missing embeddings/summaries."""
    if _lock.locked():
        return False
    thread = threading.Thread(target=_sync_missing, args=(app,), daemon=True)
    thread.start()
    return True


def rebuild_profile_async(app):
    """Spawn a background thread to rebuild the psychological profile."""
    thread = threading.Thread(target=_rebuild_profile, args=(app,), daemon=True)
    thread.start()


def _sync_missing(app):
    """Process only entries missing embeddings or summaries.

    Each entry runs in its own app_context so the DB connection is fully
    released between entries — same pattern as `_run_extraction`. Between
    entries the function does a cooperative yield of `_lock`, letting
    new-entry processing cut in cleanly so the user doesn't wait for a
    long sync to finish before their fresh save gets indexed.

    Progress is tracked in `_sync_status` (poll via `get_sync_status()`).
    Per-entry failures don't abort the run — they're counted in `failed`
    and the last few messages stored in `errors` so the UI can show them.
    """
    if not _lock.acquire(timeout=5):
        log.info('Lock busy, skipping sync')
        _set_sync_status(running=False, phase='', message='Background busy, try again later')
        return

    lock_held = True
    _set_sync_status(
        running=True, phase='scanning', current=0, total=0,
        embedded=0, summarized=0, failed=0, errors=[],
        message='Scanning entries…', started_at=time.time(),
    )

    embedded_count = 0
    summarized_count = 0
    failed_count = 0
    errors: list = []

    try:
        # Phase 1: scan for missing data — short read in its own context.
        # Capture only IDs (not ORM objects) so the loop below can re-fetch
        # each entry in a fresh session without DetachedInstanceError.
        with app.app_context():
            from app.models import EntryEmbedding, EntrySummary
            embedded_ids = {
                row[0] for row in
                EntryEmbedding.query.with_entities(EntryEmbedding.entry_id).all()
            }
            summarized_ids = {
                row[0] for row in
                EntrySummary.query.with_entities(EntrySummary.entry_id).all()
            }
            entry_rows = (MoodEntry.query
                          .with_entities(MoodEntry.id)
                          .order_by(MoodEntry.date)
                          .all())
            missing = []
            for (entry_id,) in entry_rows:
                needs_embed = entry_id not in embedded_ids
                needs_summary = entry_id not in summarized_ids
                if needs_embed or needs_summary:
                    missing.append((entry_id, needs_embed, needs_summary))

        if not missing:
            log.info('sync: all entries up to date')
            _set_sync_status(running=False, phase='done',
                             message='Все записи уже обработаны')
            return

        total = len(missing)
        log.info('sync: %d entries need processing', total)
        _set_sync_status(phase='processing', total=total,
                         message=f'Обработка {total} записей')

        # Don't let a background sync be what loads the multi-GB LLM — that
        # stalls the whole machine for a few seconds. Use it only if it's
        # already resident (the user opened the assistant). Embeddings are cheap
        # and always run; summaries wait for a hot model and get picked up by
        # the post-warmup catch-up.
        llm = None
        with app.app_context():
            from .routes import llm_is_loaded, _get_llm
            if llm_is_loaded():
                try:
                    llm = _get_llm()
                except Exception as e:
                    log.warning(f'sync: LLM present but failed to fetch: {e}')
                    llm = None
        if llm is None:
            log.info('sync: LLM not loaded — embeddings only, summaries deferred')

        # Phase 2: process each entry in its own context so the DB
        # connection is freed between entries. Cooperative yield between
        # entries lets new-entry processing cut in.
        for i, (entry_id, needs_embed, needs_summary) in enumerate(missing):
            with app.app_context():
                entry = db.session.get(MoodEntry, entry_id)
                if entry is None:
                    continue

                if needs_embed:
                    try:
                        from .memory import update_embedding
                        update_embedding(entry)
                        embedded_count += 1
                    except Exception as e:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        failed_count += 1
                        errors.append(f'embed #{entry_id}: {str(e)[:140]}')
                        log.warning(f'sync: embedding failed for {entry_id}: {e}')

                if needs_summary and llm is not None:
                    # Re-fetch in case update_embedding removed the session.
                    if entry not in db.session:
                        entry = db.session.get(MoodEntry, entry_id)
                        if entry is None:
                            continue
                    try:
                        from .memory import generate_entry_summary
                        generate_entry_summary(entry, llm)
                        summarized_count += 1
                    except Exception as e:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        failed_count += 1
                        errors.append(f'summary #{entry_id}: {str(e)[:140]}')
                        log.warning(f'sync: summary failed for {entry_id}: {e}')

            # Update progress (keep only last 5 errors for the UI)
            _set_sync_status(
                current=i + 1,
                embedded=embedded_count,
                summarized=summarized_count,
                failed=failed_count,
                errors=errors[-5:],
            )

            # Cooperative yield — let new-entry processing cut in.
            _lock.release()
            lock_held = False
            time.sleep(0.05)
            if not _lock.acquire(timeout=300):
                log.warning('sync: could not reacquire lock, pausing')
                _set_sync_status(running=False, phase='error',
                                 message='Прервано: лок занят слишком долго')
                return
            lock_held = True

        # Done — surface final counts to the UI.
        if failed_count > 0:
            msg = (f'Готово с ошибками: {embedded_count} embeddings, '
                   f'{summarized_count} summaries, {failed_count} ошибок')
            _set_sync_status(running=False, phase='done_with_errors',
                             message=msg, errors=errors[-5:])
        else:
            msg = f'Готово: {embedded_count} embeddings, {summarized_count} summaries'
            _set_sync_status(running=False, phase='done', message=msg)
        log.info(f'sync: {msg}')
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        log.error('sync crashed: %s', e, exc_info=True)
        _set_sync_status(running=False, phase='error',
                         message=f'Сбой синхронизации: {e}')
    finally:
        if lock_held:
            _lock.release()


def _rebuild_profile(app):
    """Delete and rebuild the psychological profile."""
    if not _lock.acquire(timeout=30):
        log.warning('Lock busy, cannot rebuild profile')
        return

    try:
        with app.app_context():
            from .memory import update_profile
            from .routes import _get_llm
            from app.models import UserPsychProfile

            UserPsychProfile.query.delete()
            db.session.commit()

            llm = _get_llm()
            update_profile(llm, force_rebuild=True)
            log.info('Profile rebuilt successfully')
    except Exception as e:
        log.warning(f'Profile rebuild failed: {e}')
    finally:
        _lock.release()


def _warmup(app):
    try:
        with app.app_context():
            from .routes import _get_llm, _env_bool
            # The LLM is a multi-GB GGUF loaded fully onto the Metal GPU. Eagerly
            # warming it on every launch spikes unified memory and briefly freezes
            # the whole machine on 16 GB Macs. Default OFF: it now loads lazily when
            # the user opens the assistant chat (chat.js pings /assistant/warmup
            # then, with a progress bar). Opt back in with LLM_WARMUP_ON_LOAD=1.
            if _env_bool('LLM_WARMUP_ON_LOAD', False):
                try:
                    _get_llm()
                except Exception as e:
                    log.warning(f'LLM warmup failed: {e}', exc_info=True)
            # The embedding model is small and CPU-only (used by background entry
            # processing), so warming it on load is cheap and won't stall the system.
            try:
                from .memory import _get_embed_model
                _get_embed_model()
            except Exception as e:
                log.warning(f'Embedding warmup failed: {e}')
    except Exception as e:
        log.warning(f'Warmup failed: {e}')
