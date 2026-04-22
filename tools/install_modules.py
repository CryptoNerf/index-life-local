#!/usr/bin/env python
"""
Install optional module dependencies for index.life.

Examples:
  python tools/install_modules.py --list
  python tools/install_modules.py --module assistant --profile auto
  python tools/install_modules.py --module assistant --profile cpu
  python tools/install_modules.py --module assistant --profile cuda
  python tools/install_modules.py --module assistant --profile vulkan
  python tools/install_modules.py --module assistant --profile cuda-source
  python tools/install_modules.py --module assistant --profile vulkan-source
  python tools/install_modules.py --module voice
  python tools/install_modules.py --all --assistant-profile auto
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


# Force UTF-8 on stdout/stderr so progress messages with non-ASCII
# characters (→, ✓, Cyrillic, etc.) don't crash on Windows consoles
# whose default encoding is cp1251/cp866.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


# Detect context: EXE distribution or source checkout.
# Source:  <project>/tools/install_modules.py  → parent.parent is project root
# EXE Win: <exe_dir>/_internal/tools/install_modules.py → parent.parent is _internal
# EXE Mac: <app>/Contents/Frameworks/tools/install_modules.py → parent.parent is Frameworks
#          OR Contents/Resources/tools/install_modules.py (symlink resolved)
_script_parent = Path(__file__).resolve().parent.parent  # _internal/ or Frameworks/ or Resources/ or project root
_IS_FROZEN = _script_parent.name in ("_internal", "Frameworks", "Resources")

if _IS_FROZEN:
    # EXE distribution
    ROOT = _script_parent.parent                          # <exe_dir>/ or Contents/
    MODULES_DIR = _script_parent / "app" / "modules"      # _internal/app/modules/ or Frameworks/app/modules/
    # macOS .app: also check Resources/ for module files
    if not MODULES_DIR.exists():
        _alt = ROOT / "Resources" / "app" / "modules"
        if _alt.exists():
            MODULES_DIR = _alt
else:
    # Source checkout
    ROOT = _script_parent
    MODULES_DIR = ROOT / "app" / "modules"

# Pre-built CUDA wheels (bundle their own CUDA runtime, no toolkit needed)
CUDA_INDEX_URL = "https://abetlen.github.io/llama-cpp-python/whl/cu124"

# Model download
MODEL_HF_REPO = "unsloth/Qwen3.5-9B-GGUF"
MODEL_FILENAME = "Qwen3.5-9B-Q4_K_M.gguf"
MODEL_URL = f"https://huggingface.co/{MODEL_HF_REPO}/resolve/main/{MODEL_FILENAME}"

# Pre-built Vulkan wheel (GitHub Release — no Vulkan SDK needed for users)
GITHUB_REPO = "CryptoNerf/index-life-local"
LLAMA_CPP_VERSION = "0.3.20"
VULKAN_WHEEL_TAG = "v2.5.0"  # Release tag containing Vulkan wheels


def _get_vulkan_wheel_url() -> tuple[str, str]:
    """Return (url, filename) for the pre-built Vulkan wheel matching this OS.

    llama-cpp-python >= 0.3.20 publishes stable-ABI wheels tagged `py3-none`,
    so a single wheel per platform works across all Python 3.x minor versions.
    """
    ver = LLAMA_CPP_VERSION
    if sys.platform == "win32":
        plat = "win_amd64"
    else:
        plat = "linux_x86_64"
    filename = f"llama_cpp_python-{ver}-py3-none-{plat}.whl"
    url = f"https://github.com/{GITHUB_REPO}/releases/download/{VULKAN_WHEEL_TAG}/{filename}"
    return url, filename

ALL_PROFILES = ["auto", "cpu", "vulkan", "cuda", "vulkan-source", "cuda-source", "metal"]


def discover_modules() -> list[str]:
    found = []
    if not MODULES_DIR.exists():
        return found
    for module_path in MODULES_DIR.iterdir():
        if not module_path.is_dir():
            continue
        name = module_path.name
        if name.startswith("_") or name == "__pycache__":
            continue
        if (module_path / "__init__.py").exists():
            found.append(name)
    return sorted(found)


def _resolve_user_base() -> Path:
    """Base dir for user-writable data (venv, models). Mirrors config.py.

    Windows: portable-first (next to exe) with %APPDATA% fallback for
    legacy installs. macOS: Application Support (forced by .app bundle
    code-signing). Linux: ~/.index-life. Source checkout: project root.

    Note: on Windows the installer runs inside the modules_venv's python
    (launched by install_modules.bat), so sys.executable points at the
    venv — not the app. We use ROOT, which install_modules.py already
    computes as the exe's directory via _script_parent.
    """
    if not _IS_FROZEN:
        return ROOT
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "index.life"
    if sys.platform == "win32":
        exe_dir = ROOT  # directory containing index-life.exe
        appdata_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "index.life"
        markers = ("diary.db", "modules_venv", "models", "profile_photos")
        if any((exe_dir / m).exists() for m in markers):
            return exe_dir
        if any((appdata_dir / m).exists() for m in markers):
            return appdata_dir
        return exe_dir
    return Path.home() / ".index-life"


def _get_modules_venv() -> Path:
    """Return path to a dedicated venv for module dependencies."""
    return _resolve_user_base() / "modules_venv"


def _ensure_modules_venv() -> Path:
    """Create modules venv if it doesn't exist. Returns path to venv python.

    If an existing venv was built against a different Python minor version,
    it is wiped and recreated — its C extensions (numpy, llama_cpp) would be
    ABI-incompatible otherwise.
    """
    venv_dir = _get_modules_venv()
    if sys.platform == "win32":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python3"

    # Detect ABI mismatch with an existing venv
    cfg = venv_dir / "pyvenv.cfg"
    if cfg.exists():
        try:
            for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().lower().startswith("version"):
                    _, val = line.split("=", 1)
                    parts = val.strip().split(".")
                    if len(parts) >= 2:
                        vmaj, vmin = int(parts[0]), int(parts[1])
                        cur = (sys.version_info.major, sys.version_info.minor)
                        if (vmaj, vmin) != cur:
                            print(f"Existing modules_venv is Python {vmaj}.{vmin}, "
                                  f"but installer runs on {cur[0]}.{cur[1]}. "
                                  f"Wiping and recreating...")
                            shutil.rmtree(venv_dir, ignore_errors=True)
                    break
        except Exception as exc:
            print(f"  Warning: could not read pyvenv.cfg: {exc}")

    if not venv_python.exists():
        print(f"Creating modules virtual environment at {venv_dir} ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
        print("Virtual environment created.")

    # Verify pip is functional. On Windows, a previously-interrupted
    # `pip install --upgrade pip` can leave pip in a broken state where
    # `pip._internal.cli` is unimportable. Heal it via ensurepip.
    _ensure_pip_works(venv_python)

    return venv_python


def _ensure_pip_works(venv_python: Path) -> None:
    """Make sure `python -m pip --version` succeeds. Heal via ensurepip if not."""
    try:
        subprocess.check_call(
            [str(venv_python), "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return
    except Exception:
        pass

    print("  pip in modules_venv looks broken — repairing via ensurepip...")
    try:
        subprocess.check_call(
            [str(venv_python), "-m", "ensurepip", "--upgrade", "--default-pip"],
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not repair pip in modules_venv: {exc}. "
            f"Try Reset modules and reinstall."
        )


def run_pip(args: list[str], env: dict | None = None) -> None:
    venv_python = _ensure_modules_venv()
    cmd = [str(venv_python), "-m", "pip"] + args
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, env=env)


def ensure_stdlib_pth() -> None:
    """In EXE context, create .pth files so the frozen exe can find stdlib modules.

    PyInstaller bundles a stripped stdlib.  Heavy deps like torch/diskcache
    need modules that were excluded (pickletools, importlib.resources …).
    We create:
    1. stdlib.pth     — adds system Python's Lib to sys.path
    2. _fixstdlib.pth — executable .pth that patches importlib.__path__
                        and adds DLL search directories
    """
    if _script_parent.name != "_internal":
        return  # .pth / DLL-dir workaround is Windows-frozen specific

    # Respect the marker-aware resolver so we target the venv the app
    # actually uses, not whatever happens to sit next to the exe.
    venv_dir = _get_modules_venv()
    cfg = venv_dir / "pyvenv.cfg"
    if not cfg.exists():
        return

    # Parse "home = C:\...\Python310" from pyvenv.cfg
    python_home = None
    try:
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().lower().startswith("home"):
                _, value = line.split("=", 1)
                python_home = Path(value.strip())
                break
    except Exception as exc:
        print(f"  Warning: could not read pyvenv.cfg: {exc}")
        return

    if not python_home:
        return

    # Find stdlib directory
    stdlib = python_home / "Lib"
    if not stdlib.is_dir():
        for p in python_home.glob("lib/python3.*"):
            if p.is_dir():
                stdlib = p
                break
        else:
            return

    site_pkg = venv_dir / "Lib" / "site-packages"
    site_pkg.mkdir(parents=True, exist_ok=True)

    # 1. stdlib.pth — add stdlib to sys.path (fixes pickletools, ipaddress, etc.)
    pth_file = site_pkg / "stdlib.pth"
    pth_file.write_text(str(stdlib) + "\n", encoding="utf-8")
    print(f"  Created stdlib.pth → {stdlib}")

    # 2. _venv_fix.py — helper module that:
    #    - Removes packages bundled by PyInstaller from frozen importer so
    #      modules_venv versions are used instead (PIL, etc.)
    #    - Patches importlib.__path__ for importlib.resources
    #    - Adds DLL search directories for native extensions
    ph = str(python_home)
    sl = str(stdlib)
    fix_module = site_pkg / "_venv_fix.py"
    fix_module.write_text(
        f'''"""Auto-generated by install_modules.py — fixes for PyInstaller frozen exe."""
import importlib
import os
import sys

# --- 1. Remove frozen packages so modules_venv versions are used ---
# PyInstaller bundles PIL etc. but modules_venv has newer/complete versions.
_OVERRIDE = {{"PIL", "Pillow"}}
for _finder in sys.meta_path:
    _toc = getattr(_finder, "toc", None)
    if _toc is None:
        continue
    for _key in list(_toc):
        if _key.split(".")[0] in _OVERRIDE:
            _toc.discard(_key) if isinstance(_toc, set) else _toc.pop(_key, None)

# --- 2. Patch importlib so importlib.resources works ---
importlib.__path__.insert(0, r"{sl}\\importlib")

# --- 3. Add DLL search dirs for native extensions ---
if hasattr(os, "add_dll_directory"):
    # System Python dirs (for _ctypes, _ssl, etc.)
    for _d in [r"{ph}", r"{ph}\\DLLs"]:
        if os.path.isdir(_d):
            os.add_dll_directory(_d)

    # Scan modules_venv site-packages for package DLL dirs
    # (torch/lib, *.libs, ctranslate2/, etc.)
    _sp = os.path.dirname(os.path.abspath(__file__))
    for _entry in os.listdir(_sp):
        _full = os.path.join(_sp, _entry)
        if not os.path.isdir(_full):
            continue
        # torch/lib — main DLL directory for PyTorch
        _lib = os.path.join(_full, "lib")
        if os.path.isdir(_lib):
            os.add_dll_directory(_lib)
        # *.libs dirs (e.g. numpy.libs, tokenizers.libs)
        if _entry.endswith(".libs"):
            os.add_dll_directory(_full)

# --- 4. Block torch import (not needed, breaks in frozen exe) ---
# CTranslate2 (used by faster_whisper) optionally imports torch.
# In frozen exe torch fails to fully init, leaving a broken partial module
# in sys.modules that causes "has no attribute autograd" errors.
# Block it so CTranslate2 gets a clean ImportError and uses CPU path.
class _BlockTorch:
    def find_module(self, name, path=None):
        if name == "torch" or name.startswith("torch."):
            return self
        return None
    def load_module(self, name):
        raise ImportError(name + " is not available in packaged app")

sys.meta_path.insert(0, _BlockTorch())
''',
        encoding="utf-8",
    )
    # .pth file that imports the fix module (lines starting with "import" are executed)
    fix_pth = site_pkg / "_venv_fix.pth"
    fix_pth.write_text("import _venv_fix\n", encoding="utf-8")
    print(f"  Created _venv_fix.py + _venv_fix.pth (frozen override + importlib + DLL dirs)")


# ---------------------------------------------------------------------------
# Download utilities
# ---------------------------------------------------------------------------

def _head_content_length(url: str) -> int | None:
    """Fetch expected content-length via HEAD (follows redirects). Returns
    None if the server doesn't advertise it (chunked transfer etc.)."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "index-life/2.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
    except Exception:
        return None


