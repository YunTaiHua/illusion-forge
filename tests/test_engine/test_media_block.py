"""Tests for MediaBlock content block."""
from __future__ import annotations

from illusion_forge.engine.messages import (
    MediaBlock,
    serialize_content_block,
)


def test_media_block_is_valid_content_block():
    block = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="iVBOR...",
    )
    assert block.type == "media"


def test_media_block_discriminator():
    block = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="abc",
    )
    assert isinstance(block, MediaBlock)


def test_serialize_media_block_anthropic_image():
    block = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="abc123",
    )
    result = serialize_content_block(block, provider_type="anthropic")
    assert result["type"] == "image"
    assert result["source"]["type"] == "base64"
    assert result["source"]["media_type"] == "image/png"
    assert result["source"]["data"] == "abc123"


def test_serialize_media_block_openai_image():
    block = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="abc123",
    )
    result = serialize_content_block(block, provider_type="openai_compat")
    assert result["type"] == "image_url"
    assert result["image_url"]["url"].startswith("data:image/png;base64,abc123")


def test_serialize_media_block_codex_image():
    block = MediaBlock(
        file_path="/tmp/img.png",
        media_type="image/png",
        data="abc123",
    )
    result = serialize_content_block(block, provider_type="openai_codex")
    assert result["type"] == "input_image"
    assert result["image_url"].startswith("data:image/png;base64,abc123")
