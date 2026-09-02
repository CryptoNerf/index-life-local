"""Renaming a merged person must not crash, and must not build a loop.

What the user hit: renaming "Марь" to "Мари" showed "Something went wrong".
The log said `UNIQUE constraint failed: person_aliases.alias`, and the table
explained why — it held both "Марь → Мари" and "Мари → Марь". Each name was
the other's alias, so neither ever won and the two groups never merged; the
rename then tried to INSERT a row for a name that already had one.

Two defects, one symptom: the merge path wrote an alias without resolving its
target (that is what made the loop), and the rename path inserted instead of
replacing (that is what raised the error).
"""
import pytest

from app import db
from app.models import PersonAlias
from app.modules.graphics.routes import bp as graphics_bp


@pytest.fixture
def client(app):
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(graphics_bp)
    return app.test_client()


@pytest.fixture(autouse=True)
def assistant_active(app, monkeypatch):
    """Both endpoints are behind the assistant gate."""
    import app.modules.graphics.routes as gr
    monkeypatch.setattr(gr, '_require_assistant', lambda: None)


def _aliases():
    return {a.alias: a.canonical for a in PersonAlias.query.all()}


def _seed(*pairs):
    for alias, canonical in pairs:
        db.session.add(PersonAlias(alias=alias, canonical=canonical))
    db.session.commit()


def _rename(client, frm, to):
    return client.post('/graphics/people/alias/set_canonical', data={
        'current_canonical': frm, 'new_canonical': to})


def _merge(client, alias, canonical):
    return client.post('/graphics/people/alias/create', data={
        'alias': alias, 'canonical': canonical})


# ── the crash ─────────────────────────────────────────────────

def test_renaming_back_to_an_earlier_name_does_not_crash(client, app):
    """The exact sequence from the log: "Марь" was made an alias of "Мари"
    once, and renaming it again tried to insert that row a second time."""
    _seed(('Марь', 'Мари'))

    resp = _rename(client, 'Марь', 'Мари')

    assert resp.status_code == 302
    assert _aliases() == {'Марь': 'Мари'}


def test_renaming_carries_the_group_across(client, app):
    _seed(('Маша', 'Мари'), ('Машей', 'Мари'))

    _rename(client, 'Мари', 'Мария')

    assert _aliases() == {'Маша': 'Мария', 'Машей': 'Мария', 'Мари': 'Мария'}


def test_the_new_name_stops_being_an_alias_of_anything(client, app):
    """It is about to be the displayed name; it cannot also point elsewhere."""
    _seed(('Мари', 'Марь'))

    _rename(client, 'Марь', 'Мари')

    assert _aliases() == {'Марь': 'Мари'}


def test_renaming_twice_in_a_row_settles(client, app):
    _seed(('Дим', 'Дима'))

    _rename(client, 'Дима', 'Димон')
    _rename(client, 'Димон', 'Дима')

    assert _aliases() == {'Дим': 'Дима', 'Димон': 'Дима'}
    assert 'Дима' not in _aliases(), 'the displayed name is nobody\'s alias'


# ── the loop ──────────────────────────────────────────────────

def test_merging_the_other_way_round_does_not_build_a_loop(client, app):
    """This is the write that created "Мари → Марь" beside "Марь → Мари"."""
    _seed(('Марь', 'Мари'))

    _merge(client, 'Мари', 'Марь')

    assert _aliases() == {'Марь': 'Мари'}, 'the reverse edge was written anyway'


def test_merging_into_an_alias_lands_on_the_displayed_name(client, app):
    """Merging "Хачик" into "Мася", which is itself an alias of "Masa",
    must reach "Masa" rather than chain through."""
    _seed(('Мася', 'Masa'))

    _merge(client, 'Хачик', 'Мася')

    assert _aliases()['Хачик'] == 'Masa'


def test_re_merging_an_existing_alias_moves_it(client, app):
    _seed(('Мася', 'Masa'))

    _merge(client, 'Мася', 'Мария')

    assert _aliases() == {'Мася': 'Мария'}


def test_no_name_is_left_pointing_at_itself(client, app):
    _seed(('Вова', 'Vova'))

    _merge(client, 'Вова', 'Вова')

    assert 'Вова' not in _aliases() or _aliases()['Вова'] != 'Вова'


# ── the repair for tables already broken ──────────────────────

def test_the_migration_breaks_an_existing_loop(app):
    """Users already have loops in their table; upgrading has to fix them."""
    from sqlalchemy import inspect, text
    from app import _migrate_v12

    _seed(('Марь', 'Мари'), ('Мари', 'Марь'))

    with db.engine.begin() as conn:
        _migrate_v12(conn, inspect(db.engine))
    db.session.expire_all()

    after = _aliases()
    assert len(after) == 1, 'the loop survived: %r' % after
    # The newest row closed the loop, so it is the one that goes.
    assert after == {'Марь': 'Мари'}


def test_the_migration_flattens_a_chain(app):
    _seed(('Мася', 'Мари'), ('Мари', 'Masa'))

    from sqlalchemy import inspect
    from app import _migrate_v12
    with db.engine.begin() as conn:
        _migrate_v12(conn, inspect(db.engine))
    db.session.expire_all()

    assert _aliases() == {'Мася': 'Masa', 'Мари': 'Masa'}


def test_the_migration_leaves_a_healthy_table_alone(app):
    _seed(('Дим', 'Дима'), ('Димой', 'Дима'), ('Вов', 'Вова'))
    before = _aliases()

    from sqlalchemy import inspect
    from app import _migrate_v12
    with db.engine.begin() as conn:
        _migrate_v12(conn, inspect(db.engine))
    db.session.expire_all()

    assert _aliases() == before
