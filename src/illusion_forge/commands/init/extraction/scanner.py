"""
项目扫描器
==========

发现源文件，检测语言、框架、包管理器、构建命令等。
优先使用 git ls-files 进行快速文件发现（尊重 .gitignore）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from illusion_forge.commands.init.types import FileInfo, ProjectData

# 文件扩展名到语言的映射
_LANG_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "React",
    ".tsx": "React",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".dart": "Dart",
    ".scala": "Scala",
    ".lua": "Lua",
    ".r": "R",
    ".vue": "Vue",
    ".svelte": "Svelte",
}

# 应忽略的目录
_IGNORE_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "coverage", ".coverage", "htmlcov", ".eggs", "*.egg-info",
    ".illusion", ".claude", ".cursor", ".vscode", ".idea",
})

# 框架检测：配置文件 -> 框架名
_CONFIG_FRAMEWORKS: dict[str, str] = {
    "next.config.js": "Next.js",
    "next.config.mjs": "Next.js",
    "next.config.ts": "Next.js",
    "nuxt.config.js": "Nuxt",
    "nuxt.config.ts": "Nuxt",
    "angular.json": "Angular",
    "vue.config.js": "Vue",
    "svelte.config.js": "Svelte",
    "gatsby-config.js": "Gatsby",
    "astro.config.mjs": "Astro",
    "remix.config.js": "Remix",
}

# 包管理器检测
_PACKAGE_MANAGERS: list[tuple[str, str]] = [
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lockb", "bun"),
    ("package-lock.json", "npm"),
    ("Cargo.toml", "cargo"),
    ("go.mod", "go"),
    ("Gemfile", "bundler"),
    ("composer.json", "composer"),
    ("pubspec.yaml", "pub"),
]

# Python 包管理器检测
_PYTHON_MANAGERS: list[tuple[str, str]] = [
    ("poetry.lock", "poetry"),
    ("uv.lock", "uv"),
    ("Pipfile.lock", "pipenv"),
    ("pdm.lock", "pdm"),
    ("requirements.txt", "pip"),
    ("pyproject.toml", "pip"),
]

# CI 配置检测
_CI_CONFIGS: dict[str, str] = {
    ".github/workflows": "GitHub Actions",
    ".gitlab-ci.yml": "GitLab CI",
    "Jenkinsfile": "Jenkins",
    ".circleci/config.yml": "CircleCI",
    ".travis.yml": "Travis CI",
    "azure-pipelines.yml": "Azure Pipelines",
    "bitbucket-pipelines.yml": "Bitbucket Pipelines",
}

# 格式化工具配置
_FORMAT_CONFIGS: dict[str, str] = {
    ".prettierrc": "prettier",
    ".prettierrc.json": "prettier",
    ".prettierrc.js": "prettier",
    ".prettierrc.cjs": "prettier",
    "prettier.config.js": "prettier",
    "biome.json": "biome",
    ".eslintrc": "eslint",
    ".eslintrc.json": "eslint",
    ".eslintrc.js": "eslint",
    "eslint.config.js": "eslint",
    "eslint.config.mjs": "eslint",
    ".golangci.yml": "golangci-lint",
    ".golangci.yaml": "golangci-lint",
    "rustfmt.toml": "rustfmt",
    ".rustfmt.toml": "rustfmt",
}

# AI 配置文件
_AI_CONFIGS = [
    ".cursor/rules",
    ".cursorrules",
    ".github/copilot-instructions.md",
    ".windsurfrules",
    ".clinerules",
    "AGENTS.md",
    "CLAUDE.md",
    "ILLUSION.md",
]


def scan_project(root: Path) -> ProjectData:
    """扫描项目结构，返回原始数据

    Args:
        root: 项目根目录

    Returns:
        项目提取数据
    """
    files = _discover_files(root)
    languages = _detect_languages(files)
    package_json = _read_json(root / "package.json")
    pyproject = _read_pyproject(root / "pyproject.toml")
    frameworks = _detect_frameworks(root, package_json, pyproject)
    package_manager = _detect_package_manager(root, languages)
    build_cmd, test_cmd, lint_cmd, format_cmd = _extract_commands(root, package_json, pyproject)
    ci_config = _detect_ci(root)
    readme_summary, readme_sections = _extract_readme_basic(root)
    existing_configs = _detect_ai_configs(root)
    config_files = _read_config_excerpts(root)

    return ProjectData(
        root=root,
        files=files,
        languages=languages,
        frameworks=frameworks,
        package_manager=package_manager,
        build_commands=build_cmd,
        test_commands=test_cmd,
        lint_commands=lint_cmd,
        format_commands=format_cmd,
        ci_config=ci_config,
        readme_summary=readme_summary,
        readme_sections=readme_sections,
        existing_ai_configs=existing_configs,
        config_files=config_files,
        pyproject_data=pyproject,
        package_json_data=package_json,
        modules=[],
    )


def _discover_files(root: Path) -> list[FileInfo]:
    """发现源文件，优先使用 git ls-files"""
    files = _try_git_ls_files(root)
    if not files:
        files = _walk_files(root)
    return files


def _try_git_ls_files(root: Path) -> list[FileInfo]:
    """尝试用 git ls-files 发现文件"""
    try:
        run_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, timeout=10, check=False,
            **run_kwargs,
        )
        if result.returncode != 0:
            return []
        files = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            path = root / line
            if path.is_file() and not _should_ignore(Path(line)):
                ext = path.suffix.lower()
                lang = _LANG_EXTENSIONS.get(ext)
                if lang:
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = 0
                    files.append(FileInfo(path=Path(line), language=lang, size=size))
        return files
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def _walk_files(root: Path) -> list[FileInfo]:
    """回退方案：使用 rglob 扫描文件"""
    files = []
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if _should_ignore(rel):
                continue
            ext = p.suffix.lower()
            lang = _LANG_EXTENSIONS.get(ext)
            if lang:
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                files.append(FileInfo(path=rel, language=lang, size=size))
    except OSError:
        pass
    return files


def _should_ignore(rel_path: Path) -> bool:
    """检查路径是否应被忽略"""
    for part in rel_path.parts:
        if part in _IGNORE_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _detect_languages(files: list[FileInfo]) -> dict[str, int]:
    """检测语言并统计文件数"""
    counts: dict[str, int] = {}
    for f in files:
        counts[f.language] = counts.get(f.language, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def _detect_frameworks(
    root: Path,
    package_json: dict[str, Any] | None,
    pyproject: dict[str, Any] | None,
) -> list[str]:
    """检测项目框架"""
    frameworks: list[str] = []

    # 从配置文件检测
    for config_file, framework in _CONFIG_FRAMEWORKS.items():
        if (root / config_file).exists() and framework not in frameworks:
            frameworks.append(framework)

    # 从 package.json 依赖检测
    if package_json:
        deps = {
            **package_json.get("dependencies", {}),
            **package_json.get("devDependencies", {}),
        }
        _JS_FRAMEWORK_DEPS = {
            "react": "React", "vue": "Vue", "svelte": "Svelte",
            "next": "Next.js", "nuxt": "Nuxt", "express": "Express",
            "fastify": "Fastify", "koa": "Koa", "angular": "Angular",
            "@angular/core": "Angular", "solid-js": "Solid.js",
            "preact": "Preact", "lit": "Lit",
        }
        for dep, name in _JS_FRAMEWORK_DEPS.items():
            if dep in deps and name not in frameworks:
                frameworks.append(name)

    # 从 pyproject.toml 依赖检测
    if pyproject:
        all_deps = _get_python_deps(pyproject)
        _PY_FRAMEWORK_DEPS = {
            "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
            "starlette": "Starlette", "tornado": "Tornado",
            "sanic": "Sanic", "aiohttp": "aiohttp",
            "pyramid": "Pyramid", "bottle": "Bottle",
            "streamlit": "Streamlit", "gradio": "Gradio",
        }
        for dep, name in _PY_FRAMEWORK_DEPS.items():
            if dep in all_deps and name not in frameworks:
                frameworks.append(name)

    return frameworks


def _get_python_deps(pyproject: dict[str, Any]) -> set[str]:
    """从 pyproject.toml 提取所有 Python 依赖名（小写）"""
    deps: set[str] = set()
    # PEP 621 格式
    for dep in pyproject.get("project", {}).get("dependencies", []):
        name = dep.split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("!")[0].split("~")[0].strip().lower()
        if name:
            deps.add(name)
    # Poetry 格式
    poetry_deps = pyproject.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for name in poetry_deps:
        if name.lower() != "python":
            deps.add(name.lower())
    return deps


def _detect_package_manager(root: Path, languages: dict[str, int]) -> str | None:
    """检测包管理器"""
    # Python 优先检测
    if "Python" in languages:
        for marker, manager in _PYTHON_MANAGERS:
            if (root / marker).exists():
                return manager

    # 通用检测
    for marker, manager in _PACKAGE_MANAGERS:
        if (root / marker).exists():
            return manager

    return None


def _extract_commands(
    root: Path,
    package_json: dict[str, Any] | None,
    pyproject: dict[str, Any] | None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """提取构建/测试/检查/格式化命令"""
    build: list[str] = []
    test: list[str] = []
    lint: list[str] = []
    fmt: list[str] = []

    # package.json scripts
    if package_json:
        scripts = package_json.get("scripts", {})
        _SCRIPT_MAP = {
            "build": (build, "npm run build"),
            "dev": (build, "npm run dev"),
            "test": (test, "npm test"),
            "lint": (lint, "npm run lint"),
            "format": (fmt, "npm run format"),
            "fmt": (fmt, "npm run fmt"),
        }
        for script_name, (target, cmd) in _SCRIPT_MAP.items():
            if script_name in scripts and cmd not in target:
                target.append(cmd)

    # pyproject.toml
    if pyproject:
        tool = pyproject.get("tool", {})
        if "ruff" in tool:
            if "ruff format" not in fmt:
                fmt.append("ruff format")
            if "ruff check" not in lint:
                lint.append("ruff check")
        if "black" in tool and "black" not in fmt:
            fmt.append("black")
        if "isort" in tool and "isort" not in fmt:
            fmt.append("isort")
        if "mypy" in tool and "mypy" not in lint:
            lint.append("mypy")
        if ("pytest" in tool or "pytest.ini_options" in tool) and "pytest" not in test:
            test.append("pytest")

        # Poetry scripts
        scripts = tool.get("poetry", {}).get("scripts", {})
        if scripts and not build:
            build.append("poetry run <script>")

    # Makefile
    makefile = root / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8", errors="replace")
            _MAKE_TARGETS: dict[str, tuple[list[str], str]] = {
                "build:": (build, "make build"),
                "test:": (test, "make test"),
                "lint:": (lint, "make lint"),
                "fmt:": (fmt, "make fmt"),
                "format:": (fmt, "make format"),
                "check:": (lint, "make check"),
            }
            for _target, (_bucket, _cmd) in _MAKE_TARGETS.items():
                if _target in content and _cmd not in _bucket:
                    _bucket.append(_cmd)
        except OSError:
            pass

    # 格式化工具配置文件
    for config_file, tool_name in _FORMAT_CONFIGS.items():
        if (root / config_file).exists() and tool_name not in fmt:
            fmt.append(tool_name)

    return build, test, lint, fmt


def _detect_ci(root: Path) -> str | None:
    """检测 CI 配置"""
    for path, name in _CI_CONFIGS.items():
        if (root / path).exists():
            return name
    return None


def _detect_ai_configs(root: Path) -> list[str]:
    """检测现有 AI 配置文件

    扫描范围：
    1. 项目根目录下的 AI 配置文件
    2. .illusion/ 目录下的 AI 配置文件

    Args:
        root: 项目根目录

    Returns:
        list[str]: 找到的配置文件路径列表（相对于根目录）
    """
    configs = []

    # 1. 扫描根目录下的 AI 配置文件
    for config in _AI_CONFIGS:
        if (root / config).exists():
            configs.append(config)

    # 2. 扫描 .illusion/ 目录下的 AI 配置文件
    illusion_dir = root / ".illusion"
    if illusion_dir.is_dir():
        for config in _AI_CONFIGS:
            illusion_config = illusion_dir / config
            if illusion_config.exists():
                configs.append(f".illusion/{config}")

    return configs


def _read_config_excerpts(root: Path) -> dict[str, str]:
    """读取关键配置文件的内容摘要"""
    excerpt_files = [
        "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
        "tsconfig.json", "jest.config.js", "vitest.config.ts",
        "pytest.ini", "setup.cfg", ".editorconfig",
    ]
    excerpts: dict[str, str] = {}
    for name in excerpt_files:
        path = root / name
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:200]
                excerpts[name] = content
            except OSError:
                pass
    return excerpts


def _extract_readme_basic(root: Path) -> tuple[str | None, dict[str, str]]:
    """基础 README 提取（详细解析在 readme.py）"""
    readme = root / "README.md"
    if not readme.exists():
        return None, {}
    try:
        content = readme.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")[:50]
        desc_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "![", "```")):
                continue
            if stripped.startswith("<"):
                continue
            if len(stripped) > 10:
                desc_lines.append(stripped)
            if len(desc_lines) >= 3:
                break
        summary = " ".join(desc_lines) if desc_lines else None
        return summary, {}
    except OSError:
        return None, {}


def _read_json(path: Path) -> dict[str, Any] | None:
    """安全读取 JSON 文件"""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            result: dict[str, Any] = json.load(f)
            return result
    except (json.JSONDecodeError, OSError):
        return None


def _read_pyproject(path: Path) -> dict[str, Any] | None:
    """安全读取 pyproject.toml"""
    if not path.exists():
        return None
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (ModuleNotFoundError, OSError, ValueError):
        # Python < 3.11 没有 tomllib
        try:
            import tomli
            with open(path, "rb") as f:
                return tomli.load(f)
        except (ModuleNotFoundError, OSError, ValueError):
            return None
