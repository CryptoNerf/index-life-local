"""
Background processing for new diary entries.
Runs embedding, summarization, and profile updates in a separate thread.
"""
import logging
import threading

from app import db
from app.models import MoodEntry, EntrySummary

log = logging.getLogger(__name__)

_lock = threading.Lock()


def process_entry_async(app, entry_id: int):
    """Spawn a background thread to process a new/updated entry."""
    thread = threading.Thread(
        target=_process_entry,
        args=(app, entry_id),
        daemon=True,
    )
    thread.start()


def reindex_all_async(app):
    """Spawn a background thread to reindex all entries from scratch."""
    thread = threading.Thread(
        target=_reindex_all,
        args=(app,),
        daemon=True,
    )
    thread.start()


def warmup_async(app):
    """Warm up models in a background thread."""
    thread = threading.Thread(
        target=_warmup,
        args=(app,),
        daemon=True,
    )
    thread.start()


def _process_entry(app, entry_id: int):
    """Process a single entry: embedding + summary + maybe profile update."""
    if not _lock.acquire(timeout=1):
        log.info('Background processing already running, skipping.')
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

            # 3. Monthly summary for this entry's month
            try:
                from .memory import generate_month_summary
                generate_month_summary(entry.date.year, entry.date.month, llm)
            except Exception as e:
                log.warning(f'Month summary failed: {e}')

            # 4. Profile update (every 5 entries)
            try:
                update_profile(llm)
                log.info('Profile check complete')
            except Exception as e:
                log.warning(f'Profile update failed: {e}')
    finally:
        _lock.release()


def _reindex_all(app):
    """Reindex all entries from scratch. Triggered manually."""
    if not _lock.acquire(timeout=1):
        log.info('Background processing already running, skipping reindex.')
        return

    try:
        with app.app_context():
            from .memory import (
                update_embedding, generate_entry_summary,
                generate_month_summary, update_profile,
            )
            from .routes import _get_llm

            entries = MoodEntry.query.order_by(MoodEntry.date).all()
            total = len(entries)
            log.info(f'Reindex started: {total} entries')

            # Phase 1: Embeddings (fast, no LLM)
            for i, entry in enumerate(entries):
                try:
                    update_embedding(entry)
                except Exception as e:
                    log.warning(f'Embedding failed for entry {entry.id}: {e}')
                if (i + 1) % 50 == 0:
                    log.info(f'Embeddings: {i + 1}/{total}')
            log.info(f'Embeddings done: {total}')

            # Phase 2: Summaries (needs LLM, slower)
            try:
                llm = _get_llm()
            except Exception as e:
                log.error(f'Cannot load LLM for summaries: {e}')
                return

            for i, entry in enumerate(entries):
                try:
                    generate_entry_summary(entry, llm)
                except Exception as e:
                    log.warning(f'Summary failed for entry {entry.id}: {e}')
                if (i + 1) % 20 == 0:
                    log.info(f'Summaries: {i + 1}/{total}')
            log.info('Summaries done')

            # Phase 3: Monthly summaries
            months = set()
            for entry in entries:
                months.add((entry.date.year, entry.date.month))
            for year, month in sorted(months):
                try:
                    generate_month_summary(year, month, llm)
                except Exception as e:
                    log.warning(f'Month summary failed for {year}-{month}: {e}')
            log.info('Monthly summaries done')

            # Phase 4: Full profile rebuild
            try:
                update_profile(llm, force_rebuild=True)
                log.info('Profile rebuilt')
            except Exception as e:
                log.warning(f'Profile rebuild failed: {e}')

            log.info('Reindex complete')
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
