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


# Detect context: EXE distribution or source checkout.
# Source: <project>/tools/install_modules.py  → parent is project root
# EXE:    <exe_dir>/_internal/tools/install_modules.py → parent is _internal
_script_parent = Path(__file__).resolve().parent.parent  # _internal/ or project root

if _script_parent.name == "_internal":
    # EXE distribution
    ROOT = _script_parent.parent                          # <exe_dir>/
    MODULES_DIR = _script_parent / "app" / "modules"      # _internal/app/modules/
else:
    # Source checkout
    ROOT = _script_parent
    MODULES_DIR = ROOT / "app" / "modules"

# Pre-built CUDA wheels (bundle their own CUDA runtime, no toolkit needed)
CUDA_INDEX_URL = "https://abetlen.github.io/llama-cpp-python/whl/cu124"

# Model download
MODEL_HF_REPO = "Qwen/Qwen3-8B-GGUF"
MODEL_FILENAME = "Qwen3-8B-Q4_K_M.gguf"
MODEL_URL = f"https://huggingface.co/{MODEL_HF_REPO}/resolve/main/{MODEL_FILENAME}"

# Pre-built Vulkan wheel (GitHub Release — no Vulkan SDK needed for users)
GITHUB_REPO = "CryptoNerf/index-life-local"
LLAMA_CPP_VERSION = "0.3.15"
VULKAN_WHEEL_TAG = "v2.3.0"  # Release tag containing Vulkan wheels


def _get_vulkan_wheel_url() -> tuple[str, str]:
    """Return (url, filename) for the pre-built Vulkan wheel matching this OS."""
    ver = LLAMA_CPP_VERSION
    if sys.platform == "win32":
        plat = "win_amd64"
    else:
        plat = "linux_x86_64"
    filename = f"llama_cpp_python-{ver}-cp310-cp310-{plat}.whl"
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


def run_pip(args: list[str], env: dict | None = None) -> None:
    cmd = [sys.executable, "-m", "pip"] + args
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, env=env)


# ---------------------------------------------------------------------------
# Download utilities
# ---------------------------------------------------------------------------

def download_file(url: str, dest: Path, description: str = "") -> None:
    """Download a file with progress indicator. Skips if dest already exists."""
    if dest.exists():
        print(f"  Already exists: {dest.name}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".downloading")

    label = description or dest.name
    print(f"  Downloading {label}...")
    print(f"  URL: {url}")

    def progress_hook(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            mb_done = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            print(f"\r  [{pct:3d}%] {mb_done:.0f}/{mb_total:.0f} MB", end="", flush=True)

    try:
        urllib.request.urlretrieve(url, str(tmp), reporthook=progress_hook)
        print()  # newline after progress
        tmp.rename(dest)
        print(f"  Saved: {dest.name}")
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def download_model() -> None:
    """Download the GGUF model for the assistant module if not present."""
    models_dir = MODULES_DIR / "assistant" / "models"
    dest = models_dir / MODEL_FILENAME

    # Check if any .gguf file already exists
    if models_dir.exists():
        existing = list(models_dir.glob("*.gguf"))
        if existing:
            print(f"  Model already present: {existing[0].name}")
            return

    print()
    print("Downloading AI model (~4.7 GB, this may take a while)...")
    download_file(MODEL_URL, dest, description=f"{MODEL_FILENAME} ({MODEL_HF_REPO})")
    print("  Model download complete!")


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
    run_pip(["install", "sentence-transformers>=2.2.0", "numpy>=1.24.0"])

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

    # Install other deps first
    run_pip(["install", "sentence-transformers>=2.2.0", "numpy>=1.24.0"])

    # Download and install pre-built wheel
    url, filename = _get_vulkan_wheel_url()
    wheel_dest = ROOT / "tmp" / filename

    try:
        download_file(url, wheel_dest, description="pre-built Vulkan wheel")
        run_pip(["install", str(wheel_dest)])
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
    run_pip(["install", "sentence-transformers>=2.2.0", "numpy>=1.24.0"])

    # Build llama-cpp-python from source with Vulkan
    run_pip(
        ["install", "llama-cpp-python>=0.2.0,!=0.3.16", "--no-cache-dir"],
        env=env,
    )


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

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
