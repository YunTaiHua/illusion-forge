"""CAD 工作台子系统。

可选附加功能：把 SolidWorks 自动化能力以"讨论画布 + 建模可视化"的
形态接入 IllusionForge。所有 CAD 逻辑来自 vendored 的
solidworks-automation-skill 无头模块（ illusion_forge.cad.vendor ），本包只提供
适配层：

    - glb_writer     三角面片 → 二进制 GLB（讨论期 3D 预览，零原生依赖）
    - canvas_store   画布文档存储（节点/边 CRUD、持久化、变更广播）
    - preview        友善参数 → NeutralCadDocument → 无头导出适配
    - health         环境健康检查（SolidWorks 探测/依赖报告）
    - tools          注册进 ToolRegistry 的 cad_*/canvas_* 工具

启用开关：会话类型（工作台会话的引擎构建时注册 CAD 工具域）。
"""

from illusion_forge.cad.canvas_store import CanvasStore

__all__ = ["CanvasStore"]
