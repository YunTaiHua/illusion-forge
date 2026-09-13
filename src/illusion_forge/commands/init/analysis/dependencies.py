"""
依赖用途分析器
==============

将项目依赖按用途分类：Web 框架、测试、代码检查、数据处理、CLI 等。
"""

from __future__ import annotations

from typing import Any

from illusion_forge.commands.init.types import ProjectData

# Python 依赖分类
_PY_CATEGORIES: dict[str, list[str]] = {
    "Web Frameworks": [
        "django", "flask", "fastapi", "starlette", "tornado", "sanic",
        "aiohttp", "pyramid", "bottle", "falcon", "litestar",
    ],
    "ASGI/WSGI Servers": [
        "uvicorn", "gunicorn", "hypercorn", "daphne", "waitress",
    ],
    "Testing": [
        "pytest", "pytest-cov", "pytest-asyncio", "pytest-xdist",
        "hypothesis", "tox", "nox", "coverage", "unittest2",
        "factory-boy", "faker", "responses", "httpx", "requests-mock",
    ],
    "Linting/Formatting": [
        "ruff", "black", "isort", "autopep8", "yapf",
        "flake8", "pylint", "pyflakes", "mccabe",
        "mypy", "pyright", "pytype",
    ],
    "Data/ORM": [
        "sqlalchemy", "alembic", "pydantic", "marshmallow",
        "pandas", "numpy", "scipy", "polars",
        "redis", "celery", "mongoengine", "peewee",
    ],
    "CLI": [
        "click", "typer", "argparse", "fire", "rich", "textual",
    ],
    "Async": [
        "asyncio", "aiohttp", "aiofiles", "aioredis", "anyio",
        "trio", "httpx",
    ],
    "HTTP Client": [
        "requests", "httpx", "aiohttp", "urllib3", "pycurl",
    ],
    "Serialization": [
        "pydantic", "marshmallow", "attrs", "cattrs",
        "orjson", "ujson", "msgpack",
    ],
    "Documentation": [
        "sphinx", "mkdocs", "pdoc", "pydoc-markdown",
    ],
}

# JS/TS 依赖分类
_JS_CATEGORIES: dict[str, list[str]] = {
    "Framework": [
        "react", "vue", "svelte", "angular", "@angular/core",
        "next", "nuxt", "solid-js", "preact", "lit",
        "express", "fastify", "koa", "hapi",
    ],
    "Testing": [
        "jest", "@jest/core", "vitest", "mocha", "chai",
        "@playwright/test", "cypress", "puppeteer",
        "@testing-library/react", "@testing-library/vue",
        "sinon", "nock",
    ],
    "Build": [
        "webpack", "vite", "rollup", "esbuild", "turbopack",
        "parcel", "swc", "@swc/core", "typescript",
    ],
    "Linting/Formatting": [
        "eslint", "prettier", "biome", "stylelint",
        "@typescript-eslint/parser", "@typescript-eslint/eslint-plugin",
    ],
    "State Management": [
        "redux", "@reduxjs/toolkit", "zustand", "jotai",
        "recoil", "mobx", "pinia", "vuex",
    ],
    "Styling": [
        "tailwindcss", "styled-components", "emotion",
        "sass", "less", "postcss", "css-modules",
    ],
    "HTTP Client": [
        "axios", "node-fetch", "got", "ky", "superagent",
    ],
    "ORM/Database": [
        "prisma", "typeorm", "sequelize", "knex", "drizzle-orm",
        "mongoose", "mongodb",
    ],
}


def analyze_dependencies(data: ProjectData) -> dict[str, list[str]]:
    """分析依赖用途分类

    Args:
        data: 提取阶段的项目数据

    Returns:
        category -> [packages] 的映射
    """
    result: dict[str, list[str]] = {}

    # Python 依赖
    py_deps = _get_python_dep_names(data.pyproject_data)
    if py_deps:
        _categorize_deps(py_deps, _PY_CATEGORIES, result)

    # JS/TS 依赖
    js_deps = _get_js_dep_names(data.package_json_data)
    if js_deps:
        _categorize_deps(js_deps, _JS_CATEGORIES, result)

    return result


def _get_python_dep_names(pyproject: dict[str, Any] | None) -> set[str]:
    """提取 Python 依赖名（小写）"""
    if not pyproject:
        return set()

    deps: set[str] = set()
    # PEP 621
    for dep in pyproject.get("project", {}).get("dependencies", []):
        name = dep.split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("!")[0].split("~")[0].strip().lower()
        if name:
            deps.add(name)
    # Poetry
    poetry_deps = pyproject.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for name in poetry_deps:
        if name.lower() != "python":
            deps.add(name.lower())
    # dev dependencies
    dev_deps = pyproject.get("tool", {}).get("poetry", {}).get("group", {}).get("dev", {}).get("dependencies", {})
    for name in dev_deps:
        deps.add(name.lower())
    # PEP 621 optional dependencies
    for group_deps in pyproject.get("project", {}).get("optional-dependencies", {}).values():
        for dep in group_deps:
            name = dep.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip().lower()
            if name:
                deps.add(name)

    return deps


def _get_js_dep_names(package_json: dict[str, Any] | None) -> set[str]:
    """提取 JS/TS 依赖名"""
    if not package_json:
        return set()

    deps: set[str] = set()
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        deps.update(package_json.get(section, {}).keys())
    return deps


def _categorize_deps(
    dep_names: set[str],
    categories: dict[str, list[str]],
    result: dict[str, list[str]],
) -> None:
    """将依赖按分类表归类"""
    for category, known_deps in categories.items():
        found = []
        for known in known_deps:
            if known in dep_names:
                found.append(known)
        if found:
            result[category] = found
