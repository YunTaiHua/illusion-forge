# Messaging Channels

> [中文](../zh-CN/channels.md) | English

## Table of Contents

- [How It Works](#how-it-works)
- [Supported Channels](#supported-channels)
- [Quick Start (Feishu)](#quick-start-feishu)
- [Channel Configuration (channels.json)](#channel-configuration-channelsjson)
- [Feishu Slash Commands](#feishu-slash-commands)
- [Feishu Built-in Tools](#feishu-built-in-tools)
- [Permission Interaction](#permission-interaction)
- [Troubleshooting](#troubleshooting)
- [Quick Start (WeChat)](#quick-start-wechat)
- [Quick Start (QQ)](#quick-start-qq)
- [Channel Architecture](#channel-architecture)

---

IllusionForge supports messaging channels that let you interact with the AI assistant from messaging apps like Feishu (Lark) and WeChat. This enables **remote work continuation** — start a task on your desktop, then continue it from your phone.

## How It Works

```
illusion (main program)
 ├─ Reads channels.json → feishu.enabled / weixin.enabled / qq.enabled
 ├─ Silently spawns 'illusion-forge channel serve' as a background daemon
 │    └─ Feishu: WS long connection → agent → streaming card reply
 │    └─ WeChat: HTTP long-poll → agent → typing indicator + text reply
 │    └─ QQ: WS Gateway → agent → text reply
 └─ Web UI (browser) ← Main interactive interface

Your phone
 └─ Send message → daemon receives → agent processes → reply
```

## Supported Channels

| Channel | Protocol | Streaming | Group Chat | Status |
|---------|----------|-----------|------------|--------|
| Feishu / Lark | WS long connection | Interactive card (JSON 2.0) | ✅ | Production ready |
| WeChat (iLink Bot) | HTTP long-poll | Typing indicator + text | ❌ (DM only) | Production ready |
| QQ (QQ Open Platform Bot) | WS Gateway | Text | ✅ (C2C + Group) | Production ready |

## Quick Start (Feishu)

### 1. Create a Feishu App

1. Go to [Feishu Open Platform](https://open.feishu.cn/app) (Lark: [open.larksuite.com](https://open.larksuite.com/app))
2. Create a **Custom App** (自建应用)
3. Enable the **Bot** capability (机器人能力)
4. Under **Event Subscriptions** (事件订阅), select **Long Connection mode** (长连接模式)
5. Subscribe to the event: `im.message.receive_v1` (接收消息)
6. Record your **App ID** and **App Secret**

### 2. Configure the Channel

```bash
illusion-forge channel login
```

This launches an interactive setup wizard:

```
选择渠道 / Select a channel:
  1. 飞书 / Feishu (Lark)
输入序号: 1

--- 飞书渠道配置 ---
选择平台 / Select platform:
  1. 飞书 (open.feishu.cn)
  2. Lark (open.larksuite.com)
输入序号: 1

输入 App ID: cli_a1b2c3...
输入 App Secret: 明文输入

是否启用群组会话按用户隔离? (Y/n): Y
群组中是否要求 @机器人才响应? (Y/n): Y
是否允许其他机器人消息? (y/N): N
是否在回复中显示思考过程? (Y/n): Y

正在安装依赖 lark-oapi... ✓
配置已保存，飞书渠道已启用。
```

- The `lark-oapi` SDK is **automatically installed** on first setup (as an optional dependency)
- Credentials are stored in plaintext in `~/.illusion/channels.json` (per requirement, not masked)
- The channel is **auto-activated** on next `illusion-forge` launch

### 3. Start Using

```bash
# Option A: Let illusion-forge auto-activate the channel (silent background daemon)
illusion                    # Channel daemon starts automatically, Web UI runs normally

# Option B: Run the daemon in foreground (see logs, Ctrl+C to stop)
illusion-forge channel serve
```

Now send a message to your bot in Feishu — you'll get a streaming card reply with full Markdown rendering.

## Channel Configuration (channels.json)

Channel config is stored separately in `~/.illusion/channels.json` (not in `settings.json`):

```json
{
  "feishu": {
    "enabled": true,
    "app_id": "cli_xxx",
    "app_secret": "your-secret",
    "domain": "feishu",
    "require_mention": true,
    "allow_bots": false,
    "group_sessions_per_user": true,
    "show_reasoning": true,
    "group_policy": {
      "mode": "open",
      "allowlist": [],
      "blacklist": [],
      "admin_list": []
    }
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `false` | Whether the channel is active |
| `app_id` | — | Feishu App ID |
| `app_secret` | — | Feishu App Secret (plaintext) |
| `domain` | `"feishu"` | `"feishu"` (China) or `"lark"` (International) |
| `require_mention` | `true` | In groups, only respond when @mentioned |
| `allow_bots` | `false` | Whether to process messages from other bots |
| `group_sessions_per_user` | `true` | Isolate sessions per user in groups |
| `show_reasoning` | `true` | Whether to show thinking process in replies |
| `group_policy.mode` | `"open"` | `"open"` / `"disabled"` / `"allowlist"` / `"blacklist"` |
| `group_policy.allowlist` | `[]` | Allowed chat_ids (when mode=allowlist) |
| `group_policy.blacklist` | `[]` | Blocked chat_ids (when mode=blacklist) |
| `group_policy.admin_list` | `[]` | user_ids that always bypass policy |
| `working_directory` | — | Channel agent run directory (**required to enable**; channel agents run anchored in this directory; auto-registered as a Web workspace) |

> **Run directory notes**: enabling a channel (`enabled: true`) requires `working_directory`.
> - CLI: `illusion-forge channel enable <name> --working-directory <dir>` / `illusion-forge channel login --working-directory <dir>` (interactive prompt when omitted); the directory is validated and registered into `~/.illusion/workspaces.json`
> - Web: Settings → Channels → expand the channel card to pick a run directory (dropdown matches global workspaces, shows the selected directory directly); enabling without a directory is blocked with a hint
> - Channel agents anchor per-message to the configured directory

## Feishu Slash Commands

You can manage sessions directly from Feishu chats:

| Command | Description |
|---------|-------------|
| `/help` | List available commands |
| `/clear` | Clear current Feishu session history |
| `/new` | Start a new Feishu session |
| `/sessions` | List local sessions (unfinished work) |
| `/resume [id\|index]` | Resume a local session into Feishu |
| `/detach` | Save current Feishu session as a local session |
| `/model [show\|set NAME]` | View or switch the session model |

**Remote work continuation workflow:**
1. Start a coding task in your desktop, exit midway
2. From Feishu, send `/sessions` — see your unfinished local sessions
3. Send `/resume 1` — pull the session into Feishu, continue working
4. Send `/detach` — save it back to local; pick it up again in the Web UI session list, or continue headlessly with `illusion-forge -r <id> -p "..."`

## Feishu Built-in Tools

When the Feishu channel is enabled, the following generic channel tools are available to the agent:

| Tool | Description | Enable Condition |
|------|-------------|------------------|
| `send_media` | Send media files (images/audio/video/files) to the current channel | Any channel enabled |
| `receive_media` | Receive media files sent by users | Any channel enabled and message has attachments |
| `list_channel_sessions` | List sessions across all enabled channels | At least 2 channels enabled |
| `send_to_channel` | Send a message to a session in a specified channel | At least 2 channels enabled |

## Permission Interaction

All channel sessions run in **auto mode** by default — tool calls are automatically approved without user confirmation. This is different from the Web UI where the default permission mode requires confirmation for modification tools.

The auto mode applies to all tools (bash, file write, edit, etc.) in channel sessions. No manual approval is needed.

> **Note**: `ask_user_question` questions and plan approvals still require user input — these are interactive prompts, not permission checks.

### ask_user_question Multi-Question Handling

When the LLM calls the `ask_user_question` tool, channels handle it as follows:

- **Single question** (`len(questions) == 1`): Sent as one message, user replies with one text. When `multiSelect=true`, a "(multi-select, separate with commas)" hint is appended; user replies like `OptionA,OptionB`, which is split into a list.
- **Multiple questions** (`len(questions) > 1`): **Asked one by one** — each question is sent as a separate message (with sequence number `[1/3]`, `[2/3]`, etc.), and the next is sent only after receiving a reply. Finally, answers are merged into a dict (keyed by header).
- **No structured data** (`questions=None`): Question text is sent directly, waiting for a reply string.

Example: 3-question interaction flow
```
Channel → User: ❓ [1/3] Model: Which model?  • A — Option A  • B — Option B
User → Channel: A
Channel → User: ❓ [2/3] Effort: Reasoning level?  • low  • high
User → Channel: high
Channel → User: ❓ [3/3] Theme: Theme?  • dark  • light
User → Channel: dark
(Tool returns {Model: A, Effort: high, Theme: dark} to LLM)
```

## Plan Mode Approval

When the agent calls `exit_plan_mode` in a channel session, the plan content is sent as a message to the channel:

1. The agent calls `enter_plan_mode` to enter plan mode, explores code, and writes a plan file
2. The agent calls `exit_plan_mode` to submit the plan for approval
3. The channel automatically sends the plan content to the current session
4. The user replies "approve" or types revision feedback (treated as reject + feedback)
5. After approval, the agent starts executing; after rejection, the agent revises the plan based on the feedback

**Keywords**: Reply "approve"/"yes"/"y" (case-insensitive) to approve; any other input is treated as rejection with the input as feedback.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No response in Feishu | Check `~/.illusion/channels/serve.log` for errors |
| Daemon didn't auto-start | Run `illusion-forge channel status` to check; manually run `illusion-forge channel serve` to see logs |
| `processor not found` in logs | Harmless — this is the read-receipt event, already handled with a no-op processor |
| Card not rendering tables | Ensure your Feishu client is v7.20+ (JSON 2.0 cards require it) |
| WS connection keeps reconnecting | Verify App ID/Secret are correct; check event subscription is set to Long Connection mode |
| Edit limit (230072) | Not applicable — cards use `message.patch` which has no edit count limit |

## Quick Start (WeChat)

WeChat uses the **iLink Bot API** (Tencent's official Bot API via HTTPS long-poll). It's not a reverse-engineering hook — no WeChat client needs to be running.

### 1. Configure the Channel

```bash
illusion-forge channel login
# Select: 2. WeChat
```

This will:
1. Auto-install `aiohttp`, `cryptography`, `qrcode` (first time only)
2. Open your browser with a QR code page
3. Scan with WeChat to authorize the bot identity
4. Save credentials to `~/.illusion/channels.json`

### 2. Start Using

```bash
illusion                    # Auto-activates WeChat daemon in background
# or
illusion-forge channel serve      # Foreground mode with logs
```

Send a message to your bot in WeChat — you'll see "typing..." indicator, then the full reply.

### 3. Key Limitations

- **DM only** — bot identity cannot join normal WeChat groups
- **No message editing** — replies are sent as complete text (typing indicator shows during processing)
- **2000 char limit** — longer replies auto-split into multiple messages with 1.5s delay
- **Session expires** — if you see `errcode=-14`, re-run `illusion-forge channel login` to re-scan

## Quick Start (QQ)

QQ uses the **Official QQ Bot API v2** (WebSocket Gateway + REST API). You need to register a bot application on the QQ Open Platform.

### 1. Register a QQ Bot

1. Go to [QQ Open Platform](https://q.qq.com)
2. Register a bot application, obtain **App ID** and **Client Secret**
3. Enable **C2C Private Chat** and **Group @Message** capabilities in bot settings

### 2. Configure the Channel

```bash
illusion-forge channel login
# Select: 3. QQ
```

This will:
1. Auto-install `aiohttp` (first time only)
2. Guide you to enter App ID and Client Secret
3. Configure group policy options
4. Choose whether to show thinking process (`show_reasoning`, default Y)
5. Save credentials to `~/.illusion/channels.json`

### 3. Start Using

```bash
illusion                    # Auto-activates QQ daemon in background
# or
illusion-forge channel serve      # Foreground mode with logs
```

Send a message to your bot in QQ — private chat replies directly, group chat requires @mention.

### 4. Key Limitations

- **Group chat requires @mention** — group messages need to @mention the bot by default (configurable)
- **No message editing** — replies are sent as complete text
- **4000 char limit** — longer replies auto-split into multiple messages with 1.5s delay
- **File sending** — supports 3-step chunked upload
- **Markdown dynamic hint** — when `markdown_support` is `true` in `channels.json`, the platform prompt tells the LLM that markdown is available (msg_type=2); when `false` (default), the prompt forces plain text (msg_type=0) and `send_text` auto-degrades to plain text on failure. Keep the default `false` for normal developer accounts without template permissions
- **Attachment download security** — when downloading QQ inbound attachments, the bot token is only attached for `.qq.com` / `.qq.com.cn` hosts, preventing access_token leakage via malicious URLs

## Channel Architecture

```
src/illusion/channels/
├── __init__.py          # ChannelRunner (message→agent glue) + maybe_spawn_channel_daemon + kill_channel_daemon
├── base.py              # Channel ABC + InboundMessage + Attachment + typing methods
├── base_commands.py     # BaseCommandHandler (shared slash commands)
├── config.py            # ChannelsConfig / FeishuChannelConfig / WeixinChannelConfig
├── delivery.py          # cron job result delivery to channels (parse_deliver_to + deliver_to_channel)
├── serve.py             # 'illusion-forge channel serve' entry point (multi-channel)
├── pid.py               # PID file management (avoid duplicate daemons)
├── feishu/
│   ├── adapter.py       # FeishuChannel: WS connection, event dispatch, admission control
│   ├── ws_client.py     # lark-oapi WS client wrapper
│   ├── messaging.py     # Card send/patch, message rendering, resolve_receive_id
│   ├── stream_editor.py # Streaming card editor (throttled patch updates)
│   ├── session_map.py   # Feishu session store (chat_id → session)
│   └── commands.py      # FeishuCommandHandler (extends BaseCommandHandler)
├── weixin/
│   ├── __init__.py      # WEIXIN_DEPENDENCIES / ensure_weixin_dependencies
│   ├── adapter.py       # WeixinChannel: long-poll, admission, context_token, AES key cache, typing
│   ├── ilink_api.py     # iLink Bot API client (QR login / send / poll / typing / CDN allowlist)
│   ├── session_map.py   # WeixinSessionStore (user_id → session)
│   └── commands.py      # WeixinCommandHandler (extends BaseCommandHandler)
├── qq/
│   ├── __init__.py      # QQ_DEPENDENCIES / ensure_qq_dependencies
│   ├── adapter.py       # QQChannel: WS connection, admission, message normalization, attachment host validation
│   ├── ws_client.py     # QQ Bot WS gateway client (heartbeat/reconnect/events)
│   ├── api.py           # QQ Bot REST API client (token/send/upload/_parse_qq_response)
│   ├── session_map.py   # QQSessionStore (chat_id → session)
│   └── commands.py      # QQCommandHandler (extends BaseCommandHandler)
└── tools/
    ├── cross_channel.py # ListChannelSessionsTool / SendToChannelTool (loaded when ≥2 channels enabled)
    └── media.py         # SendMediaTool / ReceiveMediaTool (activated by channel config)
```

## Cron Job Result Delivery

Cron jobs can deliver execution results to Feishu/WeChat/QQ channel sessions. Configure via the `deliver_to` field in `cron_tool.py`:

- **Empty** — local execution only (console output)
- **`channel:chat_id`** — fully qualified format, e.g. `feishu:oc_xxx` (group), `feishu:ou_xxx` (private), `weixin:wxid_xxx`, `qq:openid`
- **`channel` (name only)** — requires the `chat_id` field; otherwise treated as "unspecified"

Session filename prefix rules (for extracting the real ID from `~/.illusion/channels/<channel>/sessions/`):

| Channel | Filename format | Real ID |
|---------|-----------------|---------|
| Feishu private | `u_ou_xxx.json` | `ou_xxx` (strip `u_` prefix) |
| Feishu group | `g_oc_xxx_ou_xxx.json` | `oc_xxx` (use the `oc_` part) |
| WeChat | `u_<wxid>.json` | `<wxid>` (strip `u_` prefix) |
| QQ | `<openid>.json` | `<openid>` (filename is the ID) |

Delivery failures do not affect task status; only a warning is logged. Failed jobs (non-success status) include stderr in the delivered text so users can see the error.

## Concurrent Message Handling

When a user sends multiple messages in quick succession, `ChannelRunner` serializes agent turns per `chat_id` using an `asyncio.Lock` to prevent session history corruption:

- M1 acquires the lock and starts the agent; M2/M3 enter the queue and wait
- After M1 completes (or exits pending_replies wait), M2 acquires the lock
- Permission/ask reply messages are **not locked** — they immediately `set_result` the waiting future, avoiding 300s timeouts
- Different `chat_id`s run fully in parallel without blocking each other

This ensures conversation history is written in order for the same session, preventing the race condition where "M1/A1 and M3/A3 are lost, only M2/A2 remains."

## Cross-Channel File Transfer

When multiple channels are enabled, the LLM can perceive all enabled channels and transfer files across channels.

### How It Works

1. **Channel-aware prompts**: System prompt includes current channel identity + overview of other enabled channels (with active sessions)
2. **Cross-channel tool**: `send_to_channel` for cross-channel file/text transfer, `send_media` for within-current-channel files
3. **Active session list**: Up to 5 recent sessions per channel (sorted by last active time) to help LLM decide delivery target

### Use Cases

- **PC (Web UI) → channel**: User says "send this file to Zhang San on Feishu"
- **Channel → channel**: User on QQ says "send this file to WeChat"
- **Within channel (default)**: User on QQ says "send this file" → uses `send_media` to current QQ session

### Limitations

- `send_to_channel` supports both files and text messages (markdown supported on feishu/qq per config, auto-split into chunks if exceeds channel limit)
- QQ and WeChat file upload APIs are complex; current version uses text prompts as fallback. Feishu is fully supported
- Active session list comes from session storage directory; users never interacted with won't appear
