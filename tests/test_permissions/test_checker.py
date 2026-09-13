"""Tests for permission decisions."""

import logging

import pytest

from illusion_forge.config.settings import PathRuleConfig, PermissionSettings
from illusion_forge.permissions import PermissionChecker, PermissionMode


def test_default_mode_allows_read_only():
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))
    decision = checker.evaluate("read_file", is_read_only=True)
    assert decision.allowed is True
    assert decision.requires_confirmation is False


def test_default_mode_requires_confirmation_for_mutation():
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))
    decision = checker.evaluate("write_file", is_read_only=False)
    assert decision.allowed is False
    assert decision.requires_confirmation is True


def test_plan_mode_blocks_mutating_tools():
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.PLAN))
    decision = checker.evaluate("bash", is_read_only=False)
    assert decision.allowed is False
    assert "plan mode" in decision.reason


def test_plan_mode_plan_file_is_writable(tmp_path):
    """计划模式下，已注册的计划文件路径可写。"""
    plan_file = str(tmp_path / "my-plan.md")
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))
    checker.set_mode(PermissionMode.PLAN)
    checker.set_plan_file(plan_file)
    decision = checker.evaluate("write_file", is_read_only=False, file_path=plan_file)
    assert decision.allowed is True


def test_plan_mode_rejection_re_registers_plan_file(tmp_path):
    """用户拒绝计划后切回计划模式，计划文件仍可写（模拟 ExitPlanModeTool 拒绝流程）。"""
    plan_file = str(tmp_path / "my-plan.md")
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))
    # 进入计划模式并注册计划文件
    checker.set_mode(PermissionMode.PLAN)
    checker.set_plan_file(plan_file)

    # 模拟 ExitPlanModeTool 的拒绝流程：restore_mode + set_mode + set_plan_file
    checker.restore_mode()
    checker.set_mode(PermissionMode.PLAN)
    checker.set_plan_file(plan_file)

    # 计划文件应仍可写
    decision = checker.evaluate("write_file", is_read_only=False, file_path=plan_file)
    assert decision.allowed is True

    # 其他文件仍应被阻止
    other_file = str(tmp_path / "other.py")
    decision = checker.evaluate("write_file", is_read_only=False, file_path=other_file)
    assert decision.allowed is False
    assert decision.auto_blocked is True


def test_full_auto_allows_mutating_tools():
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    decision = checker.evaluate("bash", is_read_only=False)
    assert decision.allowed is True


# --- 计划模式进入/退出权限保留 ---


@pytest.mark.parametrize("start_mode", [PermissionMode.DEFAULT, PermissionMode.FULL_AUTO, PermissionMode.YOLO])
def test_plan_mode_exit_restores_original_mode(start_mode):
    """进入计划模式后退出，应恢复到进入前的权限模式（而非固定为 default）。"""
    plan_file = "C:/tmp/my-plan.md"
    checker = PermissionChecker(PermissionSettings(mode=start_mode))
    # 进入计划模式：保存原模式 + 切换 + 注册计划文件
    checker.set_mode(PermissionMode.PLAN)
    checker.set_plan_file(plan_file)
    assert checker.current_mode == PermissionMode.PLAN

    # 退出计划模式（批准）：恢复到原模式，清理计划文件
    checker.restore_mode()
    assert checker.current_mode == start_mode
    # 原模式恢复后，计划文件不再特殊豁免
    decision = checker.evaluate("write_file", is_read_only=False, file_path=plan_file)
    if start_mode in (PermissionMode.PLAN, PermissionMode.FULL_AUTO):
        assert decision.allowed is True
    else:
        # default/yolo 下计划文件不再被计划模式豁免
        assert decision.requires_confirmation or decision.allowed is True


def test_plan_mode_exit_rejected_reenters_plan_preserves_original():
    """用户拒绝计划后重新进入计划模式，再次退出仍恢复到进入前的原模式。"""
    plan_file = "C:/tmp/my-plan.md"
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    # 进入 → 拒绝（重进 plan） → 批准退出
    checker.set_mode(PermissionMode.PLAN)
    checker.set_plan_file(plan_file)
    # 拒绝：restore + 重进 plan + 重注册计划文件
    checker.restore_mode()
    checker.set_mode(PermissionMode.PLAN)
    checker.set_plan_file(plan_file)
    # 批准退出：应恢复到最初的 FULL_AUTO
    checker.restore_mode()
    assert checker.current_mode == PermissionMode.FULL_AUTO


def test_yolo_bypasses_sandbox():
    """YOLO 模式绕过沙箱限制，返回允许。"""
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.YOLO))
    # 即使路径本应被沙箱拒绝，YOLO 也放行
    checker.sync_sandbox_restrictions(
        type("S", (), {"enabled": True, "filesystem": type("F", (), {"deny_write": ["/etc/*"], "deny_read": []})})()
    )
    decision = checker.evaluate("bash", is_read_only=False, command="rm -rf /etc/x")
    assert decision.allowed is True
    assert "YOLO" in decision.reason
    assert decision.sandbox_blocked is False


