"""
ripgrep 模块测试
"""

import platform
import sys
from unittest.mock import patch

import pytest

from illusion_forge.utils.ripgrep import get_platform_key, get_rg_binary_name


def test_get_platform_key_windows_x64(monkeypatch):
    """测试 Windows x64 平台检测"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "machine", lambda: "AMD64")
    assert get_platform_key() == "x64-win32"


def test_get_platform_key_windows_arm64(monkeypatch):
    """测试 Windows ARM64 平台检测"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "machine", lambda: "ARM64")
    assert get_platform_key() == "arm64-win32"


def test_get_platform_key_darwin_x64(monkeypatch):
    """测试 macOS x64 平台检测"""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert get_platform_key() == "x64-darwin"


def test_get_platform_key_darwin_arm64(monkeypatch):
    """测试 macOS ARM64 平台检测"""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert get_platform_key() == "arm64-darwin"


def test_get_platform_key_linux_x64(monkeypatch):
    """测试 Linux x64 平台检测"""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert get_platform_key() == "x64-linux"


def test_get_platform_key_linux_arm64(monkeypatch):
    """测试 Linux ARM64 平台检测"""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    assert get_platform_key() == "arm64-linux"


def test_get_rg_binary_name_windows():
    """测试 Windows 平台的 rg 二进制文件名"""
    assert get_rg_binary_name("x64-win32") == "rg.exe"
    assert get_rg_binary_name("arm64-win32") == "rg.exe"


def test_get_rg_binary_name_unix():
    """测试 Unix 平台的 rg 二进制文件名"""
    assert get_rg_binary_name("x64-darwin") == "rg"
    assert get_rg_binary_name("arm64-darwin") == "rg"
    assert get_rg_binary_name("x64-linux") == "rg"
    assert get_rg_binary_name("arm64-linux") == "rg"


# Task 2: rg 路径解析和发现测试

def test_find_rg_from_env(monkeypatch, tmp_path):
    """测试从环境变量获取 rg 路径"""
    rg_name = "rg.exe" if sys.platform == "win32" else "rg"
    rg_path = str(tmp_path / rg_name)
    # 创建假的 rg 文件
    with open(rg_path, "w") as f:
        f.write("")
    monkeypatch.setenv("ILLUSION_RIPGREP_PATH", rg_path)
    from illusion_forge.utils.ripgrep import find_rg_path
    result = find_rg_path()
    assert result == rg_path


def test_find_rg_from_cache(monkeypatch, tmp_path):
    """测试从缓存目录获取 rg 路径"""
    rg_name = "rg.exe" if sys.platform == "win32" else "rg"
    rg_path = str(tmp_path / rg_name)
    with open(rg_path, "w") as f:
        f.write("")
    monkeypatch.delenv("ILLUSION_RIPGREP_PATH", raising=False)
    with patch("illusion_forge.utils.ripgrep.get_cache_dir", return_value=str(tmp_path)):
        from illusion_forge.utils.ripgrep import find_rg_path
        result = find_rg_path()
        assert result == rg_path


def test_find_rg_from_path(monkeypatch):
    """测试从系统 PATH 获取 rg 路径"""
    monkeypatch.delenv("ILLUSION_RIPGREP_PATH", raising=False)
    with patch("illusion_forge.utils.ripgrep.get_cache_dir", return_value="/nonexistent"), patch(
        "shutil.which", return_value="/usr/bin/rg"
    ):
        from illusion_forge.utils.ripgrep import find_rg_path
        result = find_rg_path()
        assert result == "/usr/bin/rg"


def test_find_rg_not_found(monkeypatch):
    """测试 rg 不可用时抛出异常"""
    monkeypatch.delenv("ILLUSION_RIPGREP_PATH", raising=False)
    with patch("illusion_forge.utils.ripgrep.get_cache_dir", return_value="/nonexistent"), patch(
        "shutil.which", return_value=None
    ):
        from illusion_forge.utils.ripgrep import RipgrepNotFoundError, find_rg_path
        with pytest.raises(RipgrepNotFoundError):
            find_rg_path()


# Task 3: rg 自动下载功能测试

def test_download_rg_creates_cache_dir(monkeypatch, tmp_path):
    """测试下载功能创建缓存目录"""
    import urllib.error
    import urllib.request
    monkeypatch.setattr("illusion_forge.utils.ripgrep.get_cache_dir", lambda: str(tmp_path / "cache"))
    # 模拟下载失败（urllib.request.urlretrieve 实际抛出 URLError/OSError）
    def mock_urlretrieve(url, filename):
        raise urllib.error.URLError("模拟网络错误")
    monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)
    from illusion_forge.utils.ripgrep import RipgrepNotFoundError, download_rg
    with pytest.raises(RipgrepNotFoundError):
        download_rg()
    # 验证缓存目录已创建
    assert (tmp_path / "cache").exists()


