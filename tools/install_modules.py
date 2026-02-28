#!/usr/bin/env python
"""
Install optional module dependencies for index.life.

Examples:
  python tools/install_modules.py --list
  python tools/install_modules.py --module assistant --profile cpu
  python tools/install_modules.py --module assistant --profile cuda --cuda-version 121
  python tools/install_modules.py --module voice
  python tools/install_modules.py --all --assistant-profile cpu
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = ROOT / "app" / "modules"

CUDA_INDEX_URLS = {
    "121": "https://abetlen.github.io/llama-cpp-python/whl/cu121",
    "118": "https://abetlen.github.io/llama-cpp-python/whl/cu118",
}


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


def run_pip(args: list[str], env: dict | None = None, python_exe: str | None = None) -> None:
    python_exe = python_exe or sys.executable
    cmd = [python_exe, "-m", "pip"] + args
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, env=env)


def resolve_venv_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def ensure_venv(venv_path: Path) -> str:
    if not venv_path.exists():
        print(f"Creating venv: {venv_path}")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_path)])
    if os.name == "nt":
        python_exe = venv_path / "Scripts" / "python.exe"
    else:
        python_exe = venv_path / "bin" / "python"
    if not python_exe.exists():
        raise FileNotFoundError(f"Venv python not found at: {python_exe}")
    return str(python_exe)


def resolve_requirements(module_name: str, profile: str | None) -> Path:
    module_path = MODULES_DIR / module_name
    if not module_path.exists():
        raise FileNotFoundError(f"Module not found: {module_name}")

    if profile:
        candidate = module_path / f"requirements.{profile}.txt"
        if candidate.exists():
            return candidate

    default_req = module_path / "requirements.txt"
    if not default_req.exists():
        raise FileNotFoundError(f"requirements.txt not found for module: {module_name}")
    return default_req


def install_module(
    module_name: str,
    profile: str | None = None,
    cuda_version: str | None = None,
    python_exe: str | None = None,
) -> None:
    requirements_path = resolve_requirements(module_name, profile)

    env = os.environ.copy()
    pip_args = ["install", "-r", str(requirements_path)]

    if module_name == "assistant" and profile == "cuda":
        extra_index = env.get("LLAMA_CPP_CUDA_INDEX_URL", "").strip()
        if not extra_index:
            cuda_key = "121"
            if cuda_version:
                cuda_key = "118" if cuda_version in {"118", "11.8"} else "121"
            extra_index = CUDA_INDEX_URLS.get(cuda_key, CUDA_INDEX_URLS["121"])
        pip_args += ["--extra-index-url", extra_index]

    if module_name == "assistant" and profile == "metal":
        cmake_args = env.get("CMAKE_ARGS", "").strip()
        if "-DLLAMA_METAL=on" not in cmake_args:
            cmake_args = (cmake_args + " -DLLAMA_METAL=on").strip()
        env["CMAKE_ARGS"] = cmake_args
        if env.get("LLAMA_FORCE_CMAKE", "").strip():
            env["FORCE_CMAKE"] = "1"

    run_pip(pip_args, env=env, python_exe=python_exe)


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Install optional module dependencies.")
    parser.add_argument("--list", action="store_true", help="List available modules")
    parser.add_argument("--module", action="append", help="Module to install (repeatable)")
    parser.add_argument("--all", action="store_true", help="Install all discovered modules")
    parser.add_argument("--profile", choices=["cpu", "cuda", "metal"], help="Profile for assistant module")
    parser.add_argument("--assistant-profile", choices=["cpu", "cuda", "metal"], help="Profile for assistant when using --all")
    parser.add_argument("--cuda-version", choices=["121", "118"], help="CUDA version for assistant (121 or 118)")
    parser.add_argument("--venv", help="Install modules into a local venv (e.g. modules_venv)")
    args = parser.parse_args()

    venv_raw = args.venv or os.environ.get("INDEXLIFE_MODULES_VENV", "").strip()
    venv_path = resolve_venv_path(venv_raw) if venv_raw else None
    python_exe = ensure_venv(venv_path) if venv_path else None

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
            profile = prompt_choice("Select assistant profile", ["cpu", "cuda", "metal"], default="cpu")

        cuda_version = args.cuda_version
        if module_name == "assistant" and profile == "cuda" and not cuda_version:
            cuda_version = prompt_choice("Select CUDA version", ["121", "118"], default="121")

        print(f"Installing module: {module_name}" + (f" ({profile})" if profile else ""))
        install_module(module_name, profile=profile, cuda_version=cuda_version, python_exe=python_exe)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
