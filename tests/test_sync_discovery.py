"""Cloud-folder discovery for one-click sync setup.

The scan must find folders that already hold sync artifacts (the phone's
folder — `device_*.json` / `vault.json`), suggest `<root>/index.life` for
clouds without one, and stay strictly bounded (no deep recursion).
"""
import json

from app.sync_discovery import discover_sync_folders


def _mk(p, files=()):
    p.mkdir(parents=True, exist_ok=True)
    for name in files:
        (p / name).write_text('{}', encoding='utf-8')
    return p


def test_finds_the_phones_google_drive_folder(tmp_path):
    drive = tmp_path / 'Library' / 'CloudStorage' / 'GoogleDrive-me@x.com' / 'My Drive'
    _mk(drive / 'index.life', ['device_abc.json', 'device_def.json', 'vault.json'])
    _mk(drive / 'Photos')                      # unrelated dir — ignored

    found = discover_sync_folders(home=tmp_path)

    assert len(found) == 1
    f = found[0]
    assert f['provider'] == 'Google Drive'
    assert f['kind'] == 'existing'
    assert f['devices'] == 2
    assert f['has_vault'] is True
    assert f['path'].endswith('index.life')


def test_finds_yandex_app_folder_under_prilozheniya(tmp_path):
    yd = tmp_path / 'Yandex.Disk.localized'
    _mk(yd / 'Приложения' / 'index.life app', ['device_phone.json'])

    found = discover_sync_folders(home=tmp_path)

    existing = [f for f in found if f['kind'] == 'existing']
    assert len(existing) == 1
    assert existing[0]['provider'] == 'Яндекс.Диск'
    assert existing[0]['devices'] == 1
    assert existing[0]['has_vault'] is False


def test_suggests_a_new_folder_for_clouds_without_artifacts(tmp_path):
    _mk(tmp_path / 'Dropbox')

    found = discover_sync_folders(home=tmp_path)

    assert len(found) == 1
    f = found[0]
    assert f['kind'] == 'suggested'
    assert f['provider'] == 'Dropbox'
    assert f['path'].endswith('index.life')


def test_existing_folders_sort_before_suggestions(tmp_path):
    _mk(tmp_path / 'Dropbox')                                  # suggestion only
    drive = tmp_path / 'Library' / 'CloudStorage' / 'GoogleDrive-a@b' / 'My Drive'
    _mk(drive / 'index-life-sync', ['device_pc.json'])         # legacy name

    found = discover_sync_folders(home=tmp_path)

    assert [f['kind'] for f in found] == ['existing', 'suggested']


def test_no_cloud_clients_means_no_results(tmp_path):
    assert discover_sync_folders(home=tmp_path) == []


def test_shallow_scan_finds_custom_named_folders(tmp_path):
    _mk(tmp_path / 'Dropbox' / 'мой-дневник', ['device_1.json'])

    found = discover_sync_folders(home=tmp_path)

    existing = [f for f in found if f['kind'] == 'existing']
    assert len(existing) == 1
    assert existing[0]['path'].endswith('мой-дневник')


def test_results_are_json_serializable(tmp_path):
    _mk(tmp_path / 'Dropbox')
    json.dumps(discover_sync_folders(home=tmp_path))
