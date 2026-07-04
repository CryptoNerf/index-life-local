"""create_app initialization order.

The assistant's startup catch-up (sync_missing / backfill) queries
entry_embeddings / entry_summaries right away; when create_app kicked it off
before db.create_all() + migrations, every fresh database (first launch,
restore, new data dir) crashed those threads with "no such table".

The stubs below replace the *_async spawners and run synchronously at the
exact call sites inside create_app, recording whether the tables existed at
that moment — deterministic, no thread timing involved.
"""
from sqlalchemy import inspect as sa_inspect


def test_assistant_catchup_starts_only_after_tables_exist(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, 'user_data_dir', lambda: tmp_path)
    monkeypatch.setenv('SECRET_KEY', 'test')

    # Pretend the assistant module is active without importing its heavy
    # deps — the invariant under test is create_app's call ordering, not
    # module discovery.
    import app.modules as modules_pkg
    monkeypatch.setattr(
        modules_pkg, 'register_modules',
        lambda application: application.config.__setitem__(
            'ACTIVE_MODULES', ['assistant']),
    )

    from app import db
    from app.modules.assistant import background as bg
    from app.modules.assistant import routes as assistant_routes

    seen = {}

    def _probe(name):
        def probe(app_obj, force=False):
            with app_obj.app_context():
                insp = sa_inspect(db.engine)
                seen[name] = (insp.has_table('entry_embeddings')
                              and insp.has_table('entry_summaries')
                              and insp.has_table('mood_entries'))
            return True
        return probe

    monkeypatch.setattr(bg, 'sync_missing_async', _probe('sync_missing'))
    monkeypatch.setattr(bg, 'backfill_assistant_data_async', _probe('backfill'))
    monkeypatch.setattr(bg, 'warmup_async', lambda app_obj: None)
    monkeypatch.setattr(assistant_routes, 'prewarm_model_async',
                        lambda delay_s=0.0: None)

    from app import create_app
    create_app()

    # Both catch-up entry points were invoked, and only once the schema
    # fully existed.
    assert seen == {'sync_missing': True, 'backfill': True}
