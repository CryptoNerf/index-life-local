# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""System-capability probe for gating the AI-psychologist module.

The assistant runs a ~9B GGUF locally. On machines that can't hold it the
model either fails to load or thrashes the whole system, so the Modules
page must only offer it where it can actually run. This module answers
"can this machine run the assistant?" with **no heavy imports** (it must
work before llama-cpp/torch are installed), using only stdlib + a couple
of platform CLIs.

Minimum bar (mirrors what the app was tested to run on):

  * Apple Silicon (M-series): unified memory ≥ 16 GB.
  * NVIDIA GPU: VRAM ≥ 8 GB AND system RAM ≥ 16 GB.
  * Otherwise: not offered (an env override exists for power users who
    know their setup — e.g. a big AMD/Intel GPU we can't measure).

`INDEXLIFE_ALLOW_ASSISTANT=1` forces `can_run=True` (advanced/testing).

Disk space is checked as well, and the override does not skip it: the
install writes a 5.7 GB model plus the inference libraries, and running out
of space halfway through a download helps nobody.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess

log = logging.getLogger(__name__)

MIN_RAM_GB = 16
MIN_VRAM_GB = 8

# Free space the assistant install needs, in GB (GiB, like the RAM figures,
# which errs on the side of asking for a little more). The model alone is
# 5.7 GB; the libraries are about 1 GB on a Mac and a few on Windows with
# CUDA builds; the search model and pip's temporary copies need room too.
# A reinstall that finds the model already downloaded needs only the rest.
DISK_GB_FULL = 10
DISK_GB_MODEL_PRESENT = 4


def _total_ram_gb() -> float | None:
    """Physical RAM in GB, or None if it can't be determined."""
    try:
        if os.name == 'nt':
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]

            stat = _MemStatus()
            stat.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullTotalPhys / (1024 ** 3)
            return None
        if hasattr(os, 'sysconf'):
            page = os.sysconf('SC_PAGE_SIZE')
            pages = os.sysconf('SC_PHYS_PAGES')
            if page and pages:
                return (page * pages) / (1024 ** 3)
    except Exception as exc:
        log.debug('RAM probe failed: %s', exc)
    # macOS fallback via sysctl
    try:
        out = subprocess.check_output(
            ['sysctl', '-n', 'hw.memsize'], text=True, timeout=5).strip()
        if out.isdigit():
            return int(out) / (1024 ** 3)
    except Exception:
        pass
    return None


def _is_apple_silicon() -> bool:
    return (platform.system() == 'Darwin'
            and platform.machine().lower() in ('arm64', 'aarch64'))


def _nvidia_vram_gb() -> float | None:
    """Largest NVIDIA GPU's VRAM in GB via nvidia-smi, or None."""
    smi = shutil.which('nvidia-smi')
    if not smi:
        return None
    try:
        out = subprocess.check_output(
            [smi, '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
            stderr=subprocess.DEVNULL, text=True, timeout=10)
    except Exception:
        return None
    vals = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            vals.append(int(line))
    return (max(vals) / 1024.0) if vals else None


def _data_dir():
    """Where the model and the module libraries are written."""
    from pathlib import Path
    try:
        import paths
        return Path(paths.user_data_dir())
    except Exception:
        return Path.home()


def _model_present(data_dir) -> bool:
    """The assistant's GGUF is already on disk (a reinstall or repair)."""
    from pathlib import Path
    candidates = [data_dir / 'models' / 'assistant',
                  Path(__file__).resolve().parent / 'modules' / 'assistant' / 'models']
    for d in candidates:
        try:
            if d.is_dir() and any(d.glob('*.gguf')):
                return True
        except OSError:
            continue
    return False


def _free_disk_gb(path) -> float | None:
    """Free space on the volume holding `path` (or its nearest existing
    parent — the data dir may not exist yet on a first install)."""
    p = path
    try:
        while not p.exists() and p.parent != p:
            p = p.parent
        return shutil.disk_usage(p).free / (1024 ** 3)
    except Exception as exc:
        log.debug('disk probe failed: %s', exc)
        return None


def assistant_disk() -> dict:
    """Is there room to install the assistant? A dict with `disk_free_gb`,
    `disk_needed_gb` and `disk_ok` (True when the free space is unknown —
    better to let the installer try than to block on a failed probe)."""
    data_dir = _data_dir()
    needed = DISK_GB_MODEL_PRESENT if _model_present(data_dir) else DISK_GB_FULL
    free = _free_disk_gb(data_dir)
    return {
        'disk_free_gb': round(free, 1) if free is not None else None,
        'disk_needed_gb': needed,
        'disk_ok': free is None or free >= needed,
    }


def _env_forced() -> bool:
    return (os.environ.get('INDEXLIFE_ALLOW_ASSISTANT') or '').strip().lower() in (
        '1', 'true', 'yes', 'on')


def _hardware_capability() -> dict:
    """Whether this machine's memory and accelerator can run the model.

    The hardware half of `assistant_capability`: a dict with can_run,
    reason (a translation key, resolved in the template so the message
    follows the interface language), ram_gb / vram_gb (rounded, or None
    when unknown), apple_silicon and forced.
    """
    ram = _total_ram_gb()
    apple = _is_apple_silicon()
    vram = None if apple else _nvidia_vram_gb()

    result = {
        'ram_gb': round(ram, 1) if ram else None,
        'vram_gb': round(vram, 1) if vram else None,
        'apple_silicon': apple,
        'forced': False,
    }

    if _env_forced():
        result.update(can_run=True, forced=True, reason='hw.reason_forced')
        return result

    if apple:
        if ram is not None and ram >= MIN_RAM_GB:
            result.update(can_run=True, reason='hw.reason_ok_apple')
        else:
            result.update(can_run=False, reason='hw.reason_low_ram')
        return result

    # Discrete-GPU path (NVIDIA measurable): need both VRAM and RAM.
    if vram is not None:
        if vram >= MIN_VRAM_GB and (ram is None or ram >= MIN_RAM_GB):
            result.update(can_run=True, reason='hw.reason_ok_gpu')
        elif vram < MIN_VRAM_GB:
            result.update(can_run=False, reason='hw.reason_low_vram')
        else:
            result.update(can_run=False, reason='hw.reason_low_ram')
        return result

    # No measurable capable GPU. RAM alone isn't enough for a 9B at usable
    # speed, so we don't offer it — but say why, and point at the override.
    result.update(can_run=False, reason='hw.reason_no_gpu')
    return result


def assistant_capability() -> dict:
    """Whether this machine may install the AI-psychologist module.

    The hardware verdict (see `_hardware_capability`) plus room on disk.
    Returns a UI-ready dict:
      { can_run: bool, reason: str, ram_gb, vram_gb, apple_silicon: bool,
        forced: bool, disk_free_gb, disk_needed_gb, disk_ok: bool }
    `reason` is a translation key; a machine that fails both checks is told
    about the hardware, since freeing disk space would not help it.
    """
    result = _hardware_capability()
    result.update(assistant_disk())
    if result['can_run'] and not result['disk_ok']:
        result.update(can_run=False, reason='hw.reason_low_disk')
    return result
