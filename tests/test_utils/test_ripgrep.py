"""run_rg_checked 单元测试。

验证 run_rg_checked 的"不抛出异常"契约：所有 rg 失败路径
（RipgrepError、RipgrepNotFoundError、OSError、非零退出码）
都返回 (None, error_msg) 而非抛出异常。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from illusion_forge.utils.ripgrep import (
    RipgrepError,
    RipgrepNotFoundError,
    run_rg_checked,
)


class TestRunRgChecked:
    """run_rg_checked 契约测试。"""

    async def test_success_returns_stdout(self) -> None:
        """成功执行（退出码 0）返回 (stdout, None)。"""
        with patch(
            "illusion_forge.utils.ripgrep.run_rg", new_callable=AsyncMock
        ) as mock_rg:
            mock_rg.return_value = ("line1\nline2\n", "", 0)
            stdout, error = await run_rg_checked(["--files"])

        assert stdout == "line1\nline2\n"
        assert error is None

    async def test_no_match_returns_empty_stdout(self) -> None:
        """退出码 1（无匹配）返回空字符串 stdout。"""
        with patch(
            "illusion_forge.utils.ripgrep.run_rg", new_callable=AsyncMock
        ) as mock_rg:
            mock_rg.return_value = ("", "", 1)
            stdout, error = await run_rg_checked(["pattern"])

        assert stdout == ""
        assert error is None

    async def test_nonzero_exit_returns_error(self) -> None:
        """非零退出码（非 1）返回 (None, error_msg)。"""
        with patch(
            "illusion_forge.utils.ripgrep.run_rg", new_callable=AsyncMock
        ) as mock_rg:
            mock_rg.return_value = ("", "regex error", 2)
            stdout, error = await run_rg_checked(["bad-regex"])

        assert stdout is None
        assert error is not None
        assert "退出码 2" in error
        assert "regex error" in error

    async def test_ripgrep_error_is_caught(self) -> None:
        """RipgrepError 被捕获为 (None, error_msg)，不抛出。"""
        with patch(
            "illusion_forge.utils.ripgrep.run_rg", new_callable=AsyncMock
        ) as mock_rg:
            mock_rg.side_effect = RipgrepError("rg 执行超时（20秒）")
            stdout, error = await run_rg_checked(["pattern"])

        assert stdout is None
        assert error == "rg 执行超时（20秒）"

    async def test_ripgrep_not_found_error_is_caught(self) -> None:
        """RipgrepNotFoundError 被捕获为 (None, error_msg)，不抛出。"""
        with patch(
            "illusion_forge.utils.ripgrep.run_rg", new_callable=AsyncMock
        ) as mock_rg:
            mock_rg.side_effect = RipgrepNotFoundError("rg 不可用")
            stdout, error = await run_rg_checked(["pattern"])

        assert stdout is None
        assert error == "rg 不可用"

    async def test_os_error_is_caught(self) -> None:
        """OSError 被捕获为 (None, error_msg)，不抛出。"""
        with patch(
            "illusion_forge.utils.ripgrep.run_rg", new_callable=AsyncMock
        ) as mock_rg:
            mock_rg.side_effect = OSError("Permission denied")
            stdout, error = await run_rg_checked(["pattern"])

        assert stdout is None
        assert error is not None
        assert "rg 执行失败" in error
        assert "Permission denied" in error

    async def test_value_error_is_caught(self) -> None:
        """ValueError 被捕获为 (None, error_msg)，不抛出。"""
        with patch(
            "illusion_forge.utils.ripgrep.run_rg", new_callable=AsyncMock
        ) as mock_rg:
            mock_rg.side_effect = ValueError("bad arg")
            stdout, error = await run_rg_checked(["pattern"])

        assert stdout is None
        assert error is not None
        assert "rg 执行失败" in error
