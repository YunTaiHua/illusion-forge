"""
UI 模块
=======

本模块承载 IllusionForge 用户界面的后端侧支撑：

主要组件：
    - protocol: 前后端 WebSocket 事件/请求协议（FrontendRequest / BackendEvent）
    - runtime: 会话运行时装配（引擎构建、行处理、会话元数据）
    - file_mentions: @ 文件引用解析
    - headless: 无头（print）模式入口，供 cron 与脚本调用
    - headless_prompts: 无头模式非交互问答/审批回调
    - web: FastAPI + WebSocket 的 Web UI 服务端（桌面壳通过 `illusion-forge forge` 启动）
"""