def test_yolo_still_respects_explicit_deny_tool():
    """YOLO 模式仍保留显式工具拒绝规则。"""
    settings = PermissionSettings(mode=PermissionMode.YOLO, denied_tools=["bash"])
    checker = PermissionChecker(settings)
    decision = checker.evaluate("bash", is_read_only=False)
    assert decision.allowed is False


# --- 沙箱权限回调（FULL_AUTO 仍受沙箱约束） ---


def _sandbox_settings(**overrides):
    """构造启用了沙箱的简化 settings 对象。"""
    fs = {"deny_write": ["/etc/*"], "deny_read": ["/etc/shadow"], "allow_write": ["."]}
    fs.update(overrides.pop("filesystem", {}))
    return type(
        "S",
        (),
        {
            "enabled": True,
            "filesystem": type("F", (), fs),
        },
    )()


def test_full_auto_still_respects_sandbox_write_deny():
    """FULL_AUTO 模式仍受沙箱写入限制约束（正确回调沙箱权限）。"""
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    checker.sync_sandbox_restrictions(_sandbox_settings())
    decision = checker.evaluate("write_file", is_read_only=False, file_path="/etc/hosts")
    assert decision.allowed is False
    assert decision.sandbox_blocked is True


def test_full_auto_still_respects_sandbox_read_deny():
    """FULL_AUTO 模式仍受沙箱读取限制约束。"""
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    checker.sync_sandbox_restrictions(_sandbox_settings())
    decision = checker.evaluate("read_file", is_read_only=True, file_path="/etc/shadow")
    assert decision.allowed is False
    assert decision.sandbox_blocked is True


# --- 高危操作覆盖会话级允许 ---


def test_session_allow_reenables_access():
    """会话级允许后，常规操作不再被沙箱拦截。"""
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    checker.sync_sandbox_restrictions(_sandbox_settings())
    checker.allow_sandbox_path_for_session("/etc/hosts")
    decision = checker.evaluate("write_file", is_read_only=False, file_path="/etc/hosts")
    assert decision.allowed is True


def test_high_risk_overrides_session_allow():
    """高危操作（删除/还原）即使路径已被会话级允许，仍弹权限确认。"""
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    checker.sync_sandbox_restrictions(_sandbox_settings())
    checker.allow_sandbox_path_for_session("/etc/x")
    # 高危命令（rm）作用于会话已允许的路径，仍应 sandbox_blocked
    decision = checker.evaluate("bash", is_read_only=False, command="rm -rf /etc/x", file_path="/etc/x")
    assert decision.allowed is False
    assert decision.sandbox_blocked is True
    assert decision.high_risk is True


def test_medium_risk_respects_session_allow():
    """常规变更操作（非高危）会话级允许后不再拦截。"""
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    checker.sync_sandbox_restrictions(_sandbox_settings())
    checker.allow_sandbox_path_for_session("/etc/x")
    decision = checker.evaluate("bash", is_read_only=False, command="touch /etc/x", file_path="/etc/x")
    assert decision.allowed is True
    assert decision.high_risk is False


# --- auto 与 yolo 在有无沙箱时的区别 ---


def test_auto_always_blocks_high_risk():
    """auto 始终受沙箱约束：即使未 sync 沙箱限制，高危操作（rm）也需确认。"""
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    # 未 sync_sandbox_restrictions 也不影响：auto 永远拦高危
    decision = checker.evaluate("bash", is_read_only=False, command="rm -rf /etc/x")
    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.high_risk is True


def test_auto_with_sandbox_blocks_high_risk():
    """有沙箱时 auto 拦高危：沙箱允许的路径上执行 rm 仍需确认。"""
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    checker.sync_sandbox_restrictions(_sandbox_settings())
    # /tmp 不在 deny_write 内，未被沙箱拦截，但高危操作应要求确认
    decision = checker.evaluate("bash", is_read_only=False, command="rm -rf /tmp/x")
    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.high_risk is True
    assert decision.sandbox_blocked is False


# --- 命令级白名单（allowed_shell_commands） ---


def test_allowed_shell_commands_prefix_does_not_exempt_high_risk():
    """命令级白名单：仅前缀命中不豁免高危（配置 git push 不放行 git push --force）。"""
    settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_shell_commands=["git push"],
    )
    checker = PermissionChecker(settings)
    # git push 单独非高危，配置它不豁免高危子命令 git push --force
    decision = checker.evaluate("bash", is_read_only=False, command="git push --force origin main")
    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.high_risk is True


def test_allowed_shell_commands_full_high_risk_releases():
    """命令级白名单：配置完整高危命令头（git push --force）时允许自动放行。"""
    settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_shell_commands=["git push --force"],
    )
    checker = PermissionChecker(settings)
    decision = checker.evaluate("bash", is_read_only=False, command="git push --force origin main")
    assert decision.allowed is True


def test_allowed_shell_commands_rm_prefix_does_not_release():
    """命令级白名单：配置 rm 前缀不豁免 rm -rf（rm 单独非高危模式）。"""
    settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_shell_commands=["rm"],
    )
    checker = PermissionChecker(settings)
    decision = checker.evaluate("bash", is_read_only=False, command="rm -rf build")
    assert decision.allowed is False
    assert decision.requires_confirmation is True


