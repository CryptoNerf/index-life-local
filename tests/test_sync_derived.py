"""Tests for syncing the LLM-derived AI data (snapshot v3).

The contract: derived data (summaries, monthly summaries, profile, extracted
people/activities, alias merges) is merged STRICTLY ADDITIVELY and keyed by
the entry's cross-device UUID. A device must never lose derived data it
computed itself — it only gains coverage for entries a peer processed first.
The single exception is the one psychological profile, where the version that
analysed more entries wins (a regenerable summary, more entries = strictly
more complete).
"""
from datetime import datetime, date as date_type

from app import db
from app.models import (
    MoodEntry, EntrySummary, PeriodSummary, UserPsychProfile,
    EntryPerson, EntryActivity, PersonAlias, SyncMeta, DailySignal,
)
from app import sync


OLD = datetime(2025, 1, 1, 12, 0, 0)
NEW = datetime(2025, 2, 1, 12, 0, 0)


# ── helpers ───────────────────────────────────────────────────

def _set_device(device_id='me'):
    db.session.add(SyncMeta(key='device_id', value=device_id))
    db.session.commit()


def _local_entry(date_str, uuid, rating=5, note='local'):
    e = MoodEntry(
        date=date_type.fromisoformat(date_str), rating=rating, note=note,
        deleted=False, created_at=OLD, updated_at=OLD, uuid=uuid,
    )
    db.session.add(e)
    db.session.commit()
    return e


def _remote_entry(date_str, uuid, rating=5, note='remote'):
    return {
        'uuid': uuid, 'date': date_str, 'rating': rating, 'note': note,
        'created_at': OLD.isoformat(), 'updated_at': NEW.isoformat(),
        'device_id': 'peer1', 'deleted': False,
    }


def _snap(device_id='peer1', entries=None, summaries=None, people=None,
          activities=None, periods=None, aliases=None, profile=None):
    return {
        'snapshot_version': 3,
        'device_id': device_id,
        'generated_at': NEW.isoformat(),
        'mood_entries': entries or [],
        'chat_messages': [],
        'user_profile': None,
        'entry_summaries': summaries or [],
        'entry_people': people or [],
        'entry_activities': activities or [],
        'period_summaries': periods or [],
        'person_aliases': aliases or [],
        'psych_profile': profile,
    }


# ── summaries: additive, keyed by uuid, local wins ────────────

def test_peer_summary_imported_for_existing_entry(app):
    _set_device()
    e = _local_entry('2025-05-01', uuid='U1')  # local has the entry, no summary

    stats = sync.apply_snapshot(_snap(summaries=[
        {'entry_uuid': 'U1', 'summary': 'from peer', 'themes': '[]',
         'created_at': OLD.isoformat()},
    ]))

    assert stats['summaries_inserted'] == 1
    s = EntrySummary.query.filter_by(entry_id=e.id).first()
    assert s is not None and s.summary == 'from peer'


def test_local_summary_kept_when_both_have_one(app):
    """Answers 'which is kept?' — the local one. Nothing is overwritten."""
    _set_device()
    e = _local_entry('2025-05-01', uuid='U1')
    db.session.add(EntrySummary(entry_id=e.id, summary='MINE', themes='[]',
                                created_at=NEW))
    db.session.commit()

    stats = sync.apply_snapshot(_snap(summaries=[
        {'entry_uuid': 'U1', 'summary': 'PEER', 'themes': '[]',
         'created_at': OLD.isoformat()},
    ]))

    assert stats['summaries_inserted'] == 0
    assert EntrySummary.query.filter_by(entry_id=e.id).count() == 1
    assert EntrySummary.query.filter_by(entry_id=e.id).first().summary == 'MINE'


def test_peer_only_entry_and_its_summary_both_imported(app):
    """A day only the peer has: the entry is inserted, then its summary is
    resolved by uuid to that just-inserted local row."""
    _set_device()
    stats = sync.apply_snapshot(_snap(
        entries=[_remote_entry('2025-06-01', uuid='U2')],
        summaries=[{'entry_uuid': 'U2', 'summary': 'peer', 'themes': '[]',
                    'created_at': OLD.isoformat()}],
    ))
    assert stats['inserted'] == 1 and stats['summaries_inserted'] == 1
    e = MoodEntry.query.filter_by(uuid='U2').first()
    assert EntrySummary.query.filter_by(entry_id=e.id).first().summary == 'peer'


