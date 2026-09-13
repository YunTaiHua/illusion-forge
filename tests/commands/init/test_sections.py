"""marker 章节管理工具测试"""

from illusion_forge.commands.init.generation.sections import (
    has_section,
    replace_section,
    wrap_section,
)


def test_wrap_section():
    result = wrap_section("overview", "Hello World")
    assert "<!-- ILLUSION:overview START -->" in result
    assert "Hello World" in result
    assert "<!-- ILLUSION:overview END -->" in result


def test_has_section():
    content = "before\n<!-- ILLUSION:tech-stack START -->\ndata\n<!-- ILLUSION:tech-stack END -->\nafter"
    assert has_section(content, "tech-stack") is True
    assert has_section(content, "overview") is False


def test_replace_section_existing():
    existing = "header\n<!-- ILLUSION:overview START -->\nold content\n<!-- ILLUSION:overview END -->\nfooter"
    result = replace_section(existing, "overview", "new content")
    assert "new content" in result
    assert "old content" not in result
    assert "header" in result
    assert "footer" in result


def test_replace_section_missing():
    existing = "some content"
    result = replace_section(existing, "overview", "new content")
    assert "some content" in result
    assert "new content" in result
    assert "<!-- ILLUSION:overview START -->" in result


def test_replace_section_preserves_manual_edit():
    existing = (
        "# My Doc\n\n"
        "manual edit here\n\n"
        "<!-- ILLUSION:overview START -->\nauto\n<!-- ILLUSION:overview END -->\n\n"
        "more manual edits\n"
    )
    result = replace_section(existing, "overview", "updated auto")
    assert "manual edit here" in result
    assert "more manual edits" in result
    assert "updated auto" in result
    assert "auto" not in result or "updated auto" in result
