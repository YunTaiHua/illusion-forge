# Command System

> [中文](../zh-CN/commands.md) | English

## Main Command-Line Options

The `illusion-forge` main command supports the following options, grouped by function:

### Session

| Option | Short | Description |
|--------|-------|-------------|
| `--continue` | `-c` | Continue the most recent conversation (requires `-p`) |
| `--resume <SESSION_ID>` | `-r` | Resume a conversation by session ID (requires `-p`) |
| `--name <NAME>` | `-n` | Set a display name for this session (stored in `tool_metadata.session_name`) |

### Model & Effort

| Option | Short | Description |
|--------|-------|-------------|
| `--model <MODEL>` | `-m` | Model ID in `env_N.model_N` format (e.g. `env_1.model_2`), persists to settings.json |
| `--effort <LEVEL>` | `-e` | Effort level: `low` / `medium` / `high` / `xhigh` / `max`, persists to settings.json |
| `--max-turns <N>` | `-t` | Maximum agentic turns, persists to settings.json |

### Output

| Option | Short | Description |
|--------|-------|-------------|
| `--print <PROMPT>` | `-p` | Non-interactive print mode: execute a single prompt and exit |
| `--output-format <FORMAT>` | - | Output format for `--print` mode: `text` (default) / `json` / `stream-json` |

### Permissions

| Option | Description |
|--------|-------------|
| `--permission-mode <MODE>` | Permission mode: `default` / `plan` / `full_auto` / `yolo`, persists to settings.json |
| `--dangerously-skip-permissions` | Bypass all permission checks (equivalent to `--permission-mode full_auto`, only for sandboxed environments) |

### Global

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |
| `--help` | `-h` | Show help and exit |

---

## Run Modes

`illusion-forge` supports three main run modes:

### 1. Web UI Mode (default)

```bash
illusion-forge                       # Start Web UI (browser opens automatically)
illusion-forge --port 8080            # Launch with custom port
illusion-forge --host 0.0.0.0         # Bind all interfaces
illusion-forge --dev                  # Development mode (Vite dev server)
illusion-forge -m env_1.model_2           # Start Web UI with a specific model
illusion-forge --permission-mode full_auto # Start with auto permission mode
illusion-forge -e high                    # Start with high effort (persists to settings)
```

`illusion-forge` with no arguments is equivalent to `illusion-forge`: it starts the Web UI backend and opens the browser.

### 2. Non-Interactive Print Mode

```bash
illusion-forge -p "Analyze the project structure"
illusion-forge -p "say hi" --output-format json
illusion-forge -p "refactor this" -t 10
illusion-forge -e high -p "Analyze code"  # Persist effort and execute
```

### 3. Session Resume Mode

```bash
illusion-forge -c -p "Continue analysis"           # Continue the most recent session (requires -p)
illusion-forge -r <session-id> -p "Continue"       # Resume a specific session (requires -p)
illusion-forge -c -p "Continue" --name "feature-work"  # Continue and name the session
```

Note: `-c`/`-r` require `-p`; without `-p` the command errors out.

---

## Parameter Pass-Through

Core command options (model/effort/max_turns/permission_mode/name/continue/resume) are passed through to the Web backend host (`WebBackendHost`), ensuring they take effect in Web UI mode, print mode, and `-c`/`-r` session resume mode.

### Common Combinations

```bash
# Model + permission mode
illusion-forge -m env_1.model_2 --permission-mode plan

# High effort + print mode (persists effort)
illusion-forge -e high -p "Analyze performance bottlenecks in this code"

# Limit turns + print mode (persists max_turns)
illusion-forge -t 5 -p "Quick syntax check"

# Continue session + print mode
illusion-forge -c -p "Continue the previous task"

# Name a session
illusion-forge --name "debug-auth-issue"
```

---

## Subcommands