def test_summary_for_unknown_uuid_is_skipped(app):
    _set_device()
    stats = sync.apply_snapshot(_snap(summaries=[
        {'entry_uuid': 'does-not-exist', 'summary': 'x', 'themes': '[]'},
    ]))
    assert stats['summaries_inserted'] == 0
    assert EntrySummary.query.count() == 0


# ── people / activities: per-entry set, additive ──────────────

def test_people_set_imported_for_entry_with_none(app):
    _set_device()
    e = _local_entry('2025-05-01', uuid='U1')
    stats = sync.apply_snapshot(_snap(people=[
        {'entry_uuid': 'U1', 'mention': 'мама', 'tone': 'positive'},
        {'entry_uuid': 'U1', 'mention': 'Оля', 'tone': 'neutral'},
    ]))
    assert stats['people_inserted'] == 2
    assert EntryPerson.query.filter_by(entry_id=e.id).count() == 2


def test_local_people_kept_when_entry_already_has_some(app):
    _set_device()
    e = _local_entry('2025-05-01', uuid='U1')
    db.session.add(EntryPerson(entry_id=e.id, mention='Папа', tone='positive'))
    db.session.commit()

    stats = sync.apply_snapshot(_snap(people=[
        {'entry_uuid': 'U1', 'mention': 'мама', 'tone': 'positive'},
    ]))
    assert stats['people_inserted'] == 0
    mentions = {p.mention for p in EntryPerson.query.filter_by(entry_id=e.id).all()}
    assert mentions == {'Папа'}


def test_activities_imported_and_bad_rows_skipped(app):
    _set_device()
    e = _local_entry('2025-05-01', uuid='U1')
    stats = sync.apply_snapshot(_snap(activities=[
        {'entry_uuid': 'U1', 'activity': 'спорт'},
        {'entry_uuid': 'U1', 'activity': ''},          # blank -> skipped
        {'entry_uuid': 'nope', 'activity': 'чтение'},   # unknown uuid -> skipped
    ]))
    assert stats['activities_inserted'] == 1
    acts = {a.activity for a in EntryActivity.query.filter_by(entry_id=e.id).all()}
    assert acts == {'спорт'}


# ── aliases / period summaries: additive by their stable key ──

def test_aliases_additive_by_alias(app):
    _set_device()
    db.session.add(PersonAlias(alias='Марь', canonical='Мари'))
    db.session.commit()

    stats = sync.apply_snapshot(_snap(aliases=[
        {'alias': 'Марь', 'canonical': 'WRONG'},      # exists -> kept
        {'alias': 'Дима', 'canonical': 'Дмитрий'},     # new -> imported
    ]))
    assert stats['aliases_inserted'] == 1
    assert PersonAlias.query.filter_by(alias='Марь').first().canonical == 'Мари'
    assert PersonAlias.query.filter_by(alias='Дима').first().canonical == 'Дмитрий'


def test_period_summaries_additive_by_key(app):
    _set_device()
    db.session.add(PeriodSummary(period_type='month', period_key='2025-01',
                                 summary='MINE', avg_rating=5, entry_count=3))
    db.session.commit()

    stats = sync.apply_snapshot(_snap(periods=[
        {'period_type': 'month', 'period_key': '2025-01', 'summary': 'PEER',
         'avg_rating': 6, 'entry_count': 9},          # exists -> kept
        {'period_type': 'month', 'period_key': '2025-02', 'summary': 'NEW',
         'avg_rating': 7, 'entry_count': 4},
    ]))
    assert stats['period_summaries_inserted'] == 1
    assert PeriodSummary.query.filter_by(period_key='2025-01').first().summary == 'MINE'
    assert PeriodSummary.query.filter_by(period_key='2025-02').first().summary == 'NEW'


# ── profile: adopt only the version that analysed MORE entries ─

