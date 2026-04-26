"""
Background processing for new diary entries.
Runs embedding, summarization, and profile updates in a separate thread.
"""
import logging
import threading
import time

from app import db
from app.models import MoodEntry, EntrySummary, EntryPerson, EntryActivity

log = logging.getLogger(__name__)

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

    Used by both startup backfill (status=None) and the chart-triggered
    re-extract (status=dict) — avoids duplicating the lock/yield/error
    plumbing in two places. Each iteration releases the lock briefly so
    that user-triggered process_entry_async can cut in line on new
    entries instead of waiting for the full extraction to finish.
    """
    if not entry_ids:
        return

    if not _lock.acquire(timeout=300):
        log.warning(f'{label}: lock busy, giving up')
        return

    lock_held = True
    try:
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
                entry = db.session.get(MoodEntry, entry_id)
                if entry is None:
                    continue
                try:
                    extract_fn(entry, llm)
                except Exception as e:
                    log.warning(f'{label}: failed for entry {entry_id}: {e}')
                processed += 1
                if status is not None:
                    status['processed'] = processed
                if processed % 10 == 0:
                    log.info(f'{label}: {processed}/{total}')

                # Cooperative yield — let process_entry_async cut in.
                _lock.release()
                lock_held = False
                time.sleep(0.05)
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

    Waits up to 120s for the lock (previous entry processing or reindex)
    so that entries are never silently skipped.
    """
    if not _lock.acquire(timeout=120):
        log.warning('Background lock held for >120s, skipping entry %d', entry_id)
        return

    try:
        with app.app_context():
            entry = db.session.get(MoodEntry, entry_id)
            if entry is None:
                return

            from .memory import update_embedding, generate_entry_summary, update_profile
            from .routes import _get_llm

            # 1. Embedding (no LLM needed)
            try:
                update_embedding(entry)
                log.info(f'Embedding updated for entry {entry_id}')
            except Exception as e:
                log.warning(f'Embedding failed for entry {entry_id}: {e}')

            # 2. Summary (needs LLM)
            try:
                llm = _get_llm()
                generate_entry_summary(entry, llm)
                log.info(f'Summary generated for entry {entry_id}')
            except Exception as e:
                log.warning(f'Summary failed for entry {entry_id}: {e}')

            # 3. People mentions (needs LLM; extraction is idempotent so
            # re-running on edited entries cleanly replaces prior rows)
            try:
                from .memory import extract_people_mentions
                extract_people_mentions(entry, llm)
                log.info(f'People mentions extracted for entry {entry_id}')
            except Exception as e:
                log.warning(f'People extraction failed for entry {entry_id}: {e}')

            # 4. Activities (needs LLM; idempotent like people)
            try:
                from .memory import extract_activities
                extract_activities(entry, llm)
                log.info(f'Activities extracted for entry {entry_id}')
            except Exception as e:
                log.warning(f'Activities extraction failed for entry {entry_id}: {e}')

            # 5. Monthly summary for this entry's month
            try:
                from .memory import generate_month_summary
                generate_month_summary(entry.date.year, entry.date.month, llm)
            except Exception as e:
                log.warning(f'Month summary failed: {e}')

            # 6. Profile update (every 5 entries)
            try:
                update_profile(llm)
                log.info('Profile check complete')
            except Exception as e:
                log.warning(f'Profile update failed: {e}')
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

            entries = MoodEntry.query.order_by(MoodEntry.date).all()
            total = len(entries)
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

            # Phase 1: Embeddings (fast, no LLM)
            _set_reindex_status(phase='embeddings', current=0, total=total, message='Embeddings')
            for i, entry in enumerate(entries):
                try:
                    update_embedding(entry)
                except Exception as e:
                    log.warning(f'Embedding failed for entry {entry.id}: {e}')
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
            for i, entry in enumerate(entries):
                try:
                    generate_entry_summary(entry, llm)
                except Exception as e:
                    log.warning(f'Summary failed for entry {entry.id}: {e}')
                if (i + 1) % 3 == 0 or (i + 1) == total:
                    _set_reindex_status(current=i + 1)
                if (i + 1) % 20 == 0:
                    log.info(f'Summaries: {i + 1}/{total}')
            log.info('Summaries done')

            # Phase 3: People extraction (needs LLM)
            from .memory import extract_people_mentions
            _set_reindex_status(phase='people', current=0, total=total, message='People mentions')
            for i, entry in enumerate(entries):
                try:
                    extract_people_mentions(entry, llm)
                except Exception as e:
                    log.warning(f'People extraction failed for entry {entry.id}: {e}')
                if (i + 1) % 3 == 0 or (i + 1) == total:
                    _set_reindex_status(current=i + 1)
                if (i + 1) % 20 == 0:
                    log.info(f'People: {i + 1}/{total}')
            log.info('People mentions done')

            # Phase 4: Activities extraction (needs LLM)
            from .memory import extract_activities
            _set_reindex_status(phase='activities', current=0, total=total, message='Activities')
            for i, entry in enumerate(entries):
                try:
                    extract_activities(entry, llm)
                except Exception as e:
                    log.warning(f'Activities extraction failed for entry {entry.id}: {e}')
                if (i + 1) % 3 == 0 or (i + 1) == total:
                    _set_reindex_status(current=i + 1)
                if (i + 1) % 20 == 0:
                    log.info(f'Activities: {i + 1}/{total}')
            log.info('Activities done')

            # Phase 5: Monthly summaries
            months = set()
            for entry in entries:
                months.add((entry.date.year, entry.date.month))
            month_list = sorted(months)
            _set_reindex_status(phase='monthly_summaries', current=0, total=len(month_list), message='Monthly summaries')
            for i, (year, month) in enumerate(month_list):
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
    """Process only entries that are missing embeddings or summaries."""
    if not _lock.acquire(timeout=5):
        log.info('Lock busy, skipping sync')
        return

    try:
        with app.app_context():
            from .memory import update_embedding, generate_entry_summary
            from .routes import _get_llm
            from app.models import EntryEmbedding, EntrySummary

            all_entries = MoodEntry.query.all()
            embedded_ids = {e.entry_id for e in EntryEmbedding.query.all()}
            summarized_ids = {s.entry_id for s in EntrySummary.query.all()}

            missing = [e for e in all_entries
                       if e.id not in embedded_ids or e.id not in summarized_ids]

            if not missing:
                log.info('sync: all entries up to date')
                return

            log.info('sync: %d entries need processing', len(missing))
            llm = None

            for entry in missing:
                if entry.id not in embedded_ids:
                    try:
                        update_embedding(entry)
                        log.info(f'sync: embedded entry {entry.id}')
                    except Exception as e:
                        log.warning(f'sync: embedding failed for {entry.id}: {e}')

                if entry.id not in summarized_ids:
                    try:
                        if llm is None:
                            llm = _get_llm()
                        generate_entry_summary(entry, llm)
                        log.info(f'sync: summarized entry {entry.id}')
                    except Exception as e:
                        log.warning(f'sync: summary failed for {entry.id}: {e}')

            log.info('sync: done')
    finally:
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
            if not _env_bool('LLM_WARMUP_ON_LOAD', True):
                return
            try:
                _get_llm()
            except Exception as e:
                log.warning(f'LLM warmup failed: {e}', exc_info=True)
            try:
                from .memory import _get_embed_model
                _get_embed_model()
            except Exception as e:
                log.warning(f'Embedding warmup failed: {e}')
    except Exception as e:
        log.warning(f'Warmup failed: {e}')