def test_extract_zip(tmp_path):
    """测试 ZIP 文件解压"""
    import zipfile
    # 创建测试 ZIP 文件
    zip_path = tmp_path / "test.zip"
    rg_path = tmp_path / "rg.exe"
    with open(rg_path, "w") as f:
        f.write("fake rg")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(rg_path, "rg.exe")

    # 测试解压
    from illusion_forge.utils.ripgrep import extract_zip
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    extract_zip(str(zip_path), str(extract_dir))
    assert (extract_dir / "rg.exe").exists()


def test_extract_tar(tmp_path):
    """测试 TAR.GZ 文件解压"""
    import tarfile
    # 创建测试 TAR 文件
    tar_path = tmp_path / "test.tar.gz"
    rg_path = tmp_path / "rg"
    with open(rg_path, "w") as f:
        f.write("fake rg")
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(rg_path, "rg")

    # 测试解压
    from illusion_forge.utils.ripgrep import extract_tar
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    extract_tar(str(tar_path), str(extract_dir))
    assert (extract_dir / "rg").exists()


# Task 4: ensure_ripgrep 和 run_rg 函数测试

@pytest.mark.asyncio
async def test_ensure_ripgrep_from_cache(monkeypatch, tmp_path):
    """测试 ensure_ripgrep 从缓存获取 rg"""
    import asyncio

    rg_name = "rg.exe" if sys.platform == "win32" else "rg"
    rg_path = str(tmp_path / rg_name)

    def _create_rg_file():
        with open(rg_path, "w") as f:
            f.write("")

    await asyncio.to_thread(_create_rg_file)
    monkeypatch.setattr("illusion_forge.utils.ripgrep.find_rg_path", lambda: rg_path)
    from illusion_forge.utils.ripgrep import ensure_ripgrep
    result = await ensure_ripgrep()
    assert result == rg_path


@pytest.mark.asyncio
async def test_ensure_ripgrep_download(monkeypatch, tmp_path):
    """测试 ensure_ripgrep 下载 rg"""
    rg_path = str(tmp_path / "rg")
    from illusion_forge.utils.ripgrep import RipgrepNotFoundError
    def mock_find_rg():
        raise RipgrepNotFoundError("test")
    monkeypatch.setattr("illusion_forge.utils.ripgrep.find_rg_path", mock_find_rg)
    monkeypatch.setattr("illusion_forge.utils.ripgrep.download_rg", lambda: rg_path)
    from illusion_forge.utils.ripgrep import ensure_ripgrep
    result = await ensure_ripgrep()
    assert result == rg_path


@pytest.mark.asyncio
async def test_run_rg_success(monkeypatch):
    """测试 run_rg 成功执行"""
    import asyncio

    from illusion_forge.utils.ripgrep import run_rg

    # 模拟 rg 执行
    class MockProcess:
        def __init__(self):
            self.returncode = 0
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stdout.feed_data(b"test output\n")
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        async def communicate(self):
            return b"test output", b""

        async def wait(self):
            return 0

    async def mock_exec(*args, **kwargs):
        return MockProcess()

    async def mock_ensure():
        return "/usr/bin/rg"

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_exec)
    monkeypatch.setattr("illusion_forge.utils.ripgrep.ensure_ripgrep", mock_ensure)
    stdout, _stderr, returncode = await run_rg(["--version"])
    assert returncode == 0
    assert "test output" in stdout


@pytest.mark.asyncio
async def test_run_rg_timeout(monkeypatch):
    """测试 run_rg 超时"""
    import asyncio

    from illusion_forge.utils.ripgrep import RipgrepError, run_rg

    class MockProcess:
        def __init__(self):
            self.returncode = 0
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()

        async def communicate(self):
            await asyncio.sleep(100)
            return b"", b""

        async def wait(self):
            await asyncio.sleep(100)
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    async def mock_exec(*args, **kwargs):
        return MockProcess()

    async def mock_ensure():
        return "/usr/bin/rg"

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_exec)
    monkeypatch.setattr("illusion_forge.utils.ripgrep.ensure_ripgrep", mock_ensure)
    with pytest.raises(RipgrepError):
        await run_rg(["--version"], timeout=0.1)


class TestRunRgCancel:
    """run_rg 在 CancelledError 时应 kill 子进程。"""

    @pytest.mark.asyncio
    async def test_cancelled_error_kills_rg_process(self, monkeypatch):
        """CancelledError 传播时 process.kill() 被调用。"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        # 模拟 ensure_ripgrep 返回路径
        async def _fake_ensure():
            return "/fake/rg"
        monkeypatch.setattr("illusion_forge.utils.ripgrep.ensure_ripgrep", _fake_ensure)

        # 模拟 create_subprocess_exec 返回 mock 进程
        process = MagicMock()
        process.kill = MagicMock()
        process.wait = AsyncMock()
        process.returncode = None

        async def _slow_communicate():
            await asyncio.sleep(100)
        process.communicate = _slow_communicate

        async def _fake_create(*args, **kwargs):
            return process
        monkeypatch.setattr("illusion_forge.utils.ripgrep.asyncio.create_subprocess_exec", _fake_create)

        from illusion_forge.utils.ripgrep import run_rg

        task = asyncio.create_task(run_rg(["pattern"], timeout=1000))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert process.kill.called, "process.kill() should be called on CancelledError"
