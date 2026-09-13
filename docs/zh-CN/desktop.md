# 桌面版

IllusionForge 桌面版基于 Electron 封装 Web 端，内置 Python 与 Node.js 运行时，仅发行 Windows（NSIS 安装器）。

## 📦 下载与安装

### Windows

1. 下载 `IllusionForge-Setup-<版本>.exe`（从 [GitHub Releases](https://github.com/YunTaiHua/illusion-forge/releases)）。
2. 运行安装程序（可按需选择安装目录）。
3. 安装器自动创建开始菜单快捷方式与桌面快捷方式，点击 `IllusionForge` 启动即可。

安装器在安装时以标准方式注册应用身份（AppUserModelID）——系统通知与任务栏图标来自安装器创建的快捷方式，应用运行时不做任何注册。配置写入 `%USERPROFILE%\.illusion\`。

## 🪟 Windows 安装说明

- **标准安装**：NSIS 安装器，开始菜单/桌面快捷方式（携带 AppUserModelID）由安装器在安装与卸载时维护。
- **卸载**：通过"设置 → 应用"或安装器生成的卸载程序卸载；如需清理配置，删除 `%USERPROFILE%\.illusion\`。
- **SmartScreen 警告**：未签名 exe 首次运行时可能被拦截，按"更多信息"→"仍要运行"放行。
- **迁移**：配置在用户主目录，换机重装即可独立保留/导入配置。

## 🐍 内置 Python / Node.js 运行时

桌面版内置一份独立的 Python 与 Node.js 运行时，位于应用资源目录内，**不污染系统 PATH**。

### 检测逻辑

| 运行时 | 优先级 | 说明 |
|---|---|---|
| 用户自有 Python | 优先 | `PATH` 中可解析到符合版本要求的 `python` 时，使用用户环境 |
| 内置 Python | 兜底 | 用户环境缺失或版本不达标时，使用内置运行时（`desktop/resources/python/win-<arch>/`） |
| 用户自有 Node.js | 优先 | `PATH` 中可解析到符合版本要求的 `node` 时，使用用户环境 |
| 内置 Node.js | 兜底 | 用户环境缺失时，使用内置运行时（`desktop/resources/node/win-<arch>/`） |

`runtime.ts` 的 `platArch()` 返回 `win-x64` 或 `win-arm64`，对应目录名据此决定。桌面壳通过 `python -m illusion_forge forge --port <port>` 拉起后端，并从 stdout 解析 `Illusion Forge Web UI: http://...?token=...` 加载。

### 暴露给 LLM 工具调用

- **用户已有环境**：仅用内置 Python 启动后端，不向用户暴露内置运行时。
- **用户无 Python 环境**：内置 Python 的 bin 目录被加到后端进程的 `PATH` 前面，LLM 的工具调用（如 bash 工具执行 `python xxx.py`）能直接使用内置运行时。

## 📌 托盘行为

| 操作 | 行为 |
|---|---|
| 点击窗口关闭按钮（×） | 隐藏窗口到系统托盘，应用继续运行 |
| 托盘图标单击 | 显示/隐藏主窗口 |
| 托盘菜单 → 显示/隐藏主窗口 | 切换主窗口显隐 |
| 托盘菜单 → 打开终端（cmd） | 打开命令提示符 |
| 托盘菜单 → 退出 | 真正退出：关闭守护进程、释放端口、退出应用 |
| 重复启动 | 聚焦到现有窗口，不启动新实例 |

后端进程树通过 `taskkill /T /F` 结束，确保 Python 子进程与 Electron 一起干净退出。

窗口无边框（`frame: false`），自定义顶部栏（最小化/最大化/关闭按钮 + 标题）。

## 🔄 更新

### 自动更新（推荐）

桌面版通过 electron-updater 自动更新（基于 GitHub Releases，点击式：发现新版本仅在顶栏亮出图标，点击图标才开始下载，不打扰使用）：

1. 应用每次启动后自动检查新版本；长期不关程序时每 12 小时复查一次兜底。
2. 发现新版本时顶栏最小化按钮附近出现**闪烁的下载图标**（安装按钮不闪烁）；点击图标开始下载，下载中显示进度环。
3. 下载完成后图标变为**圆圈对勾的安装就绪态**，与下载图标明显区分：点击图标才退出应用并进入**显式安装**（显示完整安装进度，完成后自动重启应用）；正常退出应用不会触发安装。
4. 托盘隐藏期间下载完成会有系统通知提醒。

更新包经 SHA512 校验保证完整性；更新在现有安装上原地执行，配置目录 `~/.illusion/` 跨版本保留。

### 手动更新

在现有安装上重新运行新版 `IllusionForge-Setup-<版本>.exe` 即可原地更新。

## ⚠️ 注意事项

- **未签名**：Windows 触发 SmartScreen，按"更多信息"→"仍要运行"放行。
- **首次启动较慢**：内置运行时首次初始化需数秒。

## 🔧 构建脚本

桌面版构建脚本（仅 Windows 运行，非 Windows 直接报错退出）：

| 脚本 | 用途 |
|------|------|
| `scripts/build_desktop.py --all` | 全流程：fetch python + fetch node + build icons + dist |
| `scripts/build_desktop.py --fetch` | 下载 Python + Node.js 运行时 |
| `scripts/build_desktop.py --install` | 安装运行时到 `desktop/resources/` |
| `scripts/build_desktop.py --icons` | 生成图标（`icon.ico` + `icon.png`） |
| `scripts/build_desktop.py --dist` | 调用 electron-builder 打包 |
| `scripts/fetch_python.py` | 下载 python-build-standalone Windows install_only tar.gz |
| `scripts/fetch_node.py` | 下载 nodejs.org Windows zip |
| `scripts/build_icons.py` | 只生成 `icon.ico` + `icon.png` |
| `scripts/sync_version.py` | 同步 Web 前端与桌面版版本号 |

`electron-builder.yml` 只有 `win/nsis` 目标（`appId: com.illusionforge.desktop`，`productName/executableName/shortcutName: IllusionForge`，`artifactName: IllusionForge-Setup-${version}.${ext}`，publish 到 GitHub `YunTaiHua/illusion-forge`）。

## 🔁 CI / 发布

- **`.github/workflows/ci.yml`**：`windows-latest`，ruff + pytest。
- **`.github/workflows/release-desktop.yml`**：`windows-latest`，`v*` tag 触发，上传 `*.exe` / `latest*.yml` / `*.blockmap`。
- 无 `publish.yml`。
