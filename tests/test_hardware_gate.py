"""Hardware gate for the AI-psychologist module.

The assistant runs a ~9B model locally; on under-spec machines it fails to
load or thrashes the system. The Modules page must only offer it where it
can run, and the install endpoint must REFUSE it server-side (a disabled
button is only a hint).
"""
import pytest

from app import hardware

# The real probe, kept before the autouse fixture below replaces it.
_REAL_FREE_DISK_GB = hardware._free_disk_gb


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv('INDEXLIFE_ALLOW_ASSISTANT', raising=False)


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    """The hardware tests must not depend on the disk of whoever runs them;
    the disk tests below set their own numbers."""
    monkeypatch.setattr(hardware, '_free_disk_gb', lambda path: 500.0)
    monkeypatch.setattr(hardware, '_model_present', lambda data_dir: False)


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


# ── Disk space ────────────────────────────────────────────────
# The install writes a 5.7 GB model plus the inference libraries. Running
# out of space halfway through the download leaves a broken install and a
# full disk, so it is refused up front — and the override does not skip
# it, because no setting makes a full disk bigger.

def _disk(monkeypatch, *, free, model_present=False):
    monkeypatch.setattr(hardware, '_free_disk_gb', lambda path: free)
    monkeypatch.setattr(hardware, '_model_present', lambda data_dir: model_present)


def test_a_full_disk_blocks_an_otherwise_capable_machine(monkeypatch):
    _probe(monkeypatch, ram=16.0, apple=True, vram=None)
    _disk(monkeypatch, free=6.0)

    cap = hardware.assistant_capability()

    assert cap['can_run'] is False
    assert cap['reason'] == 'hw.reason_low_disk'
    assert cap['disk_needed_gb'] == hardware.DISK_GB_FULL
    assert cap['disk_free_gb'] == 6.0


def test_enough_disk_lets_it_through(monkeypatch):
    _probe(monkeypatch, ram=16.0, apple=True, vram=None)
    _disk(monkeypatch, free=hardware.DISK_GB_FULL + 0.5)

    assert hardware.assistant_capability()['can_run'] is True


def test_a_downloaded_model_lowers_the_bar(monkeypatch):
    """A reinstall that finds the model on disk needs room only for the
    libraries."""
    _probe(monkeypatch, ram=16.0, apple=True, vram=None)
    _disk(monkeypatch, free=6.0, model_present=True)

    cap = hardware.assistant_capability()

    assert cap['can_run'] is True
    assert cap['disk_needed_gb'] == hardware.DISK_GB_MODEL_PRESENT


def test_weak_hardware_is_told_about_the_hardware_not_the_disk(monkeypatch):
    """Freeing disk space would not help an 8 GB machine."""
    _probe(monkeypatch, ram=8.0, apple=True, vram=None)
    _disk(monkeypatch, free=1.0)

    assert hardware.assistant_capability()['reason'] == 'hw.reason_low_ram'


def test_the_override_does_not_skip_the_disk(monkeypatch):
    _probe(monkeypatch, ram=4.0, apple=False, vram=None)
    _disk(monkeypatch, free=2.0)
    monkeypatch.setenv('INDEXLIFE_ALLOW_ASSISTANT', '1')

    cap = hardware.assistant_capability()

    assert cap['can_run'] is False
    assert cap['reason'] == 'hw.reason_low_disk'


def test_an_unknown_free_space_does_not_block(monkeypatch):
    _probe(monkeypatch, ram=16.0, apple=True, vram=None)
    _disk(monkeypatch, free=None)

    assert hardware.assistant_capability()['can_run'] is True


def test_the_install_refusal_says_how_much_space(client, monkeypatch):
    _probe(monkeypatch, ram=16.0, apple=True, vram=None)
    _disk(monkeypatch, free=3.2)

    resp = client.post('/modules/install',
                       data={'module': 'assistant', 'profile': 'auto'})

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['hw_blocked'] is True
    assert '3.2' in body['error'] and str(hardware.DISK_GB_FULL) in body['error']


def test_the_disk_probe_walks_up_to_a_folder_that_exists(tmp_path):
    """On a first install the data folder may not exist yet."""
    free = _REAL_FREE_DISK_GB(tmp_path / 'not' / 'yet')

    assert free is not None and free > 0


def test_the_command_line_installer_refuses_a_full_disk(monkeypatch, tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        'install_modules_under_test',
        Path(__file__).resolve().parents[1] / 'tools' / 'install_modules.py')
    im = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(im)
    monkeypatch.setattr(im, '_get_models_dir', lambda: tmp_path / 'models')
    monkeypatch.setattr(im, '_model_already_present', lambda: False)

    class _Usage:
        free = 3 * 1024 ** 3
    monkeypatch.setattr(im.shutil, 'disk_usage', lambda p: _Usage())

    with pytest.raises(SystemExit) as stop:
        im.check_disk_space_for_assistant()
    assert 'Not enough disk space' in str(stop.value)
