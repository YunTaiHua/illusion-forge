"""沙箱违规事件存储 — 内存环形缓冲区 + pub/sub 模式

提供沙箱违规事件的记录、查询和订阅功能。
用于监控沙箱运行时的违规行为（如文件写入被拒绝、网络访问被阻止等）。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SandboxViolation:
    """单条违规事件

    Attributes:
        line: 原始违规日志行
        command: 触发违规的命令
        encoded_command: base64 编码的命令（用于命令匹配）
        timestamp: 违规发生时间戳
    """
    line: str
    command: str
    encoded_command: str
    timestamp: float


class SandboxViolationStore:
    """违规事件存储，环形缓冲区 + pub/sub

    使用环形缓冲区存储最近的违规事件（默认最大 100 条），
    支持通过 subscribe() 实时监听新违规。

    Attributes:
        _violations: 违规事件列表（环形缓冲区）
        _total_count: 累计违规总数（不清零）
        _max_size: 缓冲区最大容量
        _listeners: 订阅者集合
    """

    def __init__(self, max_size: int = 100) -> None:
        self._violations: list[SandboxViolation] = []
        self._total_count: int = 0
        self._max_size: int = max_size
        self._listeners: set[Callable[[list[SandboxViolation]], None]] = set()

    def add_violation(self, violation: SandboxViolation) -> None:
        """添加一条违规事件，超出容量时丢弃最旧的"""
        self._violations.append(violation)
        self._total_count += 1
        if len(self._violations) > self._max_size:
            self._violations = self._violations[-self._max_size:]
        self._notify()

    def get_violations(self, limit: int | None = None) -> list[SandboxViolation]:
        """获取违规事件列表，可选限制返回数量"""
        if limit is None:
            return list(self._violations)
        return list(self._violations[-limit:])

    def get_count(self) -> int:
        """获取当前缓冲区中的违规数量"""
        return len(self._violations)

    def get_total_count(self) -> int:
        """获取累计违规总数（不清零）"""
        return self._total_count

    def get_violations_for_command(self, encoded_command: str) -> list[SandboxViolation]:
        """根据编码命令过滤违规事件"""
        return [v for v in self._violations if v.encoded_command == encoded_command]

    def clear(self) -> None:
        """清空缓冲区（不清零 total_count）"""
        self._violations.clear()

    def subscribe(self, listener: Callable[[list[SandboxViolation]], None]) -> Callable[[], None]:
        """订阅违规事件，立即推送当前状态，返回取消订阅函数"""
        self._listeners.add(listener)
        listener(list(self._violations))
        def unsubscribe() -> None:
            self._listeners.discard(listener)
        return unsubscribe

    def _notify(self) -> None:
        """通知所有订阅者"""
        snapshot = list(self._violations)
        for listener in self._listeners:
            listener(snapshot)
