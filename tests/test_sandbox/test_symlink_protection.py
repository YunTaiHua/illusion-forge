"""符号链接防护测试"""
import os

from illusion_forge.sandbox.symlink_protection import (
    is_symlink_outside_boundary,
    normalize_path_for_sandbox,
)


def test_root_is_outside_boundary():
    assert is_symlink_outside_boundary("/some/path", "/") is True


def test_single_component_is_outside_boundary():
    assert is_symlink_outside_boundary("/some/path", "/tmp") is True
    assert is_symlink_outside_boundary("/some/path", "/usr") is True


def test_ancestor_is_outside_boundary():
    assert is_symlink_outside_boundary("/some/path/deep", "/some") is True


def test_same_path_is_inside():
    assert is_symlink_outside_boundary("/some/path", "/some/path") is False


def test_child_path_is_inside():
    assert is_symlink_outside_boundary("/some/path", "/some/path/child") is False


def test_macos_private_tmp_allowed():
    assert is_symlink_outside_boundary("/tmp/claude", "/private/tmp/claude") is False


def test_macos_private_var_allowed():
    assert is_symlink_outside_boundary("/var/folders/xx", "/private/var/folders/xx") is False


def test_normalize_expands_tilde():
    result = normalize_path_for_sandbox("~/projects")
    home = os.path.expanduser("~")
    assert result == os.path.join(home, "projects")


def test_normalize_resolves_relative():
    result = normalize_path_for_sandbox("./subdir", cwd="/work")
    # Windows 使用反斜杠，Linux/macOS 使用正斜杠
    expected = os.path.normpath("/work/subdir")
    assert result == expected
