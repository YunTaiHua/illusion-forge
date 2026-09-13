"""
IllusionForge 程序入口模块
========================

本模块作为 IllusionForge 的入口点，支持通过 `python -m illusion_forge` 运行。

使用示例：
    >>> python -m illusion_forge                    # 启动交互式会话
    >>> python -m illusion_forge -p "你的提示词"     # 非交互式打印模式
"""

from illusion_forge.cli import app  # 从 CLI 模块导入主应用程序

if __name__ == "__main__":  # 当直接运行此模块时执行主应用
    app()  # 启动 CLI 应用程序
