"""CAD 工作台 vendored 第三方模块。

以下模块从 wzyn20051216/solidworks-automation-skill（MIT License）原样引入，
仅调整 import 与仓库路径引用，其余保持原样以便跟随上游 diff 同步：

无头几何（不依赖 SolidWorks，讨论期使用）：
    - headless_cad_writer.py   无 CAD 软件时的开放格式写入器（STL/OBJ/DXF/SVG/PDF/PNG 原生实现）
    - headless_occt_service.py OCCT/OCP 隔离子进程（STEP/IGES/BREP/GLB）
    - dxf_preview_scene.py     DXF → 预览场景 JSON（依赖可选的 ezdxf）
    - cad_core_contracts.py    产物契约（sha256 / preview manifest）

SolidWorks COM 自动化（M2 建模闭环，仅在宿主 STA 线程内导入——
这些模块 import 时即初始化 pywin32）：
    - sw_preflight.py      COM 依赖自检与自动安装
    - cad_installation.py  SolidWorks 安装发现（sw_preflight 依赖）
    - sw_connect.py        COM 连接/文档生命周期/单位换算（GetActiveObject 附着优先）
    - sw_part.py           草图原语 + 拉伸/旋转/圆角/倒角/阵列/抽壳/镜像/筋
    - sw_assembly.py       组件添加 + 配合 + 干涉检查 + 特征树遍历
    - sw_hole_features.py  盲孔/通孔/沉孔/沉头孔/半圆槽/孔阵列
    - sw_document_data.py  命名尺寸修改 / 配置族 / 自定义属性
    - sw_review.py         多视角 BMP 预览（SaveBMP）/ 几何测量 / 审查报告
    - sw_export.py         STEP/STL/IGES/Parasolid/PDF/DXF 导出

SolidWorks COM 自动化（M3 二期：交付/动画/外观/工程图）：
    - sw_delivery.py       BOM CSV 导出 + Pack and Go
    - sw_motion.py         Motion Study（旋转马达/计算播放，需 swmotionstudy.tlb）
    - sw_appearance.py     文档/组件外观颜色
    - sw_drawing.py        工程图桥接（指向本包 drawing_workflow.py）
    - drawing_workflow.py  工程图子技能实现（自包含，仅标准库）

上游仓库：https://github.com/wzyn20051216/solidworks-automation-skill
"""
