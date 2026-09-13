"""
服务模块导出
==========

本模块导出 services 子目录中的公共接口。
"""

from __future__ import annotations

from illusion_forge.services.checkpoint_store import CheckpointStore, RestoreResult
from illusion_forge.services.compact import (
    AutoCompactState,
    TokenWarningState,
    calculate_token_warning_state,
    compact_conversation,
    compact_messages,
    create_compact_boundary_marker,
    estimate_conversation_tokens,
    get_autocompact_threshold,
    get_context_window,
    get_messages_after_compact_boundary,
    is_compact_boundary_marker,
    microcompact_messages,
    reactive_compact,
    should_autocompact,
    strip_images_from_messages,
    summarize_messages,
)
from illusion_forge.services.session_storage import (
    export_session_markdown,
    get_project_session_dir,
    read_index,
    read_meta,
    write_index,
    write_meta,
)
from illusion_forge.services.token_estimation import estimate_message_tokens, estimate_tokens

__all__ = [
    "AutoCompactState",
    "CheckpointStore",
    "RestoreResult",
    "TokenWarningState",
    "calculate_token_warning_state",
    "compact_conversation",
    "compact_messages",
    "create_compact_boundary_marker",
    "estimate_conversation_tokens",
    "estimate_message_tokens",
    "estimate_tokens",
    "export_session_markdown",
    "get_autocompact_threshold",
    "get_context_window",
    "get_messages_after_compact_boundary",
    "get_project_session_dir",
    "is_compact_boundary_marker",
    "microcompact_messages",
    "reactive_compact",
    "read_index",
    "read_meta",
    "should_autocompact",
    "strip_images_from_messages",
    "summarize_messages",
    "write_index",
    "write_meta",
]
