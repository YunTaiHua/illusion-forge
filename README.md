<div align="center">

# IllusionForge

![Python](https://img.shields.io/badge/python-%3E%3D3.10-green) ![Platform](https://img.shields.io/badge/platform-Windows-0078D6) ![License](https://img.shields.io/badge/license-MIT-lightgrey) [![GitHub](https://img.shields.io/badge/github-YunTaiHua%2Fillusion--forge-black)](https://github.com/YunTaiHua/illusion-forge) [![Origin](https://img.shields.io/badge/evolved%20from-illusion--agent-8A2BE2)](https://github.com/YunTaiHua/illusion-agent)

*From conversation to the real machine: an AI agent forged into an engineering workbench for Windows.*

[中文版](README.zh-CN.md) | English

</div>

---

## 📖 Introduction

IllusionForge is an open-source AI agent platform that evolved from
[illusion-agent](https://github.com/YunTaiHua/illusion-agent). It keeps the
entire agent core of illusion-agent — the multi-provider LLM gateway, toolset,
sub-agents, context compaction, MCP / plugin / hook / skill extensions, cron
scheduler and Feishu / WeChat / QQ channels — and narrows the product down to
**Web UI + Windows desktop app + CAD canvas workbench**: discuss design options
with the AI on a shared canvas, generate headless 3D previews, then connect
SolidWorks for real modeling with live visualization.

> Standing on the shoulders of giants — Claude Code prompts, OpenHarness
> architecture, OpenClaw scheduling, kimi-cli infrastructure, hermes-agent
> channels, cc-switch routing, plus the headless geometry and SolidWorks COM
> automation of solidworks-automation-skill.

### Relationship to illusion-agent

IllusionForge is not a feature branch of illusion-agent; it is a **convergent evolution**:

| Aspect | illusion-agent | IllusionForge |
|--------|----------------|---------------|
| Interface | Terminal TUI alongside a Web UI | **Web UI only** (browser / desktop shell); the terminal TUI and its React frontend are removed entirely |
| Platforms | Windows / macOS / Linux | **Windows only** (SolidWorks COM automation exists only on Windows) |
| Distribution | PyPI package + installers for three platforms | **Windows installer on GitHub Releases** + source install; no PyPI package |
| Focus | General coding agent | Coding agent **+ CAD canvas workbench** (real SolidWorks modeling) |
| `illusion-forge` command | Starts a terminal session | Starts the Web UI; `-p` headless mode is kept for cron and scripts |
| Agent core | — | Fully preserved: providers, tools, sub-agents, compaction, MCP, plugins, hooks, skills, channels, Goal, cron |

`illusion-agent` continues as an independent project. IllusionForge keeps the
Python package name `illusion_forge`; the config directory (`~/.illusion/`),
`settings.json` and the session storage format stay compatible with
illusion-agent, so existing configuration carries over unchanged.

### Core Features

- 🧊 **CAD Canvas Workbench** - React Flow shared canvas with requirement cards, design-branch cards, 3D preview cards, snapshot storyboards and parameter tables; a two-way segmented switch in the sidebar toggles between *Chat* and *Workbench*, each with its own independent sessions
- 🔩 **Real SolidWorks Modeling** - A dedicated STA COM host thread serializes 51 CAD tools (sketches, features, assemblies, holes, appearance, motion, drawings, sheet metal, weldments, …); modeling is visualized live through a snapshot stream and a mirrored feature tree
- 🧪 **Headless 3D Preview** - Generate GLB previews with a pure-Python geometry kernel without launching SolidWorks; with OCP installed, STEP / IGES export is added
- 🔁 **Two-way Collaboration & Lineage Audit** - Selections made inside SolidWorks flow back into the agent context; design cards are bound to real documents with dimension-level design-intent diffs
- 🤖 **Multi AI Provider Support** - Anthropic Claude, OpenAI, GitHub Copilot, OpenAI Codex and any OpenAI-compatible endpoint
- 🧠 **Multi-Agent Collaboration** - Built-in specialized agents (general-purpose, explore, verification) with task orchestration
- 🛠️ **Rich Toolset** - Full base toolset + channel tools + MCP dynamic tool extension
- 📦 **Context Compaction** - Microcompact (clear old tool results) + full compaction (LLM summary), auto-triggered as context fills
- 🔌 **Flexible Extension System** - Plugins, hooks, skills, MCP servers
- 🔐 **Comprehensive Permission Control** - Multiple modes + fine-grained rules + one-click Always Allow; trust fence and launch-token auth for the Web UI
- 🎯 **Goal Auto-Continuation** - Long-running goals persist across turns and keep running until verified complete
- ⏰ **Cron Scheduler & Messaging Channels** - Unattended jobs run through headless mode; Feishu, WeChat and QQ channels
- 🌍 **Bilingual** - Chinese / English UI and docs, switched by the `ui_language` setting
- 📦 **Windows Desktop Edition** - Electron shell with bundled Python / Node.js runtimes, one-click NSIS installer, zero environment setup, in-app auto-update

---

## 🚀 Quick Start

### Requirements

- Windows 10 / 11 (x64 or arm64)
- Desktop edition: nothing else — the installer bundles Python 3.12 and Node.js 24
- Running from source: Python >= 3.10 and Node.js 18+ (to build the web frontend)
- Real modeling in the CAD workbench: SolidWorks installed locally (headless previews and canvas discussion do not need it)

### Desktop Edition (recommended)

Download the Windows installer — zero environment setup:

| Platform | File |
|----------|------|
| Windows | `IllusionForge-Setup-<version>.exe` (NSIS installer) |

👉 [Download from GitHub Releases](https://github.com/YunTaiHua/illusion-forge/releases/latest)

The desktop app starts the backend on a random port and loads the Web UI; closing the window minimizes to the tray. See the [desktop docs](docs/en/desktop.md).

### Install from Source

```bash
git clone https://github.com/YunTaiHua/illusion-forge.git
cd illusion-forge

# Backend (with dev extras)
pip install -e ".[dev,all]"

# Web frontend (frontend/web/dist)
python scripts/build_frontend.py
```

### Basic Usage

```bash
# First run: configure authentication (guides you through the working directory afterwards)
illusion-forge auth login

# Start the Web UI (default interface, opens the browser)
illusion-forge

# Start the Web UI on a specific port / host
illusion-forge --port 3200

# Headless mode: run a single prompt and exit
illusion-forge -p "Analyze the structure of this project"

# Set or update the working directory
illusion-forge set "E:\Projects\my-project"

# Check for a newer release (GitHub Releases)
illusion-forge update
```

### Entering the CAD Workbench

1. Click **Workbench** at the bottom of the sidebar (the two-way segmented switch `Chat | Workbench`). The layout switches to the shared canvas plus a conversation panel and a new workbench session is created automatically.
2. Discuss designs with the agent; it creates requirement cards, design-branch cards and 3D preview cards on the canvas.
3. When it is time for real modeling, let the agent connect SolidWorks (`cad_connect`). The floating "Live Modeling" card in the top-right corner expands automatically; switch between the **Viewport / Feature Tree / Snapshots** tabs to follow the modeling process.

Workbench and chat sessions are listed separately and can run side by side without interfering. See the [CAD Canvas Workbench docs](docs/en/cad-workbench.md) for the full guide.

### Headless Mode

`-p` / `--print` executes a single request non-interactively and exits. It is how the cron daemon runs jobs and it suits scripting:

```bash
# Read-only analysis (safe, default permission mode)
illusion-forge -p "Analyze the structure of this project"

# Allow file writes / command execution without interactive approval
illusion-forge --permission-mode full_auto -p "Fix the failing tests"

# After the process exits with code 2, continue answering the pending question / permission / plan
illusion-forge -c -p "Y"

# Pick a model and effort level
illusion-forge -m env_1.model_2 -e high -p "Refactor this module"
```

Important details:

- The prompt must be the **last argument**, because typer parses `-p` greedily.
- In the default permission mode, mutating tools exit with code **2** and leave a pending approval; answer with `illusion-forge -c -p "Y"` or `"N"`.
- Exit codes: `0` success, `1` error, `2` waiting for cross-turn input.
- `-c` / `-r` only make sense in headless mode; the Web UI has its own session list.

---

## 📚 Documentation

| Topic | English | 中文 |
|-------|---------|------|
| Introduction | [docs/en/introduction.md](docs/en/introduction.md) | [docs/zh-CN/introduction.md](docs/zh-CN/introduction.md) |
| Getting Started | [docs/en/getting-started.md](docs/en/getting-started.md) | [docs/zh-CN/getting-started.md](docs/zh-CN/getting-started.md) |
| CAD Canvas Workbench | [docs/en/cad-workbench.md](docs/en/cad-workbench.md) | [docs/zh-CN/cad-workbench.md](docs/zh-CN/cad-workbench.md) |
| Desktop Edition | [docs/en/desktop.md](docs/en/desktop.md) | [docs/zh-CN/desktop.md](docs/zh-CN/desktop.md) |
| Commands | [docs/en/commands.md](docs/en/commands.md) | [docs/zh-CN/commands.md](docs/zh-CN/commands.md) |
| Goal Auto-Continuation | [docs/en/goal.md](docs/en/goal.md) | [docs/zh-CN/goal.md](docs/zh-CN/goal.md) |
| Settings & Credentials | [docs/en/settings.md](docs/en/settings.md) | [docs/zh-CN/settings.md](docs/zh-CN/settings.md) |
| Project Files & Memory | [docs/en/project-files.md](docs/en/project-files.md) | [docs/zh-CN/project-files.md](docs/zh-CN/project-files.md) |
| Extensions (MCP, Plugins, Skills, Hooks) | [docs/en/extensions.md](docs/en/extensions.md) | [docs/zh-CN/extensions.md](docs/zh-CN/extensions.md) |
| Architecture | [docs/en/architecture.md](docs/en/architecture.md) | [docs/zh-CN/architecture.md](docs/zh-CN/architecture.md) |
| Web UI Security | [docs/en/security.md](docs/en/security.md) | [docs/zh-CN/security.md](docs/zh-CN/security.md) |
| Token Metering & Compaction | [docs/en/token-metering.md](docs/en/token-metering.md) | [docs/zh-CN/token-metering.md](docs/zh-CN/token-metering.md) |
| Messaging Channels | [docs/en/channels.md](docs/en/channels.md) | [docs/zh-CN/channels.md](docs/zh-CN/channels.md) |
| @ Mentions (Skills / Sessions / Files) | [docs/en/mentions.md](docs/en/mentions.md) | [docs/zh-CN/mentions.md](docs/zh-CN/mentions.md) |

---

## 📄 License

This project is open source under the [MIT](LICENSE) license. The headless geometry
and SolidWorks COM modules bundled in the CAD workbench come from
[solidworks-automation-skill](https://github.com/wzyn20051216/solidworks-automation-skill)
(MIT License); see the [CAD Canvas Workbench docs](docs/en/cad-workbench.md#upstream-attribution-and-sync)
for attribution and the sync policy.

---

## 🤝 Contributing

Issues and Pull Requests are welcome!

---

</div>
