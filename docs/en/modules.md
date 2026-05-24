# Module system

[← back to index](../README.md) · [Русский](../ru/modules.md)

The core diary (calendar, entries, life-in-weeks, account, sync) works on its own. Everything else is **optional modules** you enable on demand.

| Module | What it adds | Dependencies |
|---|---|---|
| **Graphics** | Mood visualizations | none (activation only) |
| **Customization** | Colors, fonts, background, mosaic | none (activation only) |
| **AI Psychologist** | Chat with a local model | heavy (LLM ~4.7 GB + Python packages) |
| **Neural Map** | A map of your diary's topics | medium (~50 MB, needs AI Psychologist) |

---

## How it works

Modules live in `app/modules/<name>/` and are **auto-discovered** at startup. A module is enabled only if its dependencies are met:

- **Light modules** (graphics, customization) need no packages — they're enabled by a marker file (`graphics_enabled`, `customization_enabled`) in the data directory.
- **Heavy modules** (AI psychologist, neural map) need Python packages, installed into a separate `modules_venv/` environment.

If a module's folder exists but its dependencies aren't installed, the app simply skips it and logs a note.

Enable/install from the **Modules** page inside the app ("Install" button) or with the `install_modules.bat` / `install_modules.sh` scripts.

---

## Installing modules

### Inside the app

<!-- SCREENSHOT: Modules page with install buttons and progress | ../images/modules-page.png -->
Open the **Modules** page → click "Install" on the module. Progress shows right in the window. After installing a heavy module, restart the app.

### Via scripts (from a release / source)

**Windows:** double-click `install_modules.bat` (or with arguments):
```
install_modules.bat --module assistant --profile auto
```

**macOS (Apple Silicon, DMG):** double-click `Install Modules.command` next to the app — it handles everything.

**macOS / Linux (from source):**
```
bash install_modules.sh --module assistant --profile auto
```

The AI psychologist's GGUF model (~4.7 GB) downloads automatically during install.

---

## AI Psychologist GPU profiles

The AI psychologist can run on CPU or GPU. The profile is chosen at install time:

| Profile | GPU | Speed | Requirements |
|---|---|---|---|
| `auto` | Auto-detect | Varies | **Recommended** — picks the best option itself |
| `cpu` | None | ~3–5 tok/s | Any system with 16 GB RAM |
| `vulkan` | Any GPU | ~40–55 tok/s | GPU with Vulkan support (NVIDIA/AMD/Intel), no SDK needed |
| `cuda` | NVIDIA | ~40–50 tok/s | NVIDIA 6 GB+ VRAM, driver 452.39+ |
| `metal` | Apple | ~15–25 tok/s | Apple Silicon Mac |
| `vulkan-source` / `cuda-source` | — | — | Build from source (only if pre-built doesn't work) |

**Which to choose:**
- `auto` — for most cases. Detects your GPU and takes a pre-built wheel, no SDK to install.
- `vulkan` — pre-built wheel, works on any GPU.
- `cuda` — pre-built CUDA 12.4 wheels for NVIDIA (only a modern driver needed).
- `metal` — for Apple Silicon.

> Pre-built Vulkan wheels come from the app's GitHub release. If you re-create releases/tags, see the note in [AI Psychologist → System requirements](ai-psychologist.md#system-requirements).

### NVIDIA requirements
- **Driver:** 452.39+. Check with `nvidia-smi`.
- **VRAM:** 6 GB minimum, 8 GB+ recommended.

---

## Resetting the module environment

If an install broke or hung, the **Modules** page has "Reset modules environment": it wipes `modules_venv/` and reinstalls. **Downloaded AI models are kept** — only Python packages are removed. After resetting, reinstall the modules you need and restart the app.

---

## Python

Python 3.10 is recommended (3.8+ supported). On Windows the installer auto-installs Python if missing.
