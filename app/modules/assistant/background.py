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


def _combined_extract_enabled() -> bool:
    """Whether new/edited entries use the single combined LLM call
    (summary + people + activities) instead of three separate ones.

    OFF by default. The A/B run (tools/ab_extract.py, Qwen3.5-9B on Metal)
    showed quality parity but NO wall-clock win (×1.00): generation
    dominates and the combined answer carries the same total tokens, so
    collapsing the calls only saves re-processing the short prompts. With
    no measured benefit, the battle-tested individual extractors stay the
    default. Set ASSISTANT_COMBINED_EXTRACT=1 to opt in — worth
    re-measuring on a future faster model, where prompt processing may
    dominate and the ~3x hypothesis could hold."""
    raw = (os.environ.get('ASSISTANT_COMBINED_EXTRACT') or '').strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def _ai_index_mode(app) -> str:
    """'auto' (process LLM data in the background) or 'manual' (only when the
    user presses the "update" button). Reads UserProfile; defaults to 'auto'.
    """
    from flask import has_app_context

    def _read():
        from app.models import UserProfile
        p = UserProfile.query.first()
        return (getattr(p, 'ai_index_mode', None) or 'auto') if p else 'auto'

    try:
        if has_app_context():
            return _read()
        with app.app_context():
            return _read()
    except Exception:
        return 'auto'


def _acquire_llm_for_bg(app, force: bool = False):
    """LLM for a background task, honoring the AI-index mode.

    force (user pressed "update") or 'auto' mode → load it (pre-warmed, so no
    system freeze). 'manual' mode → return None so the caller skips LLM work;
    the update button (force=True) is then the only way it runs.
    """
    if not force and _ai_index_mode(app) != 'auto':
        return None
    from .routes import _get_llm
    return _get_llm()


def _wait_if_chat_active(max_wait: float = 120.0) -> None:
    """Pause background LLM work while the user is actively chatting, so a live
    conversation never has to wait on background summarization. Caps the wait so
    a stuck flag can't starve background work forever.
    """
    try:
        from .routes import is_chat_active
    except Exception:
        return
    waited = 0.0
    while is_chat_active() and waited < max_wait:
        time.sleep(0.5)
        waited += 0.5


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


def _marked_ids(kind: str) -> set:
    """Entries extraction has already been run over, for this kind."""
    from app.models import EntryIndexMark
    return {r.entry_id for r in EntryIndexMark.query
            .with_entities(EntryIndexMark.entry_id)
            .filter(EntryIndexMark.kind == kind).all()}


def _mark_indexed(entry_ids, kind: str) -> None:
    """Record that extraction ran over these entries, whatever it found.

    Marking is what stops an entry that mentions nobody from being asked
    about again on every launch. Only entries that were actually processed
    without error get here — a crashed extraction stays pending, exactly as
    it did before.
    """
    if not entry_ids:
        return
    from app.models import EntryIndexMark
    try:
        already = _marked_ids(kind)
        for entry_id in entry_ids:
            if entry_id not in already:
                db.session.add(EntryIndexMark(entry_id=entry_id, kind=kind))
        db.session.commit()
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        log.warning('Could not mark %s as indexed (%s): %s', kind, len(entry_ids), exc)


def _run_extraction(app, entry_ids: list, extract_fn, label: str,
                    status: dict | None = None, mark_kind: str | None = None):
    """Iterate entry_ids on the shared LLM lock, with cooperative yield.

    Each entry runs in its own app_context so the DB connection is fully
    released between entries. Without this, a single long-lived context
    keeps the SQLAlchemy session (and underlying SQLite connection) open
    across multi-second LLM calls, causing "database is locked" for every
    other writer (Flask requests, other background threads).
    `mark_kind` marks each entry as indexed the moment it is done, not at the
    end of the batch. That distinction is the whole point on a long run: the
    app is typically open for a couple of minutes while a backfill of a few
    dozen entries takes far longer, so marking only at the end would mean the
    marks were never written at all and the work repeated at every launch —
    exactly the loop this was meant to break. Entries that raised stay
    unmarked and pending.

    Also returns the ids it got through without an error.
    """
    done: list = []
    if not entry_ids:
        return done

    if not _lock.acquire(timeout=300):
        log.warning(f'{label}: lock busy, giving up')
        return done

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
            _wait_if_chat_active()  # yield to a live conversation
            # Fresh context per entry: DB connection released after each
            # commit, no stale transaction held during LLM inference.
            with app.app_context():
                entry = db.session.get(MoodEntry, entry_id)
                if entry is None:
                    processed += 1
                    continue
                try:
                    extract_fn(entry, llm)
                    done.append(entry_id)
                    if mark_kind:
                        _mark_indexed([entry_id], mark_kind)
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
                return done
            lock_held = True

        log.info(f'{label} complete: {total} entries')
        return done
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
            # A rebuild forgets that we ever looked, too — the run
            # below marks each entry again as it reaches it.
            from app.models import EntryIndexMark
            EntryIndexMark.query.filter_by(kind='people').delete()
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
            'People re-extract', status=_people_extract_status, mark_kind='people',
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
            # A rebuild forgets that we ever looked, too — the run
            # below marks each entry again as it reaches it.
            from app.models import EntryIndexMark
            EntryIndexMark.query.filter_by(kind='activities').delete()
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
            'Activities re-extract', status=_activities_extract_status, mark_kind='activities',
        )
    finally:
        _activities_extract_status['running'] = False


