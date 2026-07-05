"""Hardware gate for the AI-psychologist module.

The assistant runs a ~9B model locally; on under-spec machines it fails to
load or thrashes the system. The Modules page must only offer it where it
can run, and the install endpoint must REFUSE it server-side (a disabled
button is only a hint).
"""
import pytest

from app import hardware


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv('INDEXLIFE_ALLOW_ASSISTANT', raising=False)


def _probe(monkeypatch, *, ram, apple, vram):
    monkeypatch.setattr(hardware, '_total_ram_gb', lambda: ram)
    monkeypatch.setattr(hardware, '_is_apple_silicon', lambda: apple)
    monkeypatch.setattr(hardware, '_nvidia_vram_gb', lambda: vram)


# ── Apple Silicon ─────────────────────────────────────────────

def test_apple_silicon_16gb_can_run(monkeypatch):
    _probe(monkeypatch, ram=16.0, apple=True, vram=None)
    cap = hardware.assistant_capability()
    assert cap['can_run'] is True
    assert cap['reason'] == 'hw.reason_ok_apple'


def test_apple_silicon_8gb_blocked_on_ram(monkeypatch):
    _probe(monkeypatch, ram=8.0, apple=True, vram=None)
    cap = hardware.assistant_capability()
    assert cap['can_run'] is False
    assert cap['reason'] == 'hw.reason_low_ram'


# ── NVIDIA GPU ────────────────────────────────────────────────

def test_nvidia_8gb_vram_16gb_ram_can_run(monkeypatch):
    _probe(monkeypatch, ram=16.0, apple=False, vram=8.0)
    assert hardware.assistant_capability()['can_run'] is True


def test_nvidia_6gb_vram_blocked_on_vram(monkeypatch):
    _probe(monkeypatch, ram=32.0, apple=False, vram=6.0)
    cap = hardware.assistant_capability()
    assert cap['can_run'] is False
    assert cap['reason'] == 'hw.reason_low_vram'


def test_nvidia_enough_vram_but_low_ram_blocked(monkeypatch):
    _probe(monkeypatch, ram=8.0, apple=False, vram=12.0)
    cap = hardware.assistant_capability()
    assert cap['can_run'] is False
    assert cap['reason'] == 'hw.reason_low_ram'


# ── No capable accelerator ────────────────────────────────────

def test_no_gpu_is_blocked_even_with_lots_of_ram(monkeypatch):
    _probe(monkeypatch, ram=64.0, apple=False, vram=None)
    cap = hardware.assistant_capability()
    assert cap['can_run'] is False
    assert cap['reason'] == 'hw.reason_no_gpu'


# ── Env override ──────────────────────────────────────────────

def test_env_override_forces_can_run(monkeypatch):
    _probe(monkeypatch, ram=4.0, apple=False, vram=None)
    monkeypatch.setenv('INDEXLIFE_ALLOW_ASSISTANT', '1')
    cap = hardware.assistant_capability()
    assert cap['can_run'] is True
    assert cap['forced'] is True


# ── Server-side install enforcement ───────────────────────────

@pytest.fixture
def client(app):
    app.config['SECRET_KEY'] = 'test'
    app.config['ACTIVE_MODULES'] = []
    from app.module_routes import bp, _install_status
    from app import i18n
    # Reset the process-global install state so a stubbed run (which never
    # clears 'running') doesn't 409 the next test.
    _install_status.update({'running': False, 'done': False, 'module': None})
    i18n.register_context_processor(app)
    app.register_blueprint(bp)
    return app.test_client()


def test_install_refused_when_hardware_insufficient(client, monkeypatch):
    _probe(monkeypatch, ram=8.0, apple=True, vram=None)

    resp = client.post('/modules/install',
                       data={'module': 'assistant', 'profile': 'auto'})

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['hw_blocked'] is True


def test_install_allowed_when_hardware_sufficient(client, monkeypatch):
    _probe(monkeypatch, ram=16.0, apple=True, vram=None)
    # Stop the real installer thread from doing anything.
    import app.module_routes as mr
    monkeypatch.setattr(mr, '_run_install', lambda *a, **k: None)

    resp = client.post('/modules/install',
                       data={'module': 'assistant', 'profile': 'auto'})

    assert resp.status_code == 200
    assert resp.get_json().get('started') is True


def test_non_gated_module_ignores_hardware(client, monkeypatch):
    _probe(monkeypatch, ram=4.0, apple=False, vram=None)  # weak machine
    import app.module_routes as mr
    monkeypatch.setattr(mr, '_run_install', lambda *a, **k: None)

    resp = client.post('/modules/install',
                       data={'module': 'graphics', 'profile': 'auto'})

    # graphics is a sentinel module — no hardware gate applies
    assert resp.status_code == 200
