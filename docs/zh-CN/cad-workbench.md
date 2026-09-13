# CAD 画布工作台

> 中文 | [English](../en/cad-workbench.md)

结合 [solidworks-automation-skill](https://github.com/wzyn20051216/solidworks-automation-skill)（MIT License）的无头几何与 SolidWorks COM 自动化能力，IllusionForge 内置了一个"AI 漫剧"式的工程讨论工作台：**在共享画布上讨论方案 → 无头生成 3D 预览 → SolidWorks 实机建模实时可视化 → 选中项回流双向协作 → 方案与实机的血缘审计**。

## Table of Contents

- [总览](#总览)
- [启用与布局切换](#启用与布局切换)
- [两阶段工作流：讨论 → 实机](#两阶段工作流讨论--实机)
- [架构](#架构)
- [工具参考（51 个）](#工具参考51-个)
- [建模过程可视化](#建模过程可视化)
- [选中项回流（双向协作）](#选中项回流双向协作)
- [方案卡 ↔ 实机血缘](#方案卡--实机血缘)
- [配置参考](#配置参考)
- [权限与安全](#权限与安全)
- [测试与验证](#测试与验证)
- [上游归属与同步](#上游归属与同步)
- [附录：实施与审查记录](#附录实施与审查记录)

---

## 总览

CAD 画布工作台是一个**可选附加功能**：`workbench.enabled` 关闭时不注册任何 CAD 工具、不导入 pywin32/OCP 等重依赖，平台行为与原来完全一致。画布视图本身不受开关限制，随时可以手动使用。

四个能力层：

| 里程碑 | 能力 | 说明 |
|--------|------|------|
| M1 讨论闭环 | 共享画布 + 无头 3D 预览 | React Flow 画布，方案分支卡 / 需求卡 / GLB 预览卡；不启动 SolidWorks 即可出 3D 预览 |
| M2 建模闭环 | SolidWorks 实机建模 + 过程可视化 | STA COM 会话宿主 + 24 个建模工具；快照流、镜像特征树、分镜卡 |
| M3 协作闭环 | 选中项回流 + 逃生舱 + 二期工具 | 用户在 SolidWorks 里的选中项自动进入 agent 上下文；`cad_python` 覆盖未封装 API |
| M4 深化 | 方案↔实机血缘 + 多文档 + 钣金/焊件 | 尺寸级设计意图 diff；文档切换自动失效文档级状态 |

---

## 启用与布局切换

侧栏底部是两键分段切换器（`对话流` | `工作台`）：

- 点击 **工作台**：切换为画布布局（React Flow 共享画布 + 右侧对话面板），并自动新建一个工作台类型的会话；同时写入 `workbench.enabled=true`、`default_view="canvas"`；
- 点击 **对话流**：切换为聊天布局，并自动新建一个聊天类型的会话；同时写入 `workbench.enabled=false`、`default_view="chat"`。

会话列表按类型分开：左侧会话列表只显示当前类型的会话（聊天会话列表不含工作台会话，反之亦然），两类会话可多开互不干扰。

`workbench.enabled` 只控制 **agent 工具域注册**（cad_* / canvas_* 工具），保存后**对新会话生效**——当前已启动的会话不受影响。也就是说，在对话模式下聊天时 agent 不会带着 CAD 工具；切到工作台模式后再开新会话，agent 即具备全部 CAD 能力。

Web 设置 → "CAD 工作台"页签只读展示启用状态，并支持配置 `default_view`、`artifacts_dir`、`headless_occt`、`visualization` 等项。设置表单中**不再有"启用 CAD 工作台"开关**——`workbench.enabled` 与 `default_view` 只由侧栏分段按钮写入。

工作台布局：

```
┌────────────────────────────────────────────┬────────────┐
│          React Flow 共享画布                 │ 对话面板    │
│  [需求卡][方案卡][3D预览卡][快照卡]           │ 顶部标题栏   │
│                                            │ 消息区      │
│  ┌─────────────┐                           │            │
│  │ 建模实时胶囊 │                           │ 底部输入框   │
│  │ (点击展开)   │                           │            │
│  └─────────────┘                           │            │
└────────────────────────────────────────────┴────────────┘
```

建模实时卡片**默认折叠**为画布右上角的小胶囊；调用 `cad_connect` 工具时自动展开为浮动小卡片（约 300px 宽，不占画布宽度、不挤压输入框）。卡片顶栏有三个页签：实时视口 / 特征树 / 快照历史。

工作台欢迎屏只有应用图标 + "开始你的设计"。

---

## 两阶段工作流：讨论 → 实机

**讨论期（不需要 SolidWorks）**：agent 在画布上为每个设计方向建立方案分支卡，用无头几何内核（盒体/圆柱组合）生成 GLB 预览卡钉上画布，用户旋转查看、对比淘汰。GLB 由纯 Python 网格写入器生成（零原生依赖）；安装 OCP 运行时后可额外产出 STEP/IGES 交换格式。

**实机期（需要 SolidWorks）**：方案确定后，agent 通过 `cad_connect` 附着（或启动）SolidWorks，把确认的设计翻译成特征操作序列执行。每步操作的画面实时流到工作台，关键帧自动钉上画布形成分镜。

---

## 架构

```
illusion-forge/
├── src/illusion/cad/
│   ├── vendor/             # 上游 13 个模块原样引入（MIT，可 diff 同步）
│   ├── host.py             # ★ STA COM 会话宿主：专用线程 + 串行任务队列
│   ├── events.py           # cad_update 事件广播
│   ├── canvas_store.py     # 画布文档真源（节点/边 CRUD + 持久化 + 广播）
│   ├── glb_writer.py       # 三角面片 → 二进制 GLB（零原生依赖）
│   ├── preview.py          # 友善参数 → NeutralCadDocument → 无头导出
│   ├── health.py           # 环境健康检查（winreg 探测，不依赖 pywin32）
│   ├── context.py          # 会话上下文注入（系统提示词段落）
│   └── tools/              # 工具注册：M1 基础 + M2 建模 + M3 协作 + M4 深化
├── src/illusion/ui/web/cad_routes.py   # 产物文件服务（受限路径 + 认证）
└── frontend/web/src/components/canvas/ # React Flow 画布 + 卡片渲染
```

**STA 宿主线程模型**（`host.py`）：SolidWorks COM 对象必须固定在创建它的单元中使用。宿主用一条专用线程（`pythoncom.CoInitialize()`）+ 串行任务队列收敛全部 COM 操作，工具侧只收发纯数据。关键语义：

- **超时**：COM 调用不可强杀，超时返回 `cad_busy` 错误码，任务继续后台执行，busy 状态经事件如实上报；
- **重启契约**：线程死亡重启时清空全部 COM 指针（`_sw`/Motion 槽位），后续任务得到明确的 `cad_not_connected` 而非悬挂指针；
- **文档身份**：`(GetTitle, GetPathName)` 二元组，文档切换自动失效 Motion Study 等文档级状态；
- **线程死亡防护**：任务后置载荷构建/广播异常绝不杀死线程（否则全部任务永久排队）。

---

## 工具参考（51 个）

`workbench.enabled` 时注册（工具总数 79 → CAD 域 51）。长度一律毫米、角度一律度（内部经 `mm()/deg()` 换算成米/弧度）。

### 画布与无头预览（M1，不需要 SolidWorks）

| 工具 | 说明 |
|------|------|
| `cad_health_check` | 环境健康报告（平台/SolidWorks 注册表探测/依赖） |
| `cad_preview_build` | 无头 3D 预览（box/cylinder 组合 → GLB/STEP），默认钉卡上画布 |
| `canvas_add_node` / `canvas_update_node` / `canvas_remove_node` | 画布卡片操作（requirement/variant/preview/snapshot/spec/note） |

### SolidWorks 建模（M2）

| 域 | 工具 |
|------|------|
| 会话 | `cad_connect` `cad_session_status` `cad_new_document` `cad_open_document` `cad_save_document` `cad_close_documents` |
| 零件 | `cad_sketch_add`（8 种原语合一）`cad_feature_extrude`（boss/cut/midplane）`cad_feature_revolve` `cad_feature_fillet` `cad_feature_chamfer` `cad_feature_pattern`（linear/circular）`cad_feature_shell` `cad_feature_mirror` `cad_feature_rib` `cad_hole_create`（4 种孔）`cad_dimension_update` |
| 装配 | `cad_component_add` `cad_mate_add`（coincident/distance）`cad_assembly_inspect`（组件+配合+干涉） |
| 可视化/审查/导出 | `cad_camera_direct`（10 视角）`cad_snapshot` `cad_review_run` `cad_export`（step/stl/iges/pdf/dxf） |

### 协作闭环（M3）

| 域 | 工具 |
|------|------|
| 逃生舱 | `cad_python`（宿主线程内执行任意 Python，预置 sw/model/vendored 模块命名空间） |
| 配置/属性 | `cad_config_inspect` `cad_config_activate` `cad_config_create` `cad_properties_set` |
| 交付 | `cad_bom_export`（UTF-8 CSV + SHA-256）`cad_pack_and_go` |
| Motion | `cad_motion_create` `cad_motion_add_motor` `cad_motion_calculate` `cad_motion_summary` |
| 外观/工程图 | `cad_appearance_set` `cad_drawing_generate`（GB/ISO 图框）`cad_drawing_export_pdf` `cad_drawing_inspect` |

### 深化（M4）

| 域 | 工具 |
|------|------|
| 血缘 | `cad_document_link` `cad_dimension_diff` |
| 多文档 | `cad_documents_list` `cad_document_activate` |
| 钣金/焊件 | `cad_sheet_metal_base_flange` `cad_sheet_metal_evidence` `cad_weldment_cut_list` |

---

## 建模过程可视化

每次 CAD 操作完成后，宿主构造 `{状态, 活动文档, 特征树, 最新快照帧, 用户选中项}` 载荷，经 STA 线程安全回环广播 `cad_update` WebSocket 事件：

- **实时视口**：快照帧为 960×600 BMP（`SaveBMP` 管线），存 `<工作区>/.illusion/cad_artifacts/snapshots/`，前端经 `/api/cad/artifact` 同源加载实时刷新；
- **镜像特征树**：面板侧边实时呈现 FeatureManager 结构；
- **分镜卡**：feature 类操作（拉伸/旋转/孔/阵列…）自动把快照钉上画布，形成操作叙事；
- **相机编排**：`cad_camera_direct` 在操作间切换标准视角，用户看到零件"在镜头下长出来"。

---

## 选中项回流（双向协作）

宿主线程在任务队列空闲间隙每 2 秒轮询活动文档与 `ISelectionMgr` 选中项，**变化才广播**。三条消费通路：

1. Web 实时面板显示"已选"徽章；
2. `cad_update` 事件携带 `selection` 字段；
3. **系统提示词注入**：每轮对话构建提示词时追加 `# SolidWorks Session` 段落（状态/文档/选中项）——用户选中一个面，agent 下一轮自动感知。注入只读宿主跨线程缓存，零 COM 调用、零阻塞。

---

## 方案卡 ↔ 实机血缘

- `cad_document_link(node_id)`：把活动文档绑定为方案卡的实机实现（写入 `model_path/model_title/linked_at`），并快照 `data.params` 为设计意图基线；方案卡渲染"已链接模型"徽章；
- `cad_dimension_diff(node_id)`：读回实机命名尺寸与基线逐项对比（match / mismatch+delta / missing）——方案演进与实机偏差的审计闭环。

---

## 配置参考

```jsonc
// ~/.illusion/settings.json
"workbench": {
  "enabled": false,        // 新会话注册 CAD 工具域；画布视图不受此限制
  "default_view": "chat",  // Web 端默认布局（chat | canvas）
  "artifacts_dir": null,   // 产物根目录；缺省 <工作区>/.illusion/cad_artifacts
  "headless_occt": true,   // OCP 可用时额外产出 STEP/IGES
  "visualization": {
    "live_stream": true,
    "interval_ms": 800,
    "jpeg_quality": 75,
    "camera_choreography": true
  }
}
```

---

## 权限与安全

- **风险分级**：只读工具（status/inspect/snapshot/review/camera）LOW 免确认；变更类（建模/保存/关闭/cad_python）MEDIUM 默认逐次确认。高频工具可经 `settings.permission.allowed_tools` 预放行；save/quit 类不建议放行，也可用 `denied_tools` 完全禁用 `cad_python`；
- **`cad_python` 能力边界**：拥有完整 Python builtins，能力上限等同平台 bash/powershell 工具（同受权限门禁）——刻意不做 builtins 裁剪，见工具 docstring；
- **产物文件服务**：`GET /api/cad/artifact` 只服务 artifacts 目录树内文件（`Path.resolve()` + `relative_to` 校验，symlink 指向树外会被拒绝），并受全局认证中间件保护；
- **画布数据**：文档真源在工作区本地（`.illusion/cad_artifacts/canvas/<会话ID>.json`），**按会话隔离**——每个会话一块独立画布，切换会话自动加载对应画布；扩展字段约定放在节点 `data` 字典内。

---

## 测试与验证

- **自动化回归**：`tests/cad/test_cad_workbench.py`（11 项：画布操作契约、宿主线程机制、重启契约、选中项轮询、血缘全流程、路由路径校验）；
- **真机冒烟**：`python scripts/cad_smoke_test.py [--keep]`——连接 → 新建零件 → 草图+拉伸+打孔 → 多视角快照 → cad_python 逃生舱 → 导出 STEP → 收尾。冷启动约 1-3 分钟。

---

## 上游归属与同步

`src/illusion/cad/vendor/` 下 20 个模块从 [wzyn20051216/solidworks-automation-skill](https://github.com/wzyn20051216/solidworks-automation-skill)（MIT License）原样引入：

- **无头几何（4）**：headless_cad_writer / headless_occt_service / dxf_preview_scene / cad_core_contracts
- **COM 基础（9）**：sw_preflight / cad_installation / sw_connect / sw_part / sw_assembly / sw_hole_features / sw_document_data / sw_review / sw_export
- **交付/动画/外观/工程图（5）**：sw_delivery / sw_motion / sw_appearance / sw_drawing / drawing_workflow
- **钣金/焊件（2）**：sw_sheet_metal / sw_weldment

vendored 文件仅做最小改动：文件头归属注记、import 指向本包、个别仓库路径引用。保持与上游逐字节可 diff，上游更新时可直接覆盖同步。

---

## 附录：实施与审查记录

实施分四批交付（M1 讨论闭环 → M2 建模闭环 → M3 协作闭环 → M4 深化），完成后经独立代码审查（0 Critical / 5 Important / 2 Minor），处置：

| 发现 | 处置 |
|------|------|
| Motion 槽位失效仅凭文档标题 | 已修复：文档身份改为 title+path 二元组 |
| 线程死亡重启残留 COM 指针 | 已修复：`_ensure_thread` 重启契约 |
| `cad_python` 完整 builtins | 接受为刻意设计并文档化（等同 bash 能力边界，同受权限门禁） |
| symlink 穿越产物服务 | 不成立：`resolve()` + `relative_to` 已正确缓解，已补测试 |
| 整板替换丢弃未知顶层字段 | 接受为严格契约并文档化（扩展走 `data`） |
| 缺自动化回归测试 | 已补充 `tests/cad/`（11 项） |
| `_snapshots` 跨线程读写 | 已加锁 |
