"""
/init 命令实现
=============

完全重写的项目初始化命令，采用分层管道架构：

1. 提取阶段（extraction）：扫描文件、AST 分析、README 解析
2. 分析阶段（analysis）：规范检测、架构分析、依赖分类、关键模块识别
3. 生成阶段（generation）：CLAUDE.md、ILLUSION.md、rules/、MEMORY.md

使用示例：
    >>> from illusion_forge.commands.init import run_init
    >>> result = await run_init(context)
"""

from __future__ import annotations

from illusion_forge.commands.init.orchestrator import run_init

__all__ = ["run_init"]