def test_profile_not_downgraded_then_adopted_when_richer(app):
    _set_device()
    db.session.add(UserPsychProfile(profile_json='{"a":1}', version=2,
                                    entries_analyzed=50))
    db.session.commit()

    # Peer analysed fewer entries -> keep local.
    sync.apply_snapshot(_snap(profile={
        'profile_json': '{"b":2}', 'version': 9, 'entries_analyzed': 30,
        'updated_at': NEW.isoformat()}))
    assert UserPsychProfile.query.first().profile_json == '{"a":1}'

    # Peer analysed more entries -> adopt it.
    sync.apply_snapshot(_snap(device_id='peer2', profile={
        'profile_json': '{"c":3}', 'version': 1, 'entries_analyzed': 80,
        'updated_at': NEW.isoformat()}))
    prof = UserPsychProfile.query.first()
    assert prof.profile_json == '{"c":3}'
    assert prof.entries_analyzed == 80


# ── build side: snapshot carries derived data, uuid-keyed ─────

def test_build_snapshot_includes_uuid_keyed_derived(app):
    _set_device('A')
    e = _local_entry('2025-07-01', uuid='UA')
    db.session.add_all([
        EntrySummary(entry_id=e.id, summary='s', themes='[]', created_at=OLD),
        EntryPerson(entry_id=e.id, mention='мама', tone='positive'),
        EntryActivity(entry_id=e.id, activity='спорт'),
        PeriodSummary(period_type='month', period_key='2025-07', summary='p',
                      avg_rating=6, entry_count=1),
        PersonAlias(alias='Марь', canonical='Мари'),
        UserPsychProfile(profile_json='{"x":1}', version=1, entries_analyzed=1),
    ])
    db.session.commit()

    snap = sync.build_snapshot()

    assert snap['snapshot_version'] == 4
    assert snap['entry_summaries'][0]['entry_uuid'] == 'UA'
    assert snap['entry_people'][0]['entry_uuid'] == 'UA'
    assert snap['entry_activities'][0]['entry_uuid'] == 'UA'
    assert snap['period_summaries'][0]['period_key'] == '2025-07'
    assert snap['person_aliases'][0]['alias'] == 'Марь'
    assert snap['psych_profile']['entries_analyzed'] == 1


def test_v2_snapshot_without_derived_keys_is_tolerated(app):
    """An old (v2) peer's snapshot has no derived sections — apply must not
    blow up on the missing keys."""
    _set_device()
    v2 = {
        'snapshot_version': 2, 'device_id': 'peer1',
        'generated_at': NEW.isoformat(),
        'mood_entries': [_remote_entry('2025-08-01', uuid='U8')],
        'chat_messages': [], 'user_profile': None,
    }
    stats = sync.apply_snapshot(v2)
    assert stats['inserted'] == 1
    assert stats['summaries_inserted'] == 0
    assert stats['signals_inserted'] == 0


# ── daily_signals (weather…): additive, then last-write-wins ──

def test_daily_signals_imported_additively(app):
    _set_device()
    snap = {**_snap(), 'daily_signals': [
        {'date': '2026-06-15', 'source': 'weather', 'metric': 'temp_c',
         'value_num': 18.0, 'value_text': None, 'updated_at': NEW.isoformat()},
        {'date': '2026-06-15', 'source': 'weather', 'metric': 'condition',
         'value_num': None, 'value_text': 'Rain', 'updated_at': NEW.isoformat()},
    ]}
    stats = sync.apply_snapshot(snap)
    assert stats['signals_inserted'] == 2
    assert DailySignal.query.filter_by(
        date=date_type.fromisoformat('2026-06-15')).count() == 2


def test_daily_signal_last_write_wins(app):
    _set_device()
    d = date_type.fromisoformat('2026-06-15')
    db.session.add(DailySignal(date=d, source='weather', metric='temp_c',
                               value_num=10.0, updated_at=OLD))
    db.session.commit()

    # Newer peer value -> adopted.
    sync.apply_snapshot({**_snap(), 'daily_signals': [
        {'date': '2026-06-15', 'source': 'weather', 'metric': 'temp_c',
         'value_num': 25.0, 'value_text': None, 'updated_at': NEW.isoformat()}]})
    assert DailySignal.query.filter_by(
        date=d, source='weather', metric='temp_c').first().value_num == 25.0

    # Older peer value -> kept.
    sync.apply_snapshot({**_snap(device_id='peer2'), 'daily_signals': [
        {'date': '2026-06-15', 'source': 'weather', 'metric': 'temp_c',
         'value_num': 99.0, 'value_text': None, 'updated_at': OLD.isoformat()}]})
    assert DailySignal.query.filter_by(
        date=d, source='weather', metric='temp_c').first().value_num == 25.0