```bash
# Web UI
illusion-forge                     # Launch Web UI in browser (default port 3000)
illusion-forge --port 8080         # Launch with custom port
illusion-forge --host 0.0.0.0      # Bind all interfaces
illusion-forge --dev               # Development mode
illusion-forge --trusted-host nas.example  # Declare a trusted host (for LAN access to /ws in non-loopback deployments)
illusion-forge --model env_1.model_2  # Start with a specific model

# Authentication management
illusion-forge auth login              # Interactive provider setup (first login guides working directory setup)
illusion-forge auth status             # View credential status for all environments
illusion-forge auth logout [env_N]     # Clear environment credentials
illusion-forge auth switch [env_N]     # Switch active environment
illusion-forge add model [env_N]       # Add model(s) to an existing environment (supports multiple input)

# Working directory management
illusion-forge set                      # Show current working directory
illusion-forge set "E:\Projects\myapp"  # Set working directory (creates if missing)

# MCP management
illusion-forge mcp list                # List MCP servers
illusion-forge mcp add <name> <config> # Add server
illusion-forge mcp remove <name>       # Remove server

# Plugin management
illusion-forge plugin list             # List plugins
illusion-forge plugin install <source> # Install plugin
illusion-forge plugin uninstall <name> # Uninstall plugin

# Channel management (Feishu/WeChat/QQ messaging)
illusion-forge channel login           # Interactive channel setup (select channel → configure credentials)
illusion-forge channel serve           # Run channel daemon in foreground (listen for messages)
illusion-forge channel status          # View channel status (enabled/connected/PID)
illusion-forge channel enable feishu   # Enable a channel
illusion-forge channel disable feishu  # Disable a channel
illusion-forge channel logout feishu   # Clear channel credentials

# Scheduled tasks
illusion-forge cron start              # Start scheduler
illusion-forge cron stop               # Stop scheduler
illusion-forge cron status             # View status
illusion-forge cron serve              # Run cron daemon in foreground (daemon entry point)
illusion-forge cron list               # List tasks
illusion-forge cron toggle <name> <true|false>  # Enable/disable task
illusion-forge cron run <name>         # Manually trigger task
illusion-forge cron history            # View execution history
illusion-forge cron logs               # View scheduler logs

# Self-update
illusion-forge update                  # Check for newer version on GitHub Releases
```

## Interactive Slash Commands

In Web UI sessions, you can use the following commands:

| Category | Command Examples | Description |
|----------|------------------|-------------|
| Session Management | `/help`, `/clear`, `/exit`, `/rewind`, `/delete` | Manage session state |
| Memory Snapshots | `/memory`, `/resume`, `/export`, `/rules` | Memory and session management |
| Configuration | `/config`, `/model`, `/permissions`, `/thinking` | Adjust runtime configuration |
| Reasoning Control | `/effort`, `/max-tokens`, `/turns` | Effort, token limit, turn count control |
| Plugin Extensions | `/skills`, `/hooks`, `/mcp`, `/plugin` | Manage extension features |
| Project Init | `/init` | Initialize project IllusionForge files |
| Multi-Agent | `/continue`, `/agent` | Subagent collaboration and management: `/agent` for completed-task summaries / creation wizard / model settings; `/agent model <name> <env_N.model_M|inherit>` sets a subagent's default model (built-ins persist to settings.json, user/project agents edit the .md). On the Web, manage subagents in the Settings form's "Subagents" tab |

### Non-Interactive Mode (Print Mode) Available Parameters

Use `-p` / `--print <PROMPT>` to enter non-interactive mode: execute a single prompt and exit, suitable for scripts and automation. The following parameters can be used with `-p`:

| Parameter | Short | Description | Persists |
|-----------|-------|-------------|----------|
| `--print <PROMPT>` | `-p` | Enter print mode, PROMPT is the prompt text | No |
| `--output-format <FORMAT>` | - | Output format: `text` (default) / `json` / `stream-json` | No |
| `--model <MODEL>` | `-m` | Model alias or full model ID | Yes (writes `settings.model`) |
| `--effort <LEVEL>` | `-e` | Effort level: `low` / `medium` / `high` / `xhigh` / `max` | Yes (writes `settings.effort`) |
| `--max-turns <N>` | `-t` | Maximum agentic turns | Yes (writes `settings.max_turns`) |
| `--permission-mode <MODE>` | - | Permission mode: `default` / `plan` / `full_auto` / `yolo` | Yes (writes `settings.permission.mode`) |
| `--continue` | `-c` | Continue the most recent session (requires `-p`) | No |
| `--resume <SESSION_ID>` | `-r` | Resume a specific session by ID (requires `-p`) | No |
| `--name <NAME>` | `-n` | Set a display name for this session | No |
| `--dangerously-skip-permissions` | - | Bypass all permission checks (equivalent to `--permission-mode full_auto`) | No |

**Interactive Behavior**:

