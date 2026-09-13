<div align="center">

# IllusionForge

![Python](https://img.shields.io/badge/python-%3E%3D3.10-green) ![Platform](https://img.shields.io/badge/platform-Windows-0078D6) ![License](https://img.shields.io/badge/license-MIT-lightgrey) [![GitHub](https://img.shields.io/badge/github-YunTaiHua%2Fillusion--forge-black)](https://github.com/YunTaiHua/illusion-forge) [![Origin](https://img.shields.io/badge/evolved%20from-illusion--agent-8A2BE2)](https://github.com/YunTaiHua/illusion-agent)

*从对话到实机：把 AI 智能体锻造成 Windows 上的工程工作台。*

中文 | [English](README.md)

</div>

---

## 📖 项目简介

IllusionForge 是一款开源的 AI 智能体平台，由 [illusion-agent](https://github.com/YunTaiHua/illusion-agent) 演化而来。
它保留了 illusion-agent 的全部智能体内核 —— 多模型网关、工具集、子代理、上下文压缩、
MCP / 插件 / 钩子 / 技能扩展、Cron 调度与飞书 / 微信 / QQ 渠道 —— 并把产品重心收敛到
**Web UI + Windows 桌面版 + CAD 画布工作台**：在共享画布上与 AI 讨论方案、无头生成 3D 预览、
连接 SolidWorks 实机建模并实时可视化。

> 站在巨人之肩 —— Claude Code 提示词体系、OpenHarness 架构理念、OpenClaw 调度设计、
> kimi-cli 基础设施、hermes-agent 渠道模式、cc-switch 路由方案，
> 以及 solidworks-automation-skill 的无头几何与 SolidWorks COM 自动化能力。

### 与 illusion-agent 的关系

IllusionForge 不是 illusion-agent 的一个分支功能，而是一次**收敛式演化**：

| 维度 | illusion-agent | IllusionForge |
|------|----------------|---------------|
| 交互界面 | 终端 TUI + Web UI 并列 | **仅 Web UI**（浏览器 / 桌面壳），终端 TUI 及其 React 前端整体移除 |
| 运行平台 | Windows / macOS / Linux | **仅 Windows**（SolidWorks COM 自动化只存在于 Windows） |
| 分发方式 | PyPI 包 + 三平台桌面安装包 | **GitHub Releases 的 Windows 安装包** + 源码安装，不再发布 PyPI 包 |
| 产品重心 | 通用编程智能体 | 编程智能体 **+ CAD 画布工作台**（SolidWorks 实机建模） |
| `illusion-forge` 命令 | 启动终端会话 | 启动 Web UI；`-p` 无头模式保留，供 cron 与脚本调用 |
| 智能体内核 | — | 完整保留：多模型、工具、子代理、压缩、MCP、插件、钩子、技能、渠道、Goal、Cron |

`illusion-agent` 仍作为独立项目继续维护；IllusionForge 的 Python 包名为 `illusion_forge`，
配置目录（`~/.illusion/`）、`settings.json` 与会话存储格式与 illusion-agent 兼容，
已有配置可直接沿用。

### 核心特性

- 🧊 **CAD 画布工作台** - React Flow 共享画布：需求卡 / 方案分支卡 / 3D 预览卡 / 快照分镜 / 参数表；侧边栏一键在"对话流 | 工作台"之间切换，两类会话各自独立
- 🔩 **SolidWorks 实机建模** - 专用 STA COM 宿主线程串行执行 51 个 CAD 工具（草图、特征、装配、孔、外观、运动、工程图、钣金、焊件……），建模过程以快照流 + 镜像特征树实时可视化
- 🧪 **无头 3D 预览** - 不启动 SolidWorks 也能用纯 Python 几何内核生成 GLB 预览钉在画布上；安装 OCP 后可额外导出 STEP / IGES
- 🔁 **双向协作与血缘审计** - 用户在 SolidWorks 里的选中项自动回流到 agent 上下文；方案卡与实机文档绑定血缘，尺寸级设计意图 diff
- 🤖 **多 AI 提供商支持** - Anthropic Claude、OpenAI、GitHub Copilot、OpenAI Codex 及任意 OpenAI 兼容端点
- 🧠 **多智能体协作** - 内置通用、探索、验证等专业子代理，支持任务编排
- 🛠️ **丰富的工具集** - 完整的基础工具 + 渠道工具 + MCP 动态工具扩展
- 📦 **上下文压缩** - 微压缩（清除旧工具结果）+ 全压缩（LLM 摘要），上下文占满时自动触发
- 🔌 **灵活扩展系统** - 插件、钩子、技能、MCP 服务器
- 🔐 **完善权限控制** - 多种模式 + 细粒度规则 + Always Allow 一键放行；Web 端信任栅栏与启动令牌认证
- 🎯 **Goal 自动续跑** - 长任务目标状态跨轮次持久化，自动续跑直到验证完成
- ⏰ **Cron 调度与消息渠道** - 无人值守任务通过无头模式执行；贯通飞书、微信、QQ
- 🌍 **中英双语** - 界面与文档双语，按 `ui_language` 自动切换
- 📦 **Windows 桌面版** - Electron 壳内置 Python / Node.js 运行时，NSIS 安装器一键安装，零环境配置，应用内自动更新

---

## 🚀 快速开始

### 环境要求

- Windows 10 / 11（x64 或 arm64）
- 桌面版：无需任何环境，安装包内置 Python 3.12 与 Node.js 24
- 源码运行：Python >= 3.10、Node.js 18+（构建 Web 前端）
- CAD 工作台实机建模：本机已安装 SolidWorks（无头预览与画布讨论不需要）

### 桌面版（推荐）

直接下载 Windows 安装包，零环境配置：

| 平台 | 下载文件 |
|------|----------|
| Windows | `IllusionForge-Setup-<版本>.exe`（NSIS 安装器） |

👉 [从 GitHub Releases 下载](https://github.com/YunTaiHua/illusion-forge/releases/latest)

桌面版启动后会在随机端口拉起后端并加载 Web UI，关闭窗口最小化到托盘，详见[桌面版文档](docs/zh-CN/desktop.md)。

### 源码安装

```bash
git clone https://github.com/YunTaiHua/illusion-forge.git
cd illusion-forge

# 安装后端（含开发依赖）
pip install -e ".[dev,all]"

# 构建 Web 前端（frontend/web/dist）
python scripts/build_frontend.py
```

### 基本使用

```bash
# 首次使用：配置认证（登录后会引导设置工作目录）
illusion-forge auth login

# 启动 Web UI（默认界面，自动打开浏览器）
illusion-forge

# 指定端口 / 监听地址启动 Web UI
illusion-forge --port 3200

# 无头模式：执行单个提示词后退出
illusion-forge -p "帮我分析这个项目的结构"

# 设置或更新工作目录
illusion-forge set "E:\Projects\my-project"

# 检查是否有新版本（GitHub Releases）
illusion-forge update
```

### 进入 CAD 工作台

1. 在 Web UI 左侧栏底部点击 **工作台**（两键分段切换器：`对话流 | 工作台`），布局切换为共享画布 + 对话面板，并自动新建一个工作台会话；
2. 与 agent 讨论方案，它会在画布上创建需求卡、方案分支卡与 3D 预览卡；
3. 需要实机建模时让 agent 连接 SolidWorks（`cad_connect`），右上角浮动的"建模实时"卡片自动展开，切换 **实时视口 / 特征树 / 快照历史** 页签观察建模过程。

工作台与对话流的会话列表相互独立，多开互不干扰。完整说明见 [CAD 画布工作台文档](docs/zh-CN/cad-workbench.md)。

### 无头模式说明

`-p` / `--print` 以非交互方式执行单次请求并立即退出，是 cron 守护进程执行任务的方式，也适合脚本调用：

```bash
# 只读分析（安全，默认权限模式）
illusion-forge -p "帮我分析这个项目的结构"

# 允许写入文件 / 执行命令，无需交互式审批
illusion-forge --permission-mode full_auto -p "修复失败的测试"

# 进程以退出码 2 结束后，继续回答待处理的问题 / 权限 / 计划
illusion-forge -c -p "Y"

# 指定模型和 effort 等级
illusion-forge -m env_1.model_2 -e high -p "重构此模块"
```

重要细节：

- 提示词值必须放在 **最后一个参数**，因为 typer 会贪婪解析 `-p`。
- 默认权限模式下，变更类工具会以退出码 **2** 退出并保留待审批项；使用 `illusion-forge -c -p "Y"` 或 `"N"` 继续回答。
- 退出码：`0` 成功，`1` 错误，`2` 等待跨轮次输入。
- `-c` / `-r` 只在无头模式下有意义；Web UI 自带会话列表。

---

## 📚 详细文档

| 主题 | English | 中文 |
|------|---------|------|
| 项目简介 | [docs/en/introduction.md](docs/en/introduction.md) | [docs/zh-CN/introduction.md](docs/zh-CN/introduction.md) |
| 快速开始 | [docs/en/getting-started.md](docs/en/getting-started.md) | [docs/zh-CN/getting-started.md](docs/zh-CN/getting-started.md) |
| CAD 画布工作台 | [docs/en/cad-workbench.md](docs/en/cad-workbench.md) | [docs/zh-CN/cad-workbench.md](docs/zh-CN/cad-workbench.md) |
| 桌面版 | [docs/en/desktop.md](docs/en/desktop.md) | [docs/zh-CN/desktop.md](docs/zh-CN/desktop.md) |
| 命令系统 | [docs/en/commands.md](docs/en/commands.md) | [docs/zh-CN/commands.md](docs/zh-CN/commands.md) |
| Goal 自动续跑目标 | [docs/en/goal.md](docs/en/goal.md) | [docs/zh-CN/goal.md](docs/zh-CN/goal.md) |
| 设置与凭据 | [docs/en/settings.md](docs/en/settings.md) | [docs/zh-CN/settings.md](docs/zh-CN/settings.md) |
| 项目文件与记忆 | [docs/en/project-files.md](docs/en/project-files.md) | [docs/zh-CN/project-files.md](docs/zh-CN/project-files.md) |
| 扩展系统 (MCP, 插件, 技能, 钩子) | [docs/en/extensions.md](docs/en/extensions.md) | [docs/zh-CN/extensions.md](docs/zh-CN/extensions.md) |
| 项目架构 | [docs/en/architecture.md](docs/en/architecture.md) | [docs/zh-CN/architecture.md](docs/zh-CN/architecture.md) |
| Web UI 安全 | [docs/en/security.md](docs/en/security.md) | [docs/zh-CN/security.md](docs/zh-CN/security.md) |
| Token 计量与压缩 | [docs/en/token-metering.md](docs/en/token-metering.md) | [docs/zh-CN/token-metering.md](docs/zh-CN/token-metering.md) |
| 消息渠道 | [docs/en/channels.md](docs/en/channels.md) | [docs/zh-CN/channels.md](docs/zh-CN/channels.md) |
| @ 提及（技能 / 会话 / 文件） | [docs/en/mentions.md](docs/en/mentions.md) | [docs/zh-CN/mentions.md](docs/zh-CN/mentions.md) |

---

## 📄 许可证

本项目采用 [MIT](LICENSE) 许可证开源。CAD 工作台内置的无头几何与 SolidWorks COM 模块来自
[solidworks-automation-skill](https://github.com/wzyn20051216/solidworks-automation-skill)（MIT License），归属与同步策略见
[CAD 画布工作台文档](docs/zh-CN/cad-workbench.md#上游归属与同步)。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

</div>
