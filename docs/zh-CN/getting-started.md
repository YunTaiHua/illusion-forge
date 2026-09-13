# 快速开始

## 🚀 快速开始

### 环境要求

- Windows 10/11（x64 或 arm64）
- Python >= 3.10（源码安装时；桌面安装器内置 Python 3.12，无需额外安装）
- 网络连接（用于下载依赖与模型 API 调用）

### 安装

#### 推荐方式：桌面版安装包

最简单的安装方式，内置 Python 3.12 + Node.js 24，自动注册 `illusion-forge` 命令到全局 PATH。**无需 Node.js 环境**，前端资源已预构建并包含在包中。

1. 从 [GitHub Releases](https://github.com/YunTaiHua/illusion-forge/releases) 下载 `IllusionForge-Setup-<版本>.exe`。
2. 运行安装程序（可按需选择安装目录）。
3. 安装器自动创建开始菜单快捷方式与桌面快捷方式，点击 `IllusionForge` 启动即可。

#### 备选方式：从源码安装

克隆仓库后本地安装：

```bash
git clone https://github.com/YunTaiHua/illusion-forge.git
cd illusion-forge
pip install -e ".[dev,all]"

# 构建前端
python scripts/build_frontend.py
```

需要 Node.js 24+（用于前端构建）。

> **适用场景**：适合希望修改源代码的开发者。与桌面安装包不同，源码安装需要自行安装 Python 和 Node.js。

#### 开发者方式：uv sync（适合活跃开发）

`uv sync` 创建 editable install，需要手动构建前端。适合需要频繁修改源代码的开发者。

```bash
git clone https://github.com/YunTaiHua/illusion-forge.git
cd illusion-forge
uv sync

# 手动构建前端（uv sync 后必须执行）
python scripts/build_frontend.py
```

> **注意**：`uv sync` 不会将 `illusion-forge` 命令注册到全局 PATH。使用方式：
>
> ```bash
> # 方式一：在项目目录下使用 uv run
> cd illusion-forge
> uv run illusion-forge
>
> # 方式二：激活虚拟环境
> # Windows
> .venv\Scripts\activate
> illusion-forge
>
> # 方式三：pip 全局安装（推荐）
> pip install .
>
> # 方式四：pip 可编辑安装（全局 + 代码即时生效）
> pip install -e .
> ```

### 基本使用

> **首次使用建议**：先执行 `illusion-forge auth login` 配置 API 认证，否则可能因未登录或模型不可用而报错退出。

```bash
# 首次使用：配置认证
illusion-forge auth login

# 启动 Web UI（推荐）
illusion-forge

# 显式启动 Web UI
illusion-forge

# 自定义端口启动 Web UI
illusion-forge --port 8080

# 非交互式打印模式：只读分析（默认权限模式下安全）
illusion-forge -p "帮我分析这个项目的结构"

# 打印模式并显式自动放行写入 / 命令执行
illusion-forge --permission-mode full_auto -p "修复失败的测试"

# 指定模型
illusion-forge -m env_1.model_2

# 继续最近会话（配合 -p 使用）
illusion-forge -c -p "继续上次会话"

# 恢复指定会话（配合 -p 使用）
illusion-forge -r <session-id> -p "继续"

# 在退出码 2 后回答待处理的权限 / 问题 / 计划
illusion-forge -c -p "Y"

# 设置权限模式
illusion-forge --permission-mode full_auto

# 设置推理强度（持久化到 settings）
illusion-forge -e high
```

> **注意**：IllusionForge 的唯一交互界面是 Web UI（`illusion-forge` 或 `illusion-forge`）。headless 打印模式（`-p`）供脚本和自动化场景使用。两者共享同一个后端运行时、设置和会话存储。

---

## Print 模式详解

`-p` / `--print` 以非交互方式执行单次提示词并立即退出，适用于脚本、CI 或其他智能体控制 IllusionForge 的场景。

### 重要规则

- `-p` 的值必须放在命令行 **最后一个参数**，因为 typer 会贪婪解析 `-p`。
- 当任务需要写入文件或执行命令时，请显式使用 `--permission-mode full_auto`。
- 默认权限模式下，变更类工具会以退出码 **2** 退出并保留待审批项。使用 `illusion-forge -c -p "Y"`（单次允许）或 `"N"`（拒绝）继续。如需长期免确认请使用 `--permission-mode full_auto`。

### 退出码

| 退出码 | 含义 | 下一步操作 |
|--------|------|------------|
| 0 | 成功 | 从 stdout 读取结果 |
| 1 | 错误 | 查看 stderr 了解详情 |
| 2 | 等待跨轮次输入 | 使用 `illusion-forge -c -p "<回答>"` 继续 |

### 常见用法

```bash
# 只读分析（安全）
illusion-forge -p "找出代码库中所有的 TODO 注释"

# 自主执行变更
illusion-forge --permission-mode full_auto -p "运行测试套件并修复失败项"

# 结构化 JSON 输出，供下游脚本解析
illusion-forge -p "列出 src/ 下的所有公共函数" --output-format json

# 多轮对话
illusion-forge -p "重构 auth.py 的计划"                          # 以退出码 2 提出问题
illusion-forge -c -p '{"方案": "JWT", "范围": "完整"}'            # 注入回答后继续执行
```

---

## 🧪 开发与测试

```bash
# 安装开发依赖
uv sync --dev

# 运行测试
pytest
```

---

## 📄 许可证

本项目采用 [MIT](../LICENSE) 许可证开源。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