def test_allowed_shell_commands_full_rm_rf_releases():
    """命令级白名单：配置完整 rm -rf 命令头时允许自动放行。"""
    settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_shell_commands=["rm -rf"],
    )
    checker = PermissionChecker(settings)
    decision = checker.evaluate("bash", is_read_only=False, command="rm -rf build")
    assert decision.allowed is True


def test_allowed_shell_commands_allows_non_high_risk():
    """命令级白名单：命中前缀且非高危（git push origin main 默认 MEDIUM）直接放行。"""
    settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_shell_commands=["git push"],
    )
    checker = PermissionChecker(settings)
    decision = checker.evaluate("bash", is_read_only=False, command="git push origin main")
    assert decision.allowed is True


def test_allowed_shell_commands_powershell_non_high_risk():
    """命令级白名单对 powershell 生效；非高危命令（Write-Output）放行。"""
    settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_shell_commands=["Write-Output"],
    )
    checker = PermissionChecker(settings)
    decision = checker.evaluate("powershell", is_read_only=False, command="Write-Output hello")
    assert decision.allowed is True


def test_allowed_shell_commands_powershell_high_risk_releases():
    """命令级白名单对 powershell 生效：Remove-Item 本身即高危模式，配置后放行其删除。"""
    settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_shell_commands=["Remove-Item"],
    )
    checker = PermissionChecker(settings)
    decision = checker.evaluate("powershell", is_read_only=False, command="Remove-Item -Recurse build")
    assert decision.allowed is True


def test_allowed_shell_commands_word_boundary():
    """命令级白名单按词边界匹配，避免 `git` 误匹配 `gitleaks`。"""
    assert PermissionChecker._command_matches_allowlist("git status", ["git"]) is True
    assert PermissionChecker._command_matches_allowlist("gitleaks scan", ["git"]) is False
    assert PermissionChecker._command_matches_allowlist("ls -la", ["ls"]) is True


# --- path_rules parsing tests ---


def _settings_with_rules(*rules) -> PermissionSettings:
    """Build a PermissionSettings with the given path_rule objects bypassing validation."""
    return PermissionSettings.model_construct(
        mode=PermissionMode.FULL_AUTO,
        allowed_tools=[],
        denied_tools=[],
        denied_commands=[],
        path_rules=list(rules),
    )


@pytest.mark.parametrize(
    "bad_rule",
    [
        PathRuleConfig.model_construct(allow=False),                  # pattern attribute missing
        PathRuleConfig.model_construct(pattern="", allow=False),      # pattern empty string
        PathRuleConfig.model_construct(pattern="   ", allow=False),   # pattern whitespace-only
        PathRuleConfig.model_construct(pattern=42, allow=False),      # pattern non-string
        PathRuleConfig.model_construct(pattern=None, allow=False),    # pattern None
    ],
    ids=["missing", "empty", "whitespace-only", "non-string", "none"],
)
def test_invalid_pattern_rule_is_skipped_and_warns(bad_rule, caplog):
    """Rules with missing, empty, or non-string patterns are skipped with a warning."""
    settings = _settings_with_rules(bad_rule)
    with caplog.at_level(logging.WARNING, logger="illusion_forge.permissions.checker"):
        checker = PermissionChecker(settings)

    assert checker._path_rules == []
    assert "跳过路径规则" in caplog.text


def test_valid_deny_rule_blocks_matching_path():
    """A valid deny rule prevents access to a matching file path."""
    rule = PathRuleConfig(pattern="/etc/*", allow=False)
    settings = _settings_with_rules(rule)
    checker = PermissionChecker(settings)

    decision = checker.evaluate("read_file", is_read_only=True, file_path="/etc/passwd")
    assert decision.allowed is False
    assert "/etc/passwd" in decision.reason


def test_valid_deny_rule_does_not_block_non_matching_path():
    """A deny rule does not affect paths that don't match the pattern."""
    rule = PathRuleConfig(pattern="/etc/*", allow=False)
    settings = _settings_with_rules(rule)
    checker = PermissionChecker(settings)

    decision = checker.evaluate("read_file", is_read_only=True, file_path="/home/user/file.txt")
    assert decision.allowed is True


def test_valid_allow_rule_is_added():
    """A rule with allow=True is accepted and stored without warnings."""
    rule = PathRuleConfig(pattern="/data/*", allow=True)
    settings = _settings_with_rules(rule)
    checker = PermissionChecker(settings)

    assert len(checker._path_rules) == 1
    assert checker._path_rules[0].pattern == "/data/*"
    assert checker._path_rules[0].allow is True


def test_pattern_with_surrounding_whitespace_is_stripped():
    """A pattern with leading/trailing whitespace is accepted with whitespace stripped."""
    rule = PathRuleConfig.model_construct(pattern="  /etc/*  ", allow=False)
    settings = _settings_with_rules(rule)
    checker = PermissionChecker(settings)

    assert len(checker._path_rules) == 1
    assert checker._path_rules[0].pattern == "/etc/*"

    decision = checker.evaluate("read_file", is_read_only=True, file_path="/etc/passwd")
    assert decision.allowed is False