def download_file(url: str, dest: Path, description: str = "", max_retries: int = 3) -> None:
    """Download a file with progress indicator, size verification, and retry."""
    if dest.exists():
        print(f"  Already exists: {dest.name}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".downloading")

    label = description or dest.name
    print(f"  Downloading {label}...")
    print(f"  URL: {url}")

    expected_size = _head_content_length(url)
    if expected_size:
        print(f"  Expected size: {expected_size / (1024*1024):.1f} MB")

    import time as _time

    _last_pct = [-1]  # mutable container for closure

    def progress_hook(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            if pct != _last_pct[0]:
                _last_pct[0] = pct
                mb_done = downloaded / (1024 * 1024)
                mb_total = total_size / (1024 * 1024)
                print(f"  [{pct:3d}%] {mb_done:.0f}/{mb_total:.0f} MB", flush=True)

    # Build a proper opener with User-Agent header to avoid 403/429 from CDNs
    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", "index-life/2.0 (https://github.com/CryptoNerf/index-life-local)")]
    urllib.request.install_opener(opener)

    last_error = None
    for attempt in range(1, max_retries + 1):
        _last_pct[0] = -1
        try:
            urllib.request.urlretrieve(url, str(tmp), reporthook=progress_hook)
            print()

            # Verify we got the full file. urllib.urlretrieve only checks
            # Content-Length when it's present — HF CDN often returns chunked
            # transfers with no length, letting a truncated download pass
            # silently. A cross-check against HEAD's Content-Length catches
            # FAT32 4 GB limits and aborted connections.
            actual_size = tmp.stat().st_size
            if expected_size and actual_size < expected_size * 0.99:
                raise IOError(
                    f"Incomplete download: got {actual_size:,} bytes, "
                    f"expected {expected_size:,} bytes. Often caused by "
                    f"FAT32 drives (4 GB file limit) or aborted connection."
                )

            # On Windows, file may be briefly locked after download; retry rename
            for rename_attempt in range(5):
                try:
                    shutil.move(str(tmp), str(dest))
                    break
                except PermissionError:
                    if rename_attempt < 4:
                        _time.sleep(1)
                    else:
                        raise
            print(f"  Saved: {dest.name} ({actual_size / (1024*1024):.1f} MB)")
            return  # success
        except Exception as exc:
            last_error = exc
            # Clean up partial download
            try:
                if tmp.exists():
                    tmp.unlink()
            except PermissionError:
                pass

            if attempt < max_retries:
                wait = attempt * 5
                print(f"\n  Download error: {exc}")
                print(f"  Retrying in {wait}s (attempt {attempt}/{max_retries})...")
                _time.sleep(wait)
            else:
                print(f"\n  Download failed after {max_retries} attempts: {exc}")
                raise


def _get_models_dir() -> Path:
    """Return writable models directory."""
    if _IS_FROZEN:
        return _resolve_user_base() / "models" / "assistant"
    return MODULES_DIR / "assistant" / "models"


def download_model() -> None:
    """Download the GGUF model for the assistant module if not present."""
    models_dir = _get_models_dir()
    dest = models_dir / MODEL_FILENAME

    # Also check bundled models dir (backwards compat)
    bundled_dir = MODULES_DIR / "assistant" / "models"
    for check_dir in [models_dir, bundled_dir]:
        if check_dir.exists():
            existing = list(check_dir.glob("*.gguf"))
            if existing:
                print(f"  Model already present: {existing[0].name}")
                return

    print()
    print("Downloading AI model (~4.7 GB, this may take a while)...")

    # Direct URL download first — emits line-based progress (newline per
    # percent) so the in-app terminal and its SSE stream show progress.
    # huggingface_hub uses tqdm with carriage-returns which the UI strips,
    # making it look frozen. HF is kept as a fallback because it handles
    # CDN edge cases (rate limits, redirects) on some networks.
    try:
        download_file(MODEL_URL, dest,
                      description=f"{MODEL_FILENAME} ({MODEL_HF_REPO})")
        print("  Model download complete!")
        return
    except Exception as exc:
        print(f"  Direct download failed: {exc}")
        print("  Falling back to huggingface_hub...")

    venv_python = _ensure_modules_venv()
    # local_dir_use_symlinks=False: Windows without Developer Mode cannot
    # create symlinks, and HF's default ("auto") may still try. With
    # symlinks off the file is copied/moved directly into local_dir.
    subprocess.check_call([
        str(venv_python), "-c",
        f"from huggingface_hub import hf_hub_download; "
        f"hf_hub_download("
        f"  repo_id='{MODEL_HF_REPO}',"
        f"  filename='{MODEL_FILENAME}',"
        f"  local_dir=r'{models_dir}',"
        f"  local_dir_use_symlinks=False,"
        f")"
    ])
    if dest.exists():
        print(f"  Model download complete: {dest.name}")


# ---------------------------------------------------------------------------
# Detection utilities
# ---------------------------------------------------------------------------

def detect_cuda_toolkit() -> str | None:
    """Detect installed CUDA Toolkit version from nvcc."""
    nvcc = shutil.which("nvcc")
    if not nvcc:
        # Check common Windows location
        cuda_path = os.environ.get("CUDA_PATH", "")
        if cuda_path:
            candidate = Path(cuda_path) / "bin" / "nvcc.exe"
            if candidate.exists():
                nvcc = str(candidate)
    if not nvcc:
        return None
    try:
        out = subprocess.check_output([nvcc, "--version"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if "release" in line.lower():
                # e.g. "Cuda compilation tools, release 13.1, V13.1.105"
                parts = line.split("release")[-1].strip().split(",")[0].strip()
                return parts
    except Exception:
        pass
    return None


def detect_nvidia_driver() -> str | None:
    """Detect NVIDIA driver version from nvidia-smi."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=driver_version", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL,
        )
        return out.strip().split("\n")[0].strip()
    except Exception:
        return None


def detect_nvidia_gpu_name() -> str | None:
    """Detect NVIDIA GPU name from nvidia-smi."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=name", "--format=csv,noheader"],
            text=True, stderr=subprocess.DEVNULL,
        )
        return out.strip().split("\n")[0].strip()
    except Exception:
        return None


def detect_vulkan_sdk() -> str | None:
    """Detect Vulkan SDK path."""
    sdk = os.environ.get("VULKAN_SDK", "")
    if sdk and Path(sdk).is_dir():
        return sdk
    # Common install locations on Windows
    for candidate in [
        Path(r"C:\VulkanSDK"),
        Path(r"F:\VulkanSDK"),
        Path(os.path.expanduser("~/VulkanSDK")),
    ]:
        if candidate.is_dir():
            # Check for direct install (files right in candidate)
            if (candidate / "Include" / "vulkan").is_dir():
                return str(candidate)
            # Check for versioned subdirectory
            versions = sorted(candidate.iterdir(), reverse=True)
            for v in versions:
                if v.is_dir() and (v / "Include" / "vulkan").is_dir():
                    return str(v)
    return None


def auto_select_profile() -> str:
    """Auto-detect the best profile for the current system."""
    # macOS + Apple Silicon → metal
    if sys.platform == "darwin" and platform.machine() == "arm64":
        print("  Detected: Apple Silicon → metal")
        return "metal"

    # NVIDIA GPU → vulkan (pre-built, no SDK needed)
    gpu_name = detect_nvidia_gpu_name()
    if gpu_name:
        print(f"  Detected: {gpu_name} → vulkan (pre-built, no SDK needed)")
        return "vulkan"

    # Check for any nvidia-smi (even if name detection failed)
    if detect_nvidia_driver():
        print("  Detected: NVIDIA GPU → vulkan (pre-built, no SDK needed)")
        return "vulkan"

    # No GPU detected → cpu
    print("  No GPU detected → cpu")
    return "cpu"


# ---------------------------------------------------------------------------
# Requirements resolution
# ---------------------------------------------------------------------------

def resolve_requirements(module_name: str, profile: str | None) -> Path:
    module_path = MODULES_DIR / module_name
    if not module_path.exists():
        raise FileNotFoundError(f"Module not found: {module_name}")

    if profile:
        # Source profiles share requirements with their pre-built counterparts
        req_map = {
            "cuda-source": "cuda",
            "vulkan-source": "vulkan",
            "auto": None,  # auto resolves later
        }
        req_profile = req_map.get(profile, profile)
        if req_profile:
            candidate = module_path / f"requirements.{req_profile}.txt"
            if candidate.exists():
                return candidate

    default_req = module_path / "requirements.txt"
    if not default_req.exists():
        raise FileNotFoundError(f"requirements.txt not found for module: {module_name}")
    return default_req


# ---------------------------------------------------------------------------
# Install functions
# ---------------------------------------------------------------------------

def install_assistant_cuda_prebuilt(requirements_path: Path) -> None:
    """Install assistant with pre-built CUDA wheels (recommended, no toolkit needed)."""
    print()
    print("Installing with pre-built CUDA wheels...")
    print("(No CUDA Toolkit installation required)")
    print()
    run_pip([
        "install", "-r", str(requirements_path),
        "--extra-index-url", CUDA_INDEX_URL,
    ])


def install_assistant_cuda_source() -> None:
    """Build llama-cpp-python from source with CUDA support."""
    cuda_version = detect_cuda_toolkit()
    if not cuda_version:
        print()
        print("ERROR: CUDA Toolkit not found!")
        print("For source build, install CUDA Toolkit from:")
        print("  https://developer.nvidia.com/cuda-downloads")
        print()
        print("Or use --profile cuda (pre-built wheels, no toolkit needed)")
        raise SystemExit(1)

    print()
    print(f"CUDA Toolkit detected: {cuda_version}")
    print("Building llama-cpp-python from source (this may take 20-30 minutes)...")
    print()

    env = os.environ.copy()
    env["CMAKE_ARGS"] = "-DGGML_CUDA=ON -DLLAMA_CURL=OFF"
    env["FORCE_CMAKE"] = "1"

    # Install other deps first (fast)
    run_pip(["install", "sentence-transformers>=2.2.0", "numpy>=1.24.0", "Pillow"])

    # Build llama-cpp-python from source
    run_pip(
        ["install", "llama-cpp-python>=0.2.0,!=0.3.16", "--no-cache-dir"],
        env=env,
    )


def install_assistant_vulkan_prebuilt() -> None:
    """Install assistant with pre-built Vulkan wheel (no SDK needed)."""
    print()
    print("Installing with pre-built Vulkan wheel...")
    print("(No Vulkan SDK needed — uses GPU driver's Vulkan runtime)")
    print()

    # Install non-llama deps + llama-cpp-python's runtime deps up front.
    # We'll install the wheel itself with --no-deps to prevent pip from
    # replacing our pre-built Vulkan wheel with a generic one from PyPI,
    # so anything llama-cpp-python imports at runtime (diskcache, jinja2,
    # typing_extensions) has to be installed explicitly here.
    run_pip([
        "install",
        "sentence-transformers>=2.2.0",
        "numpy>=1.24.0",
        "Pillow",
        "diskcache>=5.6.1",
        "jinja2>=2.11.3",
        "typing-extensions>=4.5.0",
    ])

    # Download and install pre-built wheel
    url, filename = _get_vulkan_wheel_url()
    wheel_dest = ROOT / "tmp" / filename

    try:
        download_file(url, wheel_dest, description="pre-built Vulkan wheel")
        run_pip(["install", str(wheel_dest), "--force-reinstall", "--no-deps"])
    except Exception as exc:
        print()
        print(f"WARNING: Could not download pre-built Vulkan wheel: {exc}")
        print()
        print("Falling back to CPU-only llama-cpp-python...")
        print("(You can re-run with --profile vulkan-source to build with Vulkan SDK)")
        print()
        run_pip(["install", "llama-cpp-python>=0.2.0,!=0.3.16", "--no-cache-dir"])


def install_assistant_vulkan_source() -> None:
    """Build llama-cpp-python from source with Vulkan support."""
    vulkan_sdk = detect_vulkan_sdk()
    if not vulkan_sdk:
        print()
        print("ERROR: Vulkan SDK not found!")
        print("Install Vulkan SDK from:")
        print("  https://vulkan.lunarg.com/sdk/home")
        print()
        print("Or use --profile vulkan (pre-built wheel, no SDK needed)")
        raise SystemExit(1)

    print()
    print(f"Vulkan SDK detected: {vulkan_sdk}")
    print("Building llama-cpp-python with Vulkan support (~5-10 minutes)...")
    print("(No CUDA Toolkit needed — uses GPU driver's Vulkan runtime)")
    print()

    env = os.environ.copy()
    env["VULKAN_SDK"] = vulkan_sdk
    env["PATH"] = str(Path(vulkan_sdk) / "Bin") + os.pathsep + env.get("PATH", "")

    include_dir = str(Path(vulkan_sdk) / "Include")
    lib_file = str(Path(vulkan_sdk) / "Lib" / "vulkan-1.lib")
    cmake_args = "-DGGML_VULKAN=ON -DLLAMA_CURL=OFF"
    if Path(include_dir).is_dir():
        cmake_args += f" -DVulkan_INCLUDE_DIR={include_dir}"
    if Path(lib_file).is_file():
        cmake_args += f" -DVulkan_LIBRARY={lib_file}"

    env["CMAKE_ARGS"] = cmake_args
    env["FORCE_CMAKE"] = "1"

    # Install other deps first (fast)
    run_pip(["install", "sentence-transformers>=2.2.0", "numpy>=1.24.0", "Pillow"])

    # Build llama-cpp-python from source with Vulkan
    run_pip(
        ["install", "llama-cpp-python>=0.2.0,!=0.3.16", "--no-cache-dir"],
        env=env,
    )


_SMOKE_TESTS = {
    "assistant": "import llama_cpp, sentence_transformers, numpy, diskcache, jinja2, typing_extensions",
    "voice": "import faster_whisper",
}


def smoke_test(module_name: str) -> None:
    """Run a quick `python -c "import X"` in the venv to catch missing deps now
    rather than at runtime. Raises SystemExit with a useful message on failure.
    """
    probe = _SMOKE_TESTS.get(module_name)
    if not probe:
        return

    venv_python = _ensure_modules_venv()
    print()
    print(f"Verifying {module_name} imports...")
    try:
        subprocess.check_call(
            [str(venv_python), "-c", probe],
            stdout=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        # Re-run without DEVNULL so the user sees the actual traceback.
        print()
        print(f"Smoke test failed — a runtime dependency is missing. Details:")
        print()
        try:
            subprocess.call([str(venv_python), "-c", probe])
        except Exception:
            pass
        raise SystemExit(
            f"Installation of {module_name} completed package install but "
            f"imports failed. Try Reset modules and reinstall."
        )
    print(f"  {module_name} import check OK.")


def install_module(
    module_name: str,
    profile: str | None = None,
) -> None:
    # Resolve auto profile
    if module_name == "assistant" and profile == "auto":
        print()
        print("Auto-detecting best profile...")
        profile = auto_select_profile()
        print()

    requirements_path = resolve_requirements(module_name, profile)

    if module_name == "assistant" and profile == "cuda":
        install_assistant_cuda_prebuilt(requirements_path)
    elif module_name == "assistant" and profile == "cuda-source":
        install_assistant_cuda_source()
    elif module_name == "assistant" and profile == "vulkan":
        install_assistant_vulkan_prebuilt()
    elif module_name == "assistant" and profile == "vulkan-source":
        install_assistant_vulkan_source()
    elif module_name == "assistant" and profile == "metal":
        env = os.environ.copy()
        cmake_args = env.get("CMAKE_ARGS", "").strip()
        if "-DLLAMA_METAL=on" not in cmake_args:
            cmake_args = (cmake_args + " -DLLAMA_METAL=on").strip()
        env["CMAKE_ARGS"] = cmake_args
        env["FORCE_CMAKE"] = "1"
        run_pip(["install", "-r", str(requirements_path)], env=env)
    else:
        run_pip(["install", "-r", str(requirements_path)])

    # Download model for assistant module
    if module_name == "assistant":
        print()
        download_model()

    # Smoke-test: verify the module's runtime imports actually succeed. This
    # catches missing transitive deps (diskcache, jinja2 etc.) at install
    # time rather than at first chat/voice use.
    smoke_test(module_name)


# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------

def prompt_choice(prompt: str, options: list[str], default: str | None = None) -> str:
    options_str = ", ".join(options)
    default_note = f" [default: {default}]" if default else ""
    while True:
        value = input(f"{prompt} ({options_str}){default_note}: ").strip()
        if not value and default:
            return default
        if value in options:
            return value
        print("Invalid choice, try again.")


def show_gpu_info() -> None:
    """Show GPU info to help user choose profile."""
    gpu_name = detect_nvidia_gpu_name()
    driver = detect_nvidia_driver()
    cuda = detect_cuda_toolkit()
    if gpu_name:
        print(f"  GPU:           {gpu_name}")
    if driver:
        print(f"  NVIDIA driver: {driver}")
    if cuda:
        print(f"  CUDA Toolkit:  {cuda}")
    if not driver and not cuda and not gpu_name:
        print("  No NVIDIA GPU detected")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Install optional module dependencies.")
    parser.add_argument("--list", action="store_true", help="List available modules")
    parser.add_argument("--module", action="append", help="Module to install (repeatable)")
    parser.add_argument("--all", action="store_true", help="Install all discovered modules")
    parser.add_argument(
        "--profile",
        choices=ALL_PROFILES,
        help="Profile for assistant module",
    )
    parser.add_argument(
        "--assistant-profile",
        choices=ALL_PROFILES,
        help="Profile for assistant when using --all",
    )
    args = parser.parse_args()

    modules = discover_modules()
    if args.list:
        if modules:
            print("Available modules:")
            for name in modules:
                print(" -", name)
        else:
            print("No modules found.")
        return 0

    selected = []
    if args.all:
        selected = modules
    elif args.module:
        selected = args.module

    if not selected:
        if not modules:
            print("No modules found.")
            return 1
        print("Available modules:")
        for name in modules:
            print(" -", name)
        raw = input("Enter module name(s) separated by comma, or 'all': ").strip()
        if raw.lower() == "all":
            selected = modules
        else:
            selected = [item.strip() for item in raw.split(",") if item.strip()]

    if not selected:
        print("No modules selected.")
        return 1

    for module_name in selected:
        if module_name not in modules:
            print(f"Unknown module: {module_name}")
            continue

        profile = args.profile if module_name == "assistant" else None
        if module_name == "assistant" and args.all and args.assistant_profile:
            profile = args.assistant_profile

        if module_name == "assistant" and profile is None:
            print()
            print("GPU info:")
            show_gpu_info()
            print()
            print("Profiles:")
            print("  auto          — Auto-detect best GPU option (recommended)")
            print("  cpu           — CPU only (slow but works everywhere)")
            print("  vulkan        — Any GPU, pre-built (NVIDIA/AMD/Intel, recommended)")
            print("  cuda          — NVIDIA GPU, pre-built CUDA 12.4 wheels")
            print("  vulkan-source — Build from source with Vulkan SDK")
            print("  cuda-source   — Build from source with CUDA Toolkit")
            print("  metal         — Apple Silicon GPU (macOS only)")
            print()
            profile = prompt_choice(
                "Select assistant profile",
                ALL_PROFILES,
                default="auto",
            )

        print(f"\nInstalling module: {module_name}" + (f" ({profile})" if profile else ""))
        install_module(module_name, profile=profile)

    # Ensure frozen exe can find stdlib modules needed by deps
    ensure_stdlib_pth()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