def backfill_activities_async(app) -> bool:
    """User-triggered incremental update of EntryActivity rows (the Activities
    chart's "update AI data" button). Only processes entries missing rows, so it
    preserves existing data. Tracks progress in _activities_extract_status so the
    page can poll and reload when done. Returns False if already running.
    """
    if _activities_extract_status['running']:
        return False

    def _run():
        _activities_extract_status.update({
            'running': True, 'processed': 0, 'total': 0, 'started_at': time.time(),
        })
        try:
            _backfill_activities(app, status=_activities_extract_status)
        finally:
            _activities_extract_status['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def backfill_assistant_data_async(app, force: bool = False) -> bool:
    """Run people + activities backfills sequentially in a SINGLE thread.

    Running them in parallel doubles startup contention on `_lock` and the
    LLM inference lock — every cooperative yield in `_run_extraction`
    bounces the lock between two backfills and any new-entry processing.
    Sequencing them serialises the work and lets new-entry processing
    cut in cleanly between cycles. `force=True` (user's update button) runs
    regardless of the auto/manual mode.
    """
    thread = threading.Thread(target=_backfill_sequential, args=(app, force), daemon=True)
    thread.start()
    return True


def _backfill_sequential(app, force=False):
    # Hold off until the window/UI are up, so launch never feels like a freeze
    # even when this has lots of entries to process (ASSISTANT_BACKFILL_DELAY).
    delay = _backfill_start_delay()
    if delay > 0:
        time.sleep(delay)
    # 'manual' mode: don't process in the background — wait for the user's
    # "update AI data" button (force=True). 'auto' mode: proceed; the LLM here
    # loads pre-warmed (gradual cache warm inside _get_llm), so no system freeze.
    if not force and _ai_index_mode(app) != 'auto':
        log.info('backfill: manual mode — deferring to the "update AI data" button')
        return
    try:
        _backfill_people(app)
    except Exception as e:
        log.warning(f'People backfill crashed: {e}')
    try:
        _backfill_activities(app)
    except Exception as e:
        log.warning(f'Activities backfill crashed: {e}')


def _backfill_activities(app, status=None):
    """Run activity extraction on entries that have no EntryActivity rows yet.

    Incremental (only entries missing rows), so it preserves existing data —
    unlike re-extract, which wipes and rebuilds. Checks pending entries on every
    startup. An entry counts as pending only while it has neither rows nor
    an index mark: without the mark, a note that genuinely mentions nothing
    was indistinguishable from one never looked at, and got re-extracted at
    every launch for the rest of its life.
    Pass `status` (the extract-status dict) to surface progress to the UI.
    """
    with app.app_context():
        entries = MoodEntry.query.order_by(MoodEntry.date).all()
        if not entries:
            return
        existing_ids = {r.entry_id for r in EntryActivity.query.with_entities(EntryActivity.entry_id).all()}
        seen_ids = existing_ids | _marked_ids('activities')
        pending_ids = [e.id for e in entries if e.id not in seen_ids and (e.note or '').strip()]

    if not pending_ids:
        return

    if status is not None:
        status['total'] = len(pending_ids)
    log.info(f'Activities backfill: {len(pending_ids)} entries pending')
    from .memory import extract_activities
    _run_extraction(app, pending_ids, extract_activities, 'Activities backfill', status=status,
                    mark_kind='activities')


def backfill_people_async(app) -> bool:
    """User-triggered incremental update of EntryPerson rows (the People chart's
    "update AI data" button). Only processes entries missing rows, so it
    preserves existing data (and any manual edits) — unlike re-extract, which
    wipes and rebuilds. Tracks progress in _people_extract_status so the page
    can poll and reload when done. Returns False if already running.
    """
    if _people_extract_status['running']:
        return False

    def _run():
        _people_extract_status.update({
            'running': True, 'processed': 0, 'total': 0, 'started_at': time.time(),
        })
        try:
            _backfill_people(app, status=_people_extract_status)
        finally:
            _people_extract_status['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def _backfill_people(app, status=None):
    """Run people extraction on entries that have no EntryPerson rows yet.

    Incremental (only entries missing rows), so it preserves existing data —
    unlike re-extract, which wipes and rebuilds. Checks pending entries on every
    startup. An entry counts as pending only while it has neither rows nor
    an index mark: without the mark, a note that genuinely mentions nothing
    was indistinguishable from one never looked at, and got re-extracted at
    every launch for the rest of its life.
    Pass `status` (the extract-status dict) to surface progress to the UI.
    """
    with app.app_context():
        entries = MoodEntry.query.order_by(MoodEntry.date).all()
        if not entries:
            return
        existing_ids = {r.entry_id for r in EntryPerson.query.with_entities(EntryPerson.entry_id).all()}
        seen_ids = existing_ids | _marked_ids('people')
        pending_ids = [e.id for e in entries if e.id not in seen_ids and (e.note or '').strip()]

    if not pending_ids:
        return

    if status is not None:
        status['total'] = len(pending_ids)
    log.info(f'People backfill: {len(pending_ids)} entries pending')
    from .memory import extract_people_mentions
    _run_extraction(app, pending_ids, extract_people_mentions, 'People backfill', status=status,
                    mark_kind='people')


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

        # These steps need the LLM. In 'auto' mode load it (pre-warmed, so no
        # system freeze) and process now; in 'manual' mode skip — the user's
        # "update AI data" button (force) is the only trigger there. Embeddings
        # above already ran regardless.
        if _acquire_llm_for_bg(app) is None:
            log.info('entry %d: embedding done, LLM steps deferred (manual mode)', entry_id)
            return
        _wait_if_chat_active()  # don't compete with a live conversation

        # 2. Summary + people + activities — ONE combined LLM call (the fast
        # path: three passes over the same note collapse into one). Any
        # failure or unusable JSON falls back to the three individual steps
        # below, so a degraded model answer never loses a section.
        combined_done = False
        if _combined_extract_enabled():
            with app.app_context():
                entry = db.session.get(MoodEntry, entry_id)
                if entry is None:
                    return
                try:
                    from .memory import extract_entry_combined
                    from .routes import _get_llm
                    combined_done = extract_entry_combined(entry, _get_llm())
                    if combined_done:
                        # One call answered for both, so both are indexed —
                        # including when the answer was "nobody, nothing".
                        _mark_indexed([entry_id], 'people')
                        _mark_indexed([entry_id], 'activities')
                        log.info('Combined extract done for entry %d', entry_id)
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    log.warning('Combined extract failed for entry %d: %s',
                                entry_id, e)

        # 2b. Summary (fallback path)
        if not combined_done:
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
        if not combined_done:
            with app.app_context():
                entry = db.session.get(MoodEntry, entry_id)
                if entry is None:
                    return
                try:
                    from .memory import extract_people_mentions
                    from .routes import _get_llm
                    extract_people_mentions(entry, _get_llm())
                    _mark_indexed([entry_id], 'people')
                    log.info('People mentions extracted for entry %d', entry_id)
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    log.warning('People extraction failed for entry %d: %s', entry_id, e)

        # 4. Activities (idempotent like people)
        if not combined_done:
            with app.app_context():
                entry = db.session.get(MoodEntry, entry_id)
                if entry is None:
                    return
                try:
                    from .memory import extract_activities
                    from .routes import _get_llm
                    extract_activities(entry, _get_llm())
                    _mark_indexed([entry_id], 'activities')
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


def sync_missing_async(app, force: bool = False) -> bool:
    """Spawn a background thread to process entries missing embeddings/summaries.

    `force=True` (user's update button) processes summaries regardless of the
    auto/manual mode; otherwise summaries only run in 'auto' mode.
    """
    if _lock.locked():
        return False
    thread = threading.Thread(target=_sync_missing, args=(app, force), daemon=True)
    thread.start()
    return True


def rebuild_profile_async(app):
    """Spawn a background thread to rebuild the psychological profile."""
    thread = threading.Thread(target=_rebuild_profile, args=(app,), daemon=True)
    thread.start()


def _sync_missing(app, force=False):
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

        # Load the LLM only if allowed: 'auto' mode or the user's update button
        # (force). It loads pre-warmed (gradual cache warm), so no system freeze.
        # In 'manual' mode we do embeddings only and defer summaries to the
        # update button. Embeddings are cheap and always run.
        try:
            llm = _acquire_llm_for_bg(app, force)
        except Exception as e:
            log.warning(f'sync: LLM fetch failed: {e}')
            llm = None
        if llm is None:
            log.info('sync: skipping summaries (manual mode) — embeddings only')

        # Phase 2: process each entry in its own context so the DB
        # connection is freed between entries. Cooperative yield between
        # entries lets new-entry processing cut in.
        for i, (entry_id, needs_embed, needs_summary) in enumerate(missing):
            if needs_summary and llm is not None:
                _wait_if_chat_active()  # yield to a live conversation
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
