"""An entry that mentions nobody must not be asked about again every launch.

The backfill decided what was pending by looking for entries with a note and
no extracted rows. A note that genuinely mentions no people produces no rows,
so it looked identical to one that had never been processed — and was sent
through the model again at every start, forever. One real diary had 47 such
entries and spent thirteen minutes of inference on them after each launch,
reaching the same conclusion every time, while the user was trying to type.

An index mark records that extraction *ran*, which is the fact that was
missing. The rule stays conservative: an entry is pending only when it has
neither rows nor a mark, so this can only ever remove work, never add it.
"""
import pytest

from app import db
from app.models import MoodEntry, EntryPerson, EntryActivity, EntryIndexMark
from app.modules.assistant import background as bg


@pytest.fixture
def entries(app):
    from datetime import date, timedelta
    made = []
    for i in range(4):
        e = MoodEntry(date=date(2026, 7, 1) + timedelta(days=i), rating=7,
                      note='день %d' % i)
        db.session.add(e)
        made.append(e)
    db.session.commit()
    return [e.id for e in made]


class _Extractor:
    """Stands in for the model. Records which entries it was asked about."""

    def __init__(self, finds=None):
        self.asked = []
        self.finds = finds or {}

    def __call__(self, entry, llm):
        self.asked.append(entry.id)
        for name in self.finds.get(entry.id, []):
            db.session.add(EntryPerson(entry_id=entry.id, mention=name,
                                       tone='neutral'))
        db.session.commit()


@pytest.fixture
def run_backfill(app, monkeypatch):
    """Drive _backfill_people with a stub extractor and no LLM or locks."""
    def go(extractor):
        monkeypatch.setattr(bg, '_get_llm', lambda: object(), raising=False)
        import app.modules.assistant.memory as mem
        monkeypatch.setattr(mem, 'extract_people_mentions', extractor,
                            raising=False)
        import app.modules.assistant.routes as routes
        monkeypatch.setattr(routes, '_get_llm', lambda: object(), raising=False)
        monkeypatch.setattr(bg, '_extract_yield', lambda: 0.0)
        monkeypatch.setattr(bg, '_wait_if_chat_active', lambda: None)
        bg._backfill_people(app)
    return go


def _marks(kind='people'):
    return {m.entry_id for m in EntryIndexMark.query.filter_by(kind=kind).all()}


# ── the loop that used to never end ───────────────────────────

def test_an_entry_that_mentions_nobody_is_asked_about_once(app, entries, run_backfill):
    first = _Extractor()          # finds nothing in anything
    run_backfill(first)
    assert sorted(first.asked) == sorted(entries), 'the first pass skipped work'

    second = _Extractor()
    run_backfill(second)

    assert second.asked == [], 'the same entries were sent through again'


def test_the_mark_is_what_makes_the_difference(app, entries, run_backfill):
    run_backfill(_Extractor())

    assert _marks() == set(entries)


def test_entries_that_did_find_someone_are_also_left_alone(app, entries, run_backfill):
    run_backfill(_Extractor(finds={entries[0]: ['Маша']}))

    again = _Extractor()
    run_backfill(again)

    assert again.asked == []


# ── nothing that should be processed is skipped ───────────────

def test_a_new_entry_is_still_picked_up(app, entries, run_backfill):
    run_backfill(_Extractor())

    from datetime import date
    fresh = MoodEntry(date=date(2026, 8, 1), rating=6, note='новый день')
    db.session.add(fresh)
    db.session.commit()

    seen = _Extractor()
    run_backfill(seen)

    assert seen.asked == [fresh.id]


def test_an_entry_without_a_note_is_never_pending(app, run_backfill):
    from datetime import date
    db.session.add(MoodEntry(date=date(2026, 8, 2), rating=6, note='   '))
    db.session.commit()

    seen = _Extractor()
    run_backfill(seen)

    assert seen.asked == []


def test_an_entry_whose_extraction_raised_stays_pending(app, entries, run_backfill):
    """A crash is not an answer, so it must be retried — the old behaviour."""
    class _Breaks(_Extractor):
        def __call__(self, entry, llm):
            self.asked.append(entry.id)
            if entry.id == entries[1]:
                raise RuntimeError('model fell over')
            super().__call__(entry, llm)

    run_backfill(_Breaks())

    assert entries[1] not in _marks()
    retry = _Extractor()
    run_backfill(retry)
    assert retry.asked == [entries[1]]


# ── a rebuild really rebuilds ─────────────────────────────────

def test_a_full_re_extract_forgets_the_marks(app, entries, run_backfill):
    run_backfill(_Extractor())
    assert _marks() == set(entries)

    EntryPerson.query.delete()
    EntryIndexMark.query.filter_by(kind='people').delete()
    db.session.commit()

    seen = _Extractor()
    run_backfill(seen)

    assert sorted(seen.asked) == sorted(entries)


# ── people and activities are marked apart ────────────────────

def test_the_two_kinds_do_not_mark_for_each_other(app, entries, run_backfill):
    run_backfill(_Extractor())

    assert _marks('people') == set(entries)
    assert _marks('activities') == set()


def test_marking_twice_does_not_duplicate(app, entries):
    bg._mark_indexed(entries, 'people')
    bg._mark_indexed(entries, 'people')

    assert EntryIndexMark.query.filter_by(kind='people').count() == len(entries)


def test_marks_are_not_part_of_the_sync_snapshot(app, entries):
    """Per-device derived state: a peer's marks say nothing about our rows."""
    from app import sync
    bg._mark_indexed(entries, 'people')

    snapshot = sync.build_snapshot()

    assert not any('index_mark' in key or 'index_marks' in key
                   for key in snapshot), sorted(snapshot)
