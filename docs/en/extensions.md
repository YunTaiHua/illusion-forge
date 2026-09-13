# Extensions: MCP, Rules, Plugins, Skills & Hooks

> [中文](../zh-CN/extensions.md) | English

## Table of Contents

- [Overview](#overview)
- [MCP Server Configuration](#mcp-server-configuration)
- [Rules Configuration](#rules-configuration)
- [Plugin System](#plugin-system)
- [Skill System](#skill-system)
- [Hook System](#hook-system)

---

## Overview

IllusionForge provides a layered extension system. Extensions can be configured at three levels (priority high → low):

1. **Plugin-level** — bundled with plugins, auto-loaded
2. **Project-level** — in `{cwd}/.illusion/` directory
3. **Global-level** — in `~/.illusion/` or `settings.json`

---

## MCP Server Configuration

### Configuration Types

| Type | Fields | Description |
|------|--------|-------------|
| `stdio` | command, args, env, cwd, log_file, enabled | Standard I/O communication |
| `http` | url, headers, enabled | HTTP protocol (Streamable HTTP; aliases: `streamable-http`/`streamableHttp`/`streamable_http`/`streamablehttp`) |
| `sse` | url, headers, enabled | Server-Sent Events protocol |

All types support `enabled` field (default `true`). Set to `false` to disable without removing config.

The `type` field is optional. When omitted, the server is treated as `stdio` by default:

```json
{
  "command": "python",
  "args": ["server.py"]
}
```

You only need to specify `type` explicitly for non-stdio transports (`http`/`sse`).

### Three Configuration Sources (priority high → low)

#### 1. Plugin MCP

From `{plugin_dir}/mcp.json` or `{plugin_dir}/.mcp.json`. Registered as `{plugin_name}:{server_name}`.

#### 2. Project-level MCP (`{cwd}/.illusion/mcp/*.json`)

Scan all `*.json` files in the directory. Supports two formats:

**Single server** (filename = server name):
```json
{
  "command": "python",
  "args": ["server.py"],
  "enabled": true
}
```

Omitting `type` defaults to `stdio`.

**Multi server** (with `mcpServers` key):
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"]
    },
    "remote-api": {
      "type": "http",
      "url": "https://api.example.com/mcp",
      "headers": {"Authorization": "Bearer token"}
    }
  }
}
```

Above, `filesystem` omits `type` and defaults to `stdio`; `remote-api` is explicitly declared as `http`.

Both `mcpServers` and `mcp_servers` key names are supported.

#### 3. Global MCP (`settings.json`)

In the `mcp_servers` field of `~/.illusion/settings.json`:

```json
{
  "mcp_servers": {
    "my-server": {
      "command": "python",
      "args": ["server.py"],
      "enabled": true
    }
  }
}
```

Omitting `type` defaults to `stdio`.

CLI management:
```bash
illusion-forge mcp list
illusion-forge mcp add <name> <config>
illusion-forge mcp remove <name>
```

### Source Reference

- Config loading: `src/illusion/mcp/config.py`
- Type definitions: `src/illusion/mcp/types.py`

---

## Rules Configuration

Rules are `.md` files that provide project-specific instructions to the AI.

### Discovery Locations

Rules are discovered from:
1. `{cwd}/.claude/rules/*.md` — sorted by filename
2. AI instruction files (`CLAUDE.md`, `ILLUSION.md`, `AGENTS.md`) in project root and `.claude/`/`.illusion/` directories

### Rule File Format

Each `.md` file is an independent rule. The filename determines the sort order:

```
.claude/rules/
├── 01-python-style.md
├── 02-testing.md
└── 03-git-workflow.md
```

### Initialization

The `/init` command generates default rules at `.illusion/rules/`:
- `python-style.md` — Python code style rules
- `testing.md` — Testing framework and conventions
- `project-structure.md` — Project structure guide

### Source Reference

- Discovery logic: `src/illusion/prompts/claudemd.py` — `discover_claude_md_files()`
- Rule generation: `src/illusion/commands/init/generation/rules.py`

---

## Plugin System

### Plugin Directories

1. **User-level**: `~/.illusion/plugins/`
2. **Project-level**: `{cwd}/.illusion/plugins/`

### Plugin Discovery

Each subdirectory must contain `plugin.json` or `.claude-plugin/plugin.json`.

### Plugin Manifest (plugin.json)

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My custom plugin",
  "enabled_by_default": true,
  "skills_dir": "skills",
  "hooks_file": "hooks.json",
  "mcp_file": "mcp.json"
}
```

Full manifest fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Plugin name |
| `version` | string | "0.0.0" | Plugin version |
| `description` | string | "" | Plugin description |
| `enabled_by_default` | bool | true | Enable when first discovered |
| `skills_dir` | string | "skills" | Skills subdirectory name |
| `hooks_file` | string | "hooks.json" | Hooks config filename |
| `mcp_file` | string | "mcp.json" | MCP config filename |
| `commands` | string\|list\|dict | null | Command definitions |
| `agents` | string\|list | null | Agent definitions |
| `hooks` | string\|dict\|list | null | Hook definitions |
| `settings` | dict | null | Plugin default settings |

### Plugin Directory Structure

```
my-plugin/
├── plugin.json              # or .claude-plugin/plugin.json
├── skills/
│   ├── my-skill/
│   │   └── SKILL.md
│   └── another-skill.md
├── commands/                # Slash commands (.md files)
├── agents/                  # Agent definitions (.md files)
├── hooks/
│   └── hooks.json           # Hook definitions
├── mcp.json                 # MCP server configuration
└── settings.json            # Plugin default settings
```

### Plugin Enable/Disable

Controlled by `settings.enabled_plugins` in `~/.illusion/settings.json`:

```json
{
  "enabled_plugins": {
    "my-plugin": true,
    "disabled-plugin": false
  }
}
```

If not configured, uses `manifest.enabled_by_default`.

### Plugin Skill Naming

All plugin skills are registered with format `{plugin_name}:{skill_name}` to avoid conflicts.

### Plugin Hook Variables

Hook commands support `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` variable substitution.

### CLI Management

```bash
illusion-forge plugin list
illusion-forge plugin install <source>
illusion-forge plugin uninstall <name>
illusion-forge plugin enable <name>
illusion-forge plugin disable <name>
```

### Source Reference

- Plugin loader: `src/illusion/plugins/loader.py`
- Manifest schema: `src/illusion/plugins/schemas.py`
- Plugin types: `src/illusion/plugins/types.py`

---

## Skill System

### Skill Sources (priority order)

1. **Builtin skills**: `src/illusion/skills/bundled/content/*.md`
2. **User skills**: `~/.illusion/skills/*.md` (or `.yaml`/`.yml`)
3. **Project skills**: `{cwd}/.illusion/skills/` — supports two formats:
   - Directory format: `{skills_dir}/{skill_name}/SKILL.md` (priority)
   - File format: `{skills_dir}/{skill_name}.md`
4. **Plugin skills**: from all enabled plugins' skill directories

Later registrations override earlier ones with the same name.

### SKILL.md Format

Supports YAML frontmatter:

```markdown
---
description: What this skill does
allowed-tools: Bash, Read, Write
model: claude-sonnet-4-6
context: fork
effort: high
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: echo check
---

Skill content in markdown...
```

#### Frontmatter Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Skill name (auto-derived from filename if omitted) |
| `description` | string | Skill description (shown in skill list) |
| `allowed-tools` | string\|list | Comma-separated or list of allowed tool names |
| `model` | string | Model override for this skill |
| `context` | string | `inline` (expand into conversation) or `fork` (sub-agent) |
| `effort` | string | Reasoning effort override |
| `hooks` | object | Hooks to register when skill is invoked |
| `agent` | string | Agent type to use |
| `disable_model_invocation` | bool | Disable model invocation |
| `skill_root` | string | Root directory for skill resources |

### Built-in Skills

| Skill | Description |
|-------|-------------|
| `debug` | Systematic debugging workflow |
| `verify` | Code change verification |
| `loop` | Recurring task execution |
| `batch` | Batch operations |
| `remember` | Memory management |
| `simplify` | Code review for reuse and quality |
| `skillify` | Convert patterns into skills |
| `stuck` | Break through blockers |
| `update-config` | Configure settings.json |

### Source Reference

- Skill loader: `src/illusion/skills/loader.py`
- Skill types: `src/illusion/skills/types.py`
- Skill registry: `src/illusion/skills/registry.py`

---

## Hook System

### Supported Events (27 events)

| Event | Matcher | Description |
|-------|---------|-------------|
| `PreToolUse` | tool_name | Before tool execution |
| `PostToolUse` | tool_name | After tool execution |
| `PostToolUseFailure` | tool_name | After tool execution fails |
| `PermissionDenied` | tool_name | After auto mode classifier denies |
| `Notification` | notification_type | When notifications are sent |
| `UserPromptSubmit` | — | When user submits a prompt |
| `SessionStart` | source | New session started |
| `SessionEnd` | reason | Session ending |
| `Stop` | — | Before Claude concludes response |
| `StopFailure` | error | Turn ends due to API error |
| `SubagentStart` | agent_type | Subagent started |
| `SubagentStop` | agent_type | Subagent concludes |
| `PreCompact` | trigger | Before compaction |
| `PostCompact` | trigger | After compaction |
| `PermissionRequest` | tool_name | Permission dialog displayed |
| `Setup` | trigger | Repo setup |
| `ConfigChange` | source | Configuration file changes |
| `InstructionsLoaded` | load_reason | Instruction file loaded |
| `WorktreeCreate` | — | Create worktree |
| `WorktreeRemove` | — | Remove worktree |
| `CwdChanged` | — | Working directory changes |
| `FileChanged` | — | Watched file changes |
| `TaskCreated` | — | Task being created |
| `TaskCompleted` | — | Task being completed |
| `TeammateIdle` | — | Teammate about to idle |
| `Elicitation` | mcp_server_name | MCP elicitation request |
| `ElicitationResult` | mcp_server_name | After user responds to elicitation |

### Hook Types

| Type | Required | Optional | Description |
|------|----------|----------|-------------|
| `command` | `command` | `if`, `shell`, `timeout`, `statusMessage`, `once`, `async` | Execute shell command |
| `prompt` | `prompt` | `if`, `model`, `timeout`, `statusMessage`, `once` | Use LLM for verification |
| `http` | `url` | `if`, `timeout`, `headers`, `allowedEnvVars`, `statusMessage`, `once` | Send HTTP POST |
| `agent` | `prompt` | `if`, `model`, `timeout`, `statusMessage`, `once` | Use Agent for verification |

### Hook Configuration Format

Matcher-based structure:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'Tool: $ARGUMENTS' >> /tmp/tool.log",
            "timeout": 30
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "http",
            "url": "https://hooks.example.com/tool-complete",
            "headers": {"Authorization": "Bearer token"}
          }
        ]
      }
    ]
  }
}
```

### Matcher Patterns

| Pattern | Example | Behavior |
|---------|---------|----------|
| Empty / `*` | `""` | Matches everything |
| Exact match | `"Bash"` | Matches exact tool name |
| Pipe-separated | `"Write\|Edit"` | Matches any in list |
| Regex | `"^git .*"` | Regex match |

### Common Hook Options

| Option | Type | Description |
|--------|------|-------------|
| `if` | string | Permission rule syntax filter (e.g. `"Bash(git *)"`) |
| `timeout` | int | Timeout in seconds |
| `once` | bool | Hook runs once then auto-removes |
| `statusMessage` | string | Custom spinner message |

### Command Hook Environment Variables

| Variable | Description |
|----------|-------------|
| `CLAUDE_PROJECT_DIR` | Current working directory |
| `CLAUDE_SESSION_ID` | Current session ID |
| `CLAUDE_PLUGIN_ROOT` | Plugin installation directory (if from plugin) |
| `CLAUDE_PLUGIN_DATA` | Plugin data directory |
| `CLAUDE_ENV_FILE` | Write bash exports here to apply env to subsequent commands |

Use `$ARGUMENTS` in the command string to inject the hook input JSON.

### Hook Registration Sources

1. **Global**: `settings.json` → `hooks` field
2. **Plugin hooks**: from each enabled plugin's `hooks.json` or `hooks/hooks.json`

### Hook Result Aggregation

Multiple hooks on the same event are aggregated with priority: `deny` > `ask` > `allow`.

### Source Reference

- Hook loader: `src/illusion/hooks/loader.py`
- Hook events: `src/illusion/hooks/events.py`
- Hook schemas: `src/illusion/hooks/schemas.py`
- Hook types: `src/illusion/hooks/types.py`
