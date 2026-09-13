# 项目架构

## 🏗️ 项目架构

```
illusion-forge/
├── src/illusion/           # 主要源代码
│   ├── api/                # API 客户端 (Anthropic, OpenAI 等)
│   ├── auth/               # 认证管理
│   ├── cad/                # CAD 画布工作台（含 STA 宿主、无头几何、OCP 导出）
│   ├── cli/                # CLI 入口与子命令（main.py, auth.py, web.py, channel.py, cron.py, mcp.py, plugin.py, update.py）
│   ├── commands/           # 斜杠命令系统
│   ├── config/             # 配置系统
│   ├── coordinator/        # 多智能体协调器
│   ├── engine/             # 核心对话引擎
│   ├── goal/               # Goal 子系统
│   ├── hooks/              # 钩子系统
│   ├── mcp/                # MCP 客户端
│   ├── memory/             # 记忆系统
│   ├── permissions/        # 权限系统
│   ├── plugins/            # 插件系统
│   ├── prompts/            # 提示词系统
│   ├── sandbox/            # 沙箱系统
│   ├── services/           # 服务层（cron、title 等）
│   ├── skills/             # 技能系统
│   ├── swarm/              # 子代理调度
│   ├── tasks/              # 任务管理
│   ├── tools/              # 工具集（基础 + 渠道工具 + CAD 工具）
│   ├── ui/                 # 用户界面
│   │   ├── protocol.py     # Web 前后端 WebSocket 协议
│   │   ├── runtime.py      # 会话运行时装配
│   │   ├── file_mentions.py # 文件提及系统
│   │   ├── headless.py     # 无头模式（打印模式）
│   │   ├── headless_prompts.py # 无头模式回调（权限/提问/计划审批格式化）
│   │   └── web/            # Web 后端 (FastAPI + WebSocket)
│   │       ├── server.py       # FastAPI 应用入口
│   │       ├── ws_host.py      # WebBackendHost（WebSocket 会话宿主）
│   │       ├── ws_web_api.py   # WebSocket API 路由
│   │       ├── session_runtime.py # 会话运行时
│   │       ├── auth.py         # Web 访问认证
│   │       ├── security.py     # 浏览器信任栅栏
│   │       ├── env_routes.py   # 环境/配置 API
│   │       ├── cad_routes.py   # CAD 产物文件服务
│   │       └── channels_routes.py # 渠道 API
│   ├── utils/              # 工具函数
│   └── __main__.py         # 入口：python -m illusion_forge
├── frontend/
│   └── web/                # React Web 前端 (Vite + Tailwind)
├── desktop/                # Electron 桌面壳（仅 Windows）
├── tests/                  # 测试套件
└── pyproject.toml          # 项目配置
```

---

## 🔧 核心模块

### API 客户端层

支持多种 AI 提供商：

| 提供商 | API 格式 | 认证方式 |
|--------|----------|----------|
| Anthropic Claude | anthropic | API Key |
| OpenAI / 兼容接口 | openai | API Key |
| GitHub Copilot | copilot | OAuth 设备码 |
| OpenAI Codex | codex | OAuth 设备码 |
| 自定义格式 | anthropic / openai | API Key |

### 工具系统

提供基础工具，涵盖：

- **文件操作**: `file_read`, `file_write`, `file_edit`
- **命令执行**: `bash`, `powershell`
- **搜索**: `glob`, `grep`, `web_fetch`, `web_search`
- **任务管理**: `task_output`, `task_stop`
- **Agent 协作**: `agent`, `send_message`, `team_create`, `team_delete`
- **模式切换**: `enter_plan_mode`, `exit_plan_mode`
  - `exit_plan_mode` 会触发计划审批：Web 弹出审批卡片；print 模式跨轮次审批（退出码 2）；渠道端发送计划内容并等待回复
- **会话控制**: `enter_worktree`, `exit_worktree`, `todo_write`, `sleep`
- **配置与调试**: `config`, `lsp`, `mcp_auth`, `skill`
- **MCP 资源**: `list_mcp_resources`, `read_mcp_resource`
- **交互**: `ask_user_question`
- **定时任务**: `cron`（统一工具，支持 status/list/add/update/remove/run 操作）

### 定时任务与投递链路

定时任务子系统由三个模块协作：

- `services/cron.py` — 任务数据模型（CronJob）与持久化（`cron.json`）
- `services/cron_scheduler.py` — 调度器进程，子进程执行提示词，按 `deliver_to` 字段投递结果到渠道
- `channels/delivery.py` — 渠道投递模块，`parse_deliver_to` 解析目标，`deliver_to_channel` 派发到飞书/微信/QQ 的 `_deliver_*` 函数

投递目标支持 `channel:chat_id` 完全限定格式或仅渠道名（配合 `chat_id` 字段）。任务失败时附 stderr 让用户可见错误。详见 [渠道文档](channels.md#cron-任务结果投递)。

### 权限系统

四种权限模式：

| 模式 | 说明 |
|------|------|
| `default` | 修改类工具需要用户确认 |
| `plan` | 阻止所有修改类工具 |
| `full_auto` | 无沙箱时等价 `yolo`；有沙箱时受沙箱限制并拦高危 |
| `yolo` | 绕过沙箱完全运行，不施加任何沙箱限制 |

### 多智能体协调器

内置专业子代理：

| Agent | 用途 |
|-------|------|
| `general-purpose` | 通用研究和多步任务 |
| `explore` | 文件搜索和代码探索专家 |
| `verification` | 对抗性验证专家 |

---

## 🎨 前端技术栈

### Web UI

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18.x | UI 框架 |
| Vite | 6.x | 构建工具和开发服务器 |
| Tailwind CSS | 3.x | 实用优先的 CSS 框架 |
| TypeScript | 5.x | 类型安全 |
| FastAPI | - | 后端 API 框架 |
| WebSocket | - | 实时双向通信 |

### Web 多工作区（目录空间）

Web 端支持在多个目录空间并发运行会话，每个目录独立工作区：

- **后端**：`WebBackendHost`（`ws_host.py`）为每个工作区持有独立 `RuntimeBundle`（api_client / tool_registry / mcp / hooks 按目录初始化，项目级 `.illusion/` 配置随目录生效）。默认工作区急建 bundle（启动流程不变），其余工作区**懒构建**（首次进入该目录会话时）并**空闲驱逐**（60 秒宽限期）。工作区注册表持久化于 `~/.illusion/workspaces.json`
- **会话**：按目录分区存储（`~/.illusion/data/sessions/{目录}-{sha}/`），会话列表按目录分组；新建会话可指定目录（欢迎界面目录按钮）；恢复会话按所属目录路由
- **cron**：任务自带 `cwd`（创建/更新时必选已注册目录），web 委托按会话所属目录匹配；`/api/cron/sessions?cwd=` 按目录过滤
- **渠道**：渠道配置含 `working_directory`（启用必填），渠道 agent 固定在该目录运行；`channel enable/login --working-directory <dir>` 指定并自动注册工作区
- **无头/打印模式**：`build_runtime(cwd=)` 缺省取进程目录，行为不变

---

## 📦 主要依赖

| 依赖 | 用途 |
|------|------|
| anthropic | Anthropic SDK |
| openai | OpenAI SDK |
| rich | 富文本输出 |
| prompt-toolkit | 高级输入处理 |
| typer | CLI 框架 |
| pydantic | 数据验证 |
| httpx | HTTP 客户端 |
| mcp | MCP 协议 |
| fastapi | Web 后端 API 框架 |
| uvicorn | Web 后端 ASGI 服务器 |
