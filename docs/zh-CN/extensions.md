# 扩展系统：MCP、规则、插件、技能与钩子

## 目录

- [概述](#概述)
- [MCP 服务器配置](#mcp-服务器配置)
- [规则配置](#规则配置)
- [插件系统](#插件系统)
- [技能系统](#技能系统)
- [钩子系统](#钩子系统)

---

## 概述

IllusionForge 提供分层扩展系统。扩展可在三个层级配置（优先级从高到低）：

1. **插件级** — 随插件捆绑，自动加载
2. **项目级** — 在 `{cwd}/.illusion/` 目录中
3. **全局级** — 在 `~/.illusion/` 或 `settings.json` 中

---

## MCP 服务器配置

### 配置类型

| 类型 | 字段 | 说明 |
|------|------|------|
| `stdio` | command, args, env, cwd, log_file, enabled | 标准输入输出通信 |
| `http` | url, headers, enabled | HTTP 协议（Streamable HTTP，兼容 `streamable-http`/`streamableHttp`/`streamable_http`/`streamablehttp` 别名） |
| `sse` | url, headers, enabled | Server-Sent Events 协议 |

所有类型支持 `enabled` 字段（默认 `true`）。设为 `false` 可禁用而不删除配置。

`type` 字段为可选。省略时默认按 `stdio` 类型处理：

```json
{
  "command": "python",
  "args": ["server.py"]
}
```

仅在使用 `http`/`sse` 等非 stdio 类型时才需显式填写 `type`。

### 三个配置来源（优先级从高到低）

#### 1. 插件 MCP

来自 `{plugin_dir}/mcp.json` 或 `{plugin_dir}/.mcp.json`。注册格式为 `{插件名}:{服务器名}`。

#### 2. 项目级 MCP（`{cwd}/.illusion/mcp/*.json`）

扫描目录下所有 `*.json` 文件。支持两种格式：

**单服务器**（文件名 = 服务器名）：
```json
{
  "command": "python",
  "args": ["server.py"],
  "enabled": true
}
```

省略 `type` 字段时默认按 `stdio` 处理。

**多服务器**（使用 `mcpServers` 键）：
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

上例中 `filesystem` 省略了 `type`，默认按 `stdio` 处理；`remote-api` 显式声明为 `http` 类型。

`mcpServers` 和 `mcp_servers` 两种键名均支持。

#### 3. 全局 MCP（`settings.json`）

在 `~/.illusion/settings.json` 的 `mcp_servers` 字段中配置：

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

省略 `type` 字段时默认按 `stdio` 处理。

CLI 管理：
```bash
illusion-forge mcp list
illusion-forge mcp add <name> <config>
illusion-forge mcp remove <name>
```

### 源码参考

- 配置加载：`src/illusion/mcp/config.py`
- 类型定义：`src/illusion/mcp/types.py`

---

## 规则配置

规则是 `.md` 文件，为 AI 提供项目特定指令。

### 发现位置

规则从以下位置发现：
1. `{cwd}/.claude/rules/*.md` — 按文件名排序
2. AI 指令文件（`CLAUDE.md`、`ILLUSION.md`、`AGENTS.md`）在项目根目录和 `.claude/`/`.illusion/` 目录中

### 规则文件格式

每个 `.md` 文件是独立规则，文件名决定排序顺序：

```
.claude/rules/
├── 01-python-style.md
├── 02-testing.md
└── 03-git-workflow.md
```

### 初始化

`/init` 命令在 `.illusion/rules/` 生成默认规则：
- `python-style.md` — Python 代码风格规则
- `testing.md` — 测试框架和规范
- `project-structure.md` — 项目结构指南

### 源码参考

- 发现逻辑：`src/illusion/prompts/claudemd.py` — `discover_claude_md_files()`
- 规则生成：`src/illusion/commands/init/generation/rules.py`

---

## 插件系统

### 插件目录

1. **用户级**：`~/.illusion/plugins/`
2. **项目级**：`{cwd}/.illusion/plugins/`

### 插件发现

每个子目录必须包含 `plugin.json` 或 `.claude-plugin/plugin.json`。

### 插件清单 (plugin.json)

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "我的自定义插件",
  "enabled_by_default": true,
  "skills_dir": "skills",
  "hooks_file": "hooks.json",
  "mcp_file": "mcp.json"
}
```

完整清单字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | string | 必填 | 插件名称 |
| `version` | string | "0.0.0" | 插件版本 |
| `description` | string | "" | 插件描述 |
| `enabled_by_default` | bool | true | 首次发现时启用 |
| `skills_dir` | string | "skills" | 技能子目录名 |
| `hooks_file` | string | "hooks.json" | 钩子配置文件名 |
| `mcp_file` | string | "mcp.json" | MCP 配置文件名 |
| `commands` | string\|list\|dict | null | 命令定义 |
| `agents` | string\|list | null | 代理定义 |
| `hooks` | string\|dict\|list | null | 钩子定义 |
| `settings` | dict | null | 插件默认设置 |

### 插件目录结构

```
my-plugin/
├── plugin.json              # 或 .claude-plugin/plugin.json
├── skills/
│   ├── my-skill/
│   │   └── SKILL.md
│   └── another-skill.md
├── commands/                # 斜杠命令（.md 文件）
├── agents/                  # 代理定义（.md 文件）
├── hooks/
│   └── hooks.json           # 钩子定义
├── mcp.json                 # MCP 服务器配置
└── settings.json            # 插件默认设置
```

### 插件启用/禁用

由 `settings.enabled_plugins` 控制：

```json
{
  "enabled_plugins": {
    "my-plugin": true,
    "disabled-plugin": false
  }
}
```

未配置时使用 `manifest.enabled_by_default`。

### 插件技能命名

所有插件技能注册格式为 `{插件名}:{技能名}`，避免冲突。

### 插件钩子变量

钩子命令支持 `${CLAUDE_PLUGIN_ROOT}` 和 `${CLAUDE_PLUGIN_DATA}` 变量替换。

### CLI 管理

```bash
illusion-forge plugin list
illusion-forge plugin install <source>
illusion-forge plugin uninstall <name>
illusion-forge plugin enable <name>
illusion-forge plugin disable <name>
```

### 源码参考

- 插件加载器：`src/illusion/plugins/loader.py`
- 清单 schema：`src/illusion/plugins/schemas.py`
- 插件类型：`src/illusion/plugins/types.py`

---

## 技能系统

### 技能来源（优先级顺序）

1. **内置技能**：`src/illusion/skills/bundled/content/*.md`
2. **用户技能**：`~/.illusion/skills/*.md`（或 `.yaml`/`.yml`）
3. **项目技能**：`{cwd}/.illusion/skills/` — 支持两种格式：
   - 目录格式：`{skills_dir}/{skill_name}/SKILL.md`（优先）
   - 文件格式：`{skills_dir}/{skill_name}.md`
4. **插件技能**：从所有已启用插件的技能目录加载

后注册的同名技能覆盖先注册的。

### SKILL.md 格式

支持 YAML frontmatter：

```markdown
---
description: 技能描述
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

技能内容（markdown）...
```

#### Frontmatter 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 技能名（省略时从文件名派生） |
| `description` | string | 技能描述（显示在技能列表中） |
| `allowed-tools` | string\|list | 逗号分隔或列表的允许工具名 |
| `model` | string | 该技能的模型覆盖 |
| `context` | string | `inline`（展开到对话）或 `fork`（子代理） |
| `effort` | string | 推理强度覆盖 |
| `hooks` | object | 技能调用时注册的钩子 |
| `agent` | string | 使用的代理类型 |
| `disable_model_invocation` | bool | 禁用模型调用 |
| `skill_root` | string | 技能资源根目录 |

### 内置技能

| 技能 | 描述 |
|------|------|
| `debug` | 系统化调试工作流 |
| `verify` | 代码变更验证 |
| `loop` | 循环任务执行 |
| `batch` | 批量操作 |
| `remember` | 记忆管理 |
| `simplify` | 代码质量审查 |
| `skillify` | 将模式转化为技能 |
| `stuck` | 突破阻塞 |
| `update-config` | 配置 settings.json |

### 源码参考

- 技能加载器：`src/illusion/skills/loader.py`
- 技能类型：`src/illusion/skills/types.py`
- 技能注册表：`src/illusion/skills/registry.py`

---

## 钩子系统

### 支持的事件（27 个）

| 事件 | 匹配字段 | 说明 |
|------|----------|------|
| `PreToolUse` | tool_name | 工具执行前 |
| `PostToolUse` | tool_name | 工具执行后 |
| `PostToolUseFailure` | tool_name | 工具执行失败后 |
| `PermissionDenied` | tool_name | 自动模式分类器拒绝后 |
| `Notification` | notification_type | 发送通知时 |
| `UserPromptSubmit` | — | 用户提交提示词时 |
| `SessionStart` | source | 新会话开始 |
| `SessionEnd` | reason | 会话结束 |
| `Stop` | — | Claude 结束响应前 |
| `StopFailure` | error | 因 API 错误结束回合 |
| `SubagentStart` | agent_type | 子代理启动 |
| `SubagentStop` | agent_type | 子代理结束 |
| `PreCompact` | trigger | 压缩前 |
| `PostCompact` | trigger | 压缩后 |
| `PermissionRequest` | tool_name | 权限对话框显示时 |
| `Setup` | trigger | 仓库设置 |
| `ConfigChange` | source | 配置文件变更 |
| `InstructionsLoaded` | load_reason | 指令文件加载时 |
| `WorktreeCreate` | — | 创建工作树 |
| `WorktreeRemove` | — | 移除工作树 |
| `CwdChanged` | — | 工作目录变更 |
| `FileChanged` | — | 监视文件变更 |
| `TaskCreated` | — | 任务创建时 |
| `TaskCompleted` | — | 任务完成时 |
| `TeammateIdle` | — | 队友即将空闲 |
| `Elicitation` | mcp_server_name | MCP 引出请求 |
| `ElicitationResult` | mcp_server_name | 用户响应引出后 |

### 钩子类型

| 类型 | 必填 | 可选 | 说明 |
|------|------|------|------|
| `command` | `command` | `if`, `shell`, `timeout`, `statusMessage`, `once`, `async` | 执行 shell 命令 |
| `prompt` | `prompt` | `if`, `model`, `timeout`, `statusMessage`, `once` | 使用 LLM 验证 |
| `http` | `url` | `if`, `timeout`, `headers`, `allowedEnvVars`, `statusMessage`, `once` | 发送 HTTP POST |
| `agent` | `prompt` | `if`, `model`, `timeout`, `statusMessage`, `once` | 使用 Agent 验证 |

### 钩子配置格式

基于 matcher 的结构：

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

### 匹配器模式

| 模式 | 示例 | 行为 |
|------|------|------|
| 空 / `*` | `""` | 匹配所有 |
| 精确匹配 | `"Bash"` | 匹配精确工具名 |
| 管道分隔 | `"Write\|Edit"` | 匹配列表中的任意一个 |
| 正则表达式 | `"^git .*"` | 正则匹配工具名 |

### 通用钩子选项

| 选项 | 类型 | 说明 |
|------|------|------|
| `if` | string | 权限规则语法过滤（如 `"Bash(git *)"`) |
| `timeout` | int | 超时秒数 |
| `once` | bool | 为 true 时钩子执行一次后自动移除 |
| `statusMessage` | string | 钩子运行时的自定义加载消息 |

### 命令钩子环境变量

| 变量 | 说明 |
|------|------|
| `CLAUDE_PROJECT_DIR` | 当前工作目录 |
| `CLAUDE_SESSION_ID` | 当前会话 ID |
| `CLAUDE_PLUGIN_ROOT` | 插件安装目录（来自插件时） |
| `CLAUDE_PLUGIN_DATA` | 插件数据目录 |
| `CLAUDE_ENV_FILE` | 写入 bash exports 以应用到后续命令 |

在命令字符串中使用 `$ARGUMENTS` 注入钩子输入 JSON。

### 钩子注册来源

1. **全局**：`settings.json` → `hooks` 字段
2. **插件钩子**：从每个已启用插件的 `hooks.json` 或 `hooks/hooks.json`

### 钩子结果聚合

同一事件上的多个钩子按优先级聚合：`deny` > `ask` > `allow`。

### 源码参考

- 钩子加载器：`src/illusion/hooks/loader.py`
- 钩子事件：`src/illusion/hooks/events.py`
- 钩子 schema：`src/illusion/hooks/schemas.py`
- 钩子类型：`src/illusion/hooks/types.py`

---

## 插件配置

### 全局启用/禁用

在 `~/.illusion/settings.json` 的 `enabled_plugins` 字段中控制：

```json
{
  "enabled_plugins": {
    "plugin-name": true,   // 启用
    "plugin-name": false   // 禁用
  }
}
```

### 项目级禁用

在 `<project>/.illusion/permissions.json` 的 `denied_plugins` 字段中控制：

```json
{
  "denied_plugins": ["plugin-name"]  // 禁用特定插件
  "denied_plugins": ["*"]            // 禁用所有插件
}
```

### 优先级

项目级 `denied_plugins` > 全局 `enabled_plugins` > 默认值

### 源码参考

- 插件加载器：`src/illusion/plugins/loader.py`

---

## MCP 服务器配置

### 全局启用/禁用

在 MCP 服务器配置中添加 `enabled` 字段：

```json
{
  "mcp_servers": {
    "server-name": {
      "command": "python",
      "args": ["server.py"],
      "enabled": false  // 禁用此服务器
    }
  }
}
```

省略 `type` 字段时默认按 `stdio` 处理。

### 项目级禁用

在 `<project>/.illusion/permissions.json` 的 `denied_mcp_servers` 字段中控制：

```json
{
  "denied_mcp_servers": ["server-name"]  // 禁用特定服务器
  "denied_mcp_servers": ["*"]            // 禁用所有服务器
}
```

### 优先级

项目级 `denied_mcp_servers` > 全局 `enabled` 字段 > 默认值

### 源码参考

- MCP 配置加载器：`src/illusion/mcp/config.py`

---

## 记忆系统配置

### 全局启用/禁用

在 `~/.illusion/settings.json` 的 `memory.enabled` 字段中控制：

```json
{
  "memory": {
    "enabled": false  // 禁用记忆功能
  }
}
```

### 项目级禁用

在 `<project>/.illusion/permissions.json` 的 `denied_memory` 字段中控制：

```json
{
  "denied_memory": true  // 禁用记忆功能
}
```

### 优先级

项目级 `denied_memory` > 全局 `memory.enabled` > 默认值

### 源码参考

- 记忆管理器：`src/illusion/memory/manager.py`

---

## Skills 配置

### 加载来源

Skills 可以从以下位置加载：
- 内置 skills（`src/illusion/skills/bundled/`）
- 用户 skills（`~/.illusion/skills/`）
- 项目级 skills（`<project>/.illusion/skills/`）
- 插件 skills（插件的 `skills/` 目录）

### 项目级禁用

在 `<project>/.illusion/permissions.json` 的 `denied_skills` 字段中控制：

```json
{
  "denied_skills": ["skill-name"]  // 禁用特定 skill
  "denied_skills": ["*"]           // 禁用所有 skills
}
```

### 源码参考

- Skills 加载器：`src/illusion/skills/loader.py`

---

## Hooks 配置

### 加载来源

Hooks 可以从以下位置加载：
- 全局 `settings.json` 的 `hooks` 字段
- 插件的 `hooks.json` 文件

### 项目级禁用

在 `<project>/.illusion/permissions.json` 的 `denied_hooks` 字段中控制：

```json
{
  "denied_hooks": ["PreToolUse"]  // 禁用特定事件的 hooks
  "denied_hooks": ["*"]           // 禁用所有 hooks
}
```

### 源码参考

- Hooks 加载器：`src/illusion/hooks/loader.py`

---

## Commands 配置

### 命令类型

IllusionForge 的斜杠命令分为两类：

1. **内置命令**：如 `/help`、`/model`、`/skills` 等，硬编码注册，不可禁用
2. **插件命令**：通过插件的 `commands/` 或 `skills/` 目录提供，遵循插件的启用/禁用规则

### 插件命令的启用/禁用

- 通过 `enabled_plugins` 控制插件整体启用/禁用
- 通过 `denied_plugins` 项目级禁用插件
- 插件禁用后，其提供的所有命令都会被禁用

### 源码参考

- 命令注册表：`src/illusion/commands/registry.py`

---

## Rules 配置

### 加载来源

Rules 从以下位置加载：
- `.claude/rules/*.md`
- `.illusion/rules/*.md`

### 项目级禁用

在 `<project>/.illusion/permissions.json` 的 `denied_rules` 字段中控制：

```json
{
  "denied_rules": ["rule-name"]  // 禁用特定 rule
  "denied_rules": ["*"]          // 禁用所有 rules
}
```

### 源码参考

- Rules 发现逻辑：`src/illusion/prompts/claudemd.py`