- **Permission confirmation**: Print mode uses a cross-turn Y/N callback — in `default` mode, tools requiring permission do not execute directly; instead the permission request is persisted and the program exits with code 2, stderr shows `Permission request: {tool}. Use illusion-forge -c -p "Y" to allow once / "N" to deny`:
  1. **Turn 1**: `illusion-forge -p "write a file"` → tool requires permission → persisted to `pending-permission-<session_id>.json` → exit code **2**
  2. **Turn 2**: `illusion-forge -c -p "Y"` → detects pending permission → injects approval result → resumes execution

  **Approval input format** (case-insensitive):
  - **Y** / **yes** / **approve**: Allow once (not persisted, effective only for the current tool call)
  - **N** / any other input: Deny (LLM receives denial message, may try alternative approaches)

  Use `--permission-mode full_auto` to skip permission confirmation entirely; `plan` mode blocks all mutation tools.
- **Sandbox permission confirmation (two options)**: In print mode, a **sandbox restriction** uses a dedicated **two-option** cross-turn confirmation (allow / deny), distinct from the general Y/N flow, and never offers "always allow":
  1. **Turn 1**: `illusion-forge -p "..."` → tool hits a sandbox restriction → persisted to `pending-sandbox-<session_id>.json` → exit code **2**, stderr shows `Sandbox permission request: {tool}. Use illusion-forge -c -p "Y" to allow / "N" to deny`
  2. **Turn 2**: `illusion-forge -c -p "Y"` → allows that single sandboxed operation and resumes; `illusion-forge -c -p "N"` → denies it.

  **High-risk operations**: destructive commands (e.g. `rm`, `git restore`, `Remove-Item`) rank above reads. Even if a path was already allowed for the session, destructive operations on it still trigger sandbox confirmation.
- **ask_user_question interaction**: When the LLM calls the ask_user_question tool, print mode uses a **cross-turn non-interactive** pattern:
  1. **Turn 1**: `illusion-forge -p "do something"` → agent calls ask_user_question during execution → tool persists the question to `pending-question-<session_id>.json`, returns a special marker as tool_result → agent ends the turn → program exits with **exit code 2** (indicating waiting for user answer)
  2. **Turn 2**: `illusion-forge -c -p "<answer>"` → detects pending question → injects the answer as tool_result (replacing the marker) → calls `continue_pending` to resume agent execution

  This design allows IllusionForge to be controlled by other agents: each `-p` invocation is an atomic request-response, without waiting for interactive input within the same turn. Exit code semantics:
  - `0`: Normal completion
  - `1`: Error
  - `2`: Waiting for user answer (answer with `-c -p` next time)

  **Multi-question answer format** (agent-friendly):
  - **Single question**: Enter the answer text directly. For `multiSelect`, separate with commas, e.g. `optionA,optionB`
  - **Multiple questions**: Use JSON format, where keys are the headers shown in brackets:
    ```bash
    illusion-forge -c -p "{\"Fruit\": \"strawberry\", \"OS\": \"Windows\", \"Emoji\": \"less\"}"
    ```
    `multiSelect` values use arrays: `{"Fruit": ["strawberry", "mango"]}`. Non-JSON input is passed as-is to the LLM (backward compatible)
- **Plan approval interaction**: When the LLM calls `exit_plan_mode` in print mode, it uses the same cross-turn pattern as ask_user_question:
  1. **Turn 1**: `illusion-forge -p "implement feature X"` → agent enters plan mode, writes plan file, calls `exit_plan_mode` → plan persisted to `pending-plan-approval-<session_id>.json` → exit code **2**
  2. **Turn 2**: `illusion-forge -c -p "approve"` → detects pending plan approval → injects approval result → resumes execution

  Exit code semantics: 0=normal completion, 1=error, 2=waiting for user input (ask_user_question, plan approval, or permission confirmation).

  **Approval input format**: Input "approve"/"yes"/"y" (case-insensitive) means approved; any other input is treated as rejection with the input as feedback. For example, `illusion-forge -c -p "need more test cases"` is parsed as reject + feedback.
- **Persistence timing**: Parameters marked "Persists" are written to `settings.json` before executing the prompt, so persistence takes effect even if subsequent execution fails.

**Examples**:

```bash
# Basic usage
illusion-forge -p "Analyze the project structure"

# Specify model + JSON output
illusion-forge -m env_1.model_2 -p "List TODO comments" --output-format json

# High effort + limit turns (both persist)
illusion-forge -e high -t 10 -p "Refactor this function"

# Full auto permissions + persist
illusion-forge --permission-mode full_auto -p "Run tests"

# Continue previous session
illusion-forge -c -p "Continue the previous task"

# Resume a specific session
illusion-forge -r <session-id> -p "Continue"

# Combined: model + permission + effort + turns + session resume
illusion-forge -m env_1.model_2 -e max -t 20 --permission-mode full_auto -c -p "Complete this feature"
```
