"""Tests for CLAUDE.md loading."""

from __future__ import annotations

from pathlib import Path

from illusion_forge.config.settings import Settings
from illusion_forge.prompts import (
    build_runtime_system_prompt,
    discover_claude_md_files,
    load_claude_md_prompt,
)


def test_discover_claude_md_files(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("root instructions", encoding="utf-8")
    rules_dir = repo / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "python.md").write_text("rule instructions", encoding="utf-8")

    files = discover_claude_md_files(repo)

    assert repo / "CLAUDE.md" in files
    assert rules_dir / "python.md" in files


def test_discover_claude_md_files_does_not_traverse_parents(tmp_path: Path):
    repo = tmp_path / "repo"
    nested = repo / "pkg" / "mod"
    nested.mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("root instructions", encoding="utf-8")

    files = discover_claude_md_files(nested)

    assert repo / "CLAUDE.md" not in files
    assert files == []


def test_load_claude_md_prompt(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("be careful", encoding="utf-8")

    prompt = load_claude_md_prompt(repo)

    assert prompt is not None
    assert "Project Instructions" in prompt
    assert "be careful" in prompt


def test_build_runtime_system_prompt_combines_sections(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("repo rules", encoding="utf-8")

    prompt = build_runtime_system_prompt(Settings(), cwd=repo, latest_user_prompt="hello")

    assert "Environment" in prompt
    assert "Project Instructions" in prompt
    assert "repo rules" in prompt
    assert "Memory" in prompt
