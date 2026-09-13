"""Tests for ToolResultBlock with media content."""
from __future__ import annotations

from illusion_forge.engine.messages import (
    MediaBlock,
    TextBlock,
    ToolResultBlock,
    _build_tool_result_content,
    serialize_content_block,
)


def test_tool_result_block_with_media_list():
    media = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="abc",
    )
    block = ToolResultBlock(
        tool_use_id="toolu_123",
        content=[media],
    )
    assert isinstance(block.content, list)
    assert len(block.content) == 1
    assert isinstance(block.content[0], MediaBlock)


def test_tool_result_block_string_content_still_works():
    block = ToolResultBlock(
        tool_use_id="toolu_123",
        content="plain text result",
    )
    assert block.content == "plain text result"


def test_tool_result_block_text_content_property():
    media = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="abc",
    )
    block = ToolResultBlock(
        tool_use_id="toolu_123",
        content=[media],
    )
    assert block.text_content == ""


def test_tool_result_block_text_content_mixed():
    media = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="abc",
    )
    text = TextBlock(text="some text")
    block = ToolResultBlock(
        tool_use_id="toolu_123",
        content=[text, media],
    )
    assert block.text_content == "some text"


def test_serialize_tool_result_with_media():
    media = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="abc",
    )
    block = ToolResultBlock(
        tool_use_id="toolu_123",
        content=[media],
    )
    result = serialize_content_block(block, provider_type="anthropic")
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "toolu_123"
    assert isinstance(result["content"], list)
    assert result["content"][0]["type"] == "image"


def test_serialize_tool_result_plain_string():
    block = ToolResultBlock(
        tool_use_id="toolu_123",
        content="hello world",
    )
    result = serialize_content_block(block, provider_type="anthropic")
    assert result["type"] == "tool_result"
    assert result["content"] == "hello world"


def test_tool_result_block_default_content():
    block = ToolResultBlock(tool_use_id="toolu_123")
    assert block.content == ""
    assert block.text_content == ""


def test_build_tool_result_content_with_media():
    metadata = {
        "media_category": "image",
        "media_type": "image/png",
        "media_data": "iVBOR...",
        "media_path": "/tmp/test.png",
        "media_size": 1024,
    }
    content = _build_tool_result_content("[image file: /tmp/test.png (1.0 KB, image/png)]", metadata)
    assert isinstance(content, list)
    assert len(content) == 2
    assert isinstance(content[0], TextBlock)
    assert "[image file:" in content[0].text
    assert isinstance(content[1], MediaBlock)
    assert content[1].data == "iVBOR..."


def test_build_tool_result_content_without_media():
    metadata = {}
    content = _build_tool_result_content("hello world", metadata)
    assert content == "hello world"
