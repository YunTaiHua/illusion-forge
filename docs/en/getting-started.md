# Getting Started

> [中文](../zh-CN/getting-started.md) | English

## Requirements

- Python >= 3.10
- Windows 10/11 (x64 or arm64)
- Node.js 24: Only required for source installs; the desktop installer bundles Node.js

## Installation

### Recommended: Desktop Installer (Windows)

The simplest way to install IllusionForge on Windows. The NSIS installer bundles Python 3.12 and Node.js 24, creates Start Menu and desktop shortcuts, and sets up the Electron desktop shell.

1. Download `IllusionForge-Setup-<version>.exe` from the [GitHub Releases page](https://github.com/YunTaiHua/illusion-forge/releases).
2. Run the installer (choose an installation directory if desired).
3. Launch `IllusionForge` from the Start Menu or desktop shortcut.

No separate `pip install` or Node.js setup is needed.

### Alternative: Source Install

Clone the repository and install locally. This is recommended for developers who want to modify the source code.

```bash
git clone https://github.com/YunTaiHua/illusion-forge.git
cd illusion-forge
pip install -e ".[dev,all]"
python scripts/build_frontend.py
```

`scripts/build_frontend.py` builds the `frontend/web/dist` assets. Node.js 24 is required for the frontend build.

### Alternative: Editable Install (pip install -e .)

Editable install from source. Like the source install above, it requires Node.js 24 for frontend build.

```bash
git clone https://github.com/YunTaiHua/illusion-forge.git
cd illusion-forge
pip install -e ".[dev,all]"
python scripts/build_frontend.py
```

> **When to use**: Best for developers who want an editable install (live code changes) and the `illusion-forge` command available globally.

### Alternative: uv sync (for development)

`uv sync` creates an editable install within the project directory. It does **not** trigger the hatch build hook, so you must build frontends manually. This is recommended for developers who want to modify the source code.

```bash
git clone https://github.com/YunTaiHua/illusion-forge.git
cd illusion-forge
uv sync

# Build frontends manually (required after uv sync)
python scripts/build_frontend.py
```

> **Note**: `uv sync` does NOT register `illusion-forge` globally. To use it:
>
> ```bash
> # Option 1: Use uv run from the project directory
> cd illusion-forge
> uv run illusion-forge
>
> # Option 2: Activate the virtual environment
> # Windows
> .venv\Scripts\activate
> illusion-forge
>
> # Option 3: Install globally with pip (recommended)
> pip install .
>
> # Option 4: Editable install with pip (global + live code changes)
> pip install -e .
> ```

### Manual frontend build (for source installs only)

If you installed from source and need to rebuild frontends (e.g., after updating frontend code).

**Build script (recommended)**

```bash
python scripts/build_frontend.py              # Build web frontend only
```

**npm directly**

```bash
# Web UI (Vite → dist/)
cd frontend/web
npm install --no-fund --no-audit
npm run build
cd ../..
```

### Key differences

| | Desktop installer | `pip install .` | `pip install -e .` | `uv sync` |
|---|---|---|---|---|
| Source | GitHub Releases | Local git clone | Local git clone | Local git clone |
| Frontend build | Pre-built (included) | Automatic (hatch hook) | Automatic (hatch hook) | Manual |
| Node.js required | **No** | Yes (24+) | Yes (24+) | Yes (24+) |
| `illusion-forge` command | Global | Global | Global | Project-only (via `uv run` or venv activation) |
| Install type | Standard | Standard | Editable | Editable |
| Code changes take effect | Reinstall needed | Reinstall needed | Immediately | Immediately |
| Best for | End users | Contributors | Developers (global + editable) | Developers |

---

## Basic Usage

> **First-time setup**: Run `illusion-forge auth login` first to configure your API credentials. Without authentication (or if the model is unavailable), the program may exit with an error code.

```bash
# First-time: configure authentication
illusion-forge auth login

# Start Web UI in browser (default when no subcommand given)
illusion-forge

# Launch Web UI in browser (explicit)
illusion-forge

# Web UI with custom port
illusion-forge --port 8080

# Non-interactive print mode: read-only analysis (safe in default permission mode)
illusion-forge -p "Analyze the structure of this project"

# Print mode with explicit auto-approval for writes/commands
illusion-forge --permission-mode full_auto -p "Fix the failing tests"

# Specify model
illusion-forge -m env_1.model_2

# Continue most recent session (use with -p)
illusion-forge -c -p "Continue the previous session"

# Restore specific session (use with -p)
illusion-forge -r <session-id> -p "Continue"

# Answer a pending permission/question/plan after exit code 2
illusion-forge -c -p "Y"

# Set permission mode
illusion-forge --permission-mode full_auto

# Set effort level (persists to settings)
illusion-forge -e high
```

---

## Print Mode Details

`-p` / `--print` runs a single prompt non-interactively and exits. It is designed for scripts, CI, and controlling IllusionForge from other agents.

### Important rules

- The `-p` value must be the **last argument** on the command line because typer parses it greedily.
- Use `--permission-mode full_auto` when the task needs to write files or run commands without manual approval.
- In default permission mode, mutating tools exit with code **2** and persist a pending approval. Resume with `illusion-forge -c -p "Y"` (allow once), `"F"` (always allow), or `"N"` (deny).

### Exit codes

| Code | Meaning | Next action |
|------|---------|-------------|
| 0 | Success | Read stdout for the result |
| 1 | Error | Check stderr for details |
| 2 | Waiting for cross-turn input | Answer with `illusion-forge -c -p "<answer>"` |

### Common patterns

```bash
# Read-only analysis (safe)
illusion-forge -p "Find all TODO comments in the codebase"

# Autonomous execution
illusion-forge --permission-mode full_auto -p "Run the test suite and fix failures"

# Structured JSON output for downstream scripts
illusion-forge -p "List all public functions in src/" --output-format json

# Multi-turn conversation
illusion-forge -p "Plan a refactor of auth.py"                 # exits 2 with a question
illusion-forge -c -p '{"Approach": "JWT", "Scope": "full"}'    # continues with the answer
```

---

## Development & Testing

```bash
# Install development dependencies
uv sync --dev

# Run tests
pytest
```

---

## License

This project is open-sourced under the [MIT](../LICENSE) license.

---

## Contributing

Welcome to submit Issues and Pull Requests!
