# Introduction

> [中文](../zh-CN/introduction.md) | English

<div align="center">

**Where fantasy meets functionality.**

*The best of many worlds, refined into one intelligent agent*

</div>

---

IllusionForge is an open-source AI agent platform evolved from [illusion-agent](https://github.com/YunTaiHua/illusion-agent). It unifies a multi-provider LLM gateway, a browser-based Web UI, and a flexible extension ecosystem into a single intelligent agent — at home on Windows.

Whether you prefer the ease of the browser or the power of the desktop, IllusionForge resonates with your workflow: a rich built-in toolset, specialized sub-agents, two compaction methods, MCP server support, hooks, plugins, and a cron scheduler for unattended automation — spanning Feishu, WeChat, and QQ.

> Standing on the shoulders of giants — Claude Code prompts, OpenHarness architecture, OpenClaw scheduling, kimi-cli infrastructure, hermes-agent channels, cc-switch routing.

## Core Features

- 🤖 **Multi AI Provider Support** - Anthropic Claude, OpenAI, GitHub Copilot, OpenAI Codex, and any OpenAI-compatible endpoint
- 🧠 **Multi-Agent Collaboration** - Built-in specialized agents (general-purpose, explore, verification), supporting task orchestration
- 🛠️ **Rich Toolset** - Full base + channel toolset + MCP dynamic tool extension
- 📦 **Context Compaction** - Microcompact (clear old tool results) + full compaction (LLM summary), auto-triggered as context fills
- 🌐 **Web UI Interface** - Browser-based chat interface with `illusion-forge`, featuring warm color design, session management, and real-time streaming
- 🌍 **Bilingual Interface** - All CLI output automatically switches between Chinese and English based on `ui_language` setting
- 📝 **Comprehensive Markdown Rendering** - Box-drawing tables, rounded card-style code blocks, multi-color rich text, links and more
- 📂 **Project-Level Config Friendly** - Auto-generate skills, rules, mcp, plugins directories, project-level skills override global ones
- 🔌 **Flexible Extension System** - Plugins, hooks, skills, MCP servers
- 🔐 **Comprehensive Permission Control** - Four modes (default / plan / full_auto / yolo) + fine-grained rules + session-level / one-time approval
- 💾 **Memory & Context** - Project knowledge persistence and dynamic retrieval
- 🎯 **Reasoning Effort Control** - Supports low/medium/high/xhigh/max five reasoning effort levels with automatic fallback
- 🪟 **Deep Windows Optimization** - Auto-detect Git, PowerShell support, path compatibility optimization
- 🖥️ **Windows Desktop App** - Electron shell with bundled Python and Node.js runtimes, tray integration, and auto-update

## Design Origins & Innovations

**Inherited from Claude Code**: Complete injection of Claude Code's system prompts, tool definitions, permission model, and multi-agent coordination architecture, ensuring behavioral consistency.

**Inspired by OpenHarness**: Python architecture design references OpenHarness's ideas.

**Cron Architecture Aligned with OpenClaw**: The scheduled task system uses the same scheduler architecture as OpenClaw, supporting independent session execution, execution history tracking, and consecutive error monitoring.

**cc-switch Proxy Routing**: Local proxy routing through the cc-switch reverse proxy tool, supporting request forwarding to different AI providers.

**Infrastructure Ported from kimi-cli**: Core infrastructure modules including async queue (aioqueue, Queue + shutdown sentinel, Python < 3.13 polyfill), stderr fd-level redirect (stderr_redirect, StderrRedirector), and cross-platform SIGINT handler (signals) are ported from the kimi-cli project, with only docstring and logging adaptations.

**Channel Implementation Inspired by hermes-agent**: The connection/reconnection/rendering patterns of channel modules — Feishu WS long connection and message rendering strategy, WeChat iLink API client, and QQ Bot WS gateway — are referenced from the hermes-agent project.

**Deep Windows Optimization**: Auto-detect Git installation path, unified PowerShell and Bash tool processing, automatic path separator compatibility, out-of-the-box experience for Windows users.

**Bilingual Interface**: All CLI output (auth, mcp, plugin, cron, session, etc.) automatically switches language via the i18n system based on the `ui_language` field. Language preference can be selected on first run.

**Comprehensive Markdown Rendering**: Full rendering of box-drawing tables, rounded card-style code blocks, multi-color rich text (bold, italic, inline code, links), significantly improving AI response readability.

**Project-Level Config Automation**: Auto-generate `<project>/.illusion/rules/` and `<project>/.illusion/skills/` directories, project-level configuration takes precedence over global configuration, facilitating team collaboration.

**Web UI Interface**: Browser-based chat interface powered by React + Vite + Tailwind CSS frontend and FastAPI + WebSocket backend. Features warm color design, session management, sidebar navigation, real-time streaming responses, right panel with context usage display, and full i18n support. Launch with `illusion-forge`.

## Evolved from illusion-agent

IllusionForge is a focused evolution of [illusion-agent](https://github.com/YunTaiHua/illusion-agent). It retains the full agent core — multi-provider gateway, tools, sub-agents, context compaction, MCP/plugins/hooks/skills, channels, Goal, and cron — while narrowing the product surface to three interfaces:

| Aspect | illusion-agent | IllusionForge |
|--------|---------------|---------------|
| Interactive interface | Terminal TUI (Ink) + Web UI | Web UI only |
| Desktop app | None | Electron shell (Windows) |
| CAD workbench | None | Canvas + SolidWorks live modeling |
| Platforms | Windows, macOS, Linux | Windows 10/11 (x64/arm64) |
| Install | `pip install illusion-agent` (PyPI) | Desktop installer or source install |
| Terminal TUI frontend | `frontend/terminal` (React Ink) | Removed |
| `illusion-forge` (no args) | Starts terminal TUI | Starts Web UI (`illusion-forge`) |
| `--backend-only` | Supported | Removed |

What was kept:
- **Agent core**: multi-provider gateway, tool system, sub-agents, context compaction (micro + full), MCP/plugins/hooks/skills, channels (Feishu/WeChat/QQ), Goal system, cron scheduler
- **Python package name**: `illusion_forge`
- **Config/storage**: `~/.illusion/`, `settings.json`, session format remain compatible
- **Headless mode**: `illusion-forge -p "<prompt>"` for scripts and cron
- **Channel daemons**: Feishu, WeChat, QQ bots unchanged

What was removed or narrowed:
- **Terminal TUI**: the React Ink frontend (`frontend/terminal`), `ui/app.py`, `ui/react_launcher.py`, `ui/terminal_io.py`, and related modules have been removed
- **macOS / Linux desktop builds**: the Windows desktop app is the only desktop distribution
- **PyPI distribution**: no `pip install illusion-forge`; updates come from GitHub Releases
- **`illusion-forge` interactive mode**: defaults to launching the Web UI; the terminal TUI no longer exists
