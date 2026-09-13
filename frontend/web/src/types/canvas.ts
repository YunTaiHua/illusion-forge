/**
 * @fileoverview CAD 画布工作台类型定义
 *
 * 与后端 illusion_forge.cad.canvas_store 的画布文档结构对齐
 * （web_canvas_get / cad_canvas_update 事件载荷）。
 */

/** 画布节点种类（与后端 NODE_KINDS 对齐） */
export type CanvasNodeKind = 'requirement' | 'variant' | 'preview' | 'snapshot' | 'spec' | 'note';

/** 画布节点（后端文档形态） */
export interface CanvasNode {
  id: string;
  kind: CanvasNodeKind;
  title: string;
  body: string;
  /** 扩展数据：preview 卡携带 glb_path / bounds；snapshot 卡携带 image_path */
  data: Record<string, unknown>;
  position: { x: number; y: number };
  created_at: string;
}

/** 画布连线 */
export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  label: string;
}

/** 画布文档（revision 单调递增，前端据此抑制回声） */
export interface CanvasDoc {
  version: number;
  revision: number;
  updated_at: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

/** CAD 工作台设置（GET /api/settings 返回的 workbench 区块） */
export interface WorkbenchSettingsPayload {
  enabled: boolean;
  default_view: string;
  artifacts_dir: string | null;
  headless_occt: boolean;
  visualization: {
    live_stream: boolean;
    interval_ms: number;
    jpeg_quality: number;
    camera_choreography: boolean;
  };
}

/** CAD 快照帧条目（BMP 文件，经 /api/cad/artifact 加载） */
export interface CadSnapshotFrame {
  path: string;
  view: string;
  label: string;
  created_at: string;
}

/** 用户在 SolidWorks 中的选中项摘要（宿主空闲轮询，变化才推送） */
export interface CadSelectionInfo {
  doc_title: string;
  count: number;
  items: { index: number; type: string; component: string }[];
}

/** cad_update 事件载荷（宿主每操作后广播：状态+文档+特征树+最新帧） */
export interface CadUpdatePayload {
  label: string;
  state: {
    connected: boolean;
    owned: boolean;
    busy_label: string | null;
    last_error: string | null;
    snapshot_count: number;
  };
  document: { title: string; path: string; type: string; doc_type: string } | null;
  tree: { name: string; type: string }[];
  latest_frame: CadSnapshotFrame | null;
  /** 用户选中项（M3 协作回流；selection_poll 时变化推送） */
  selection?: CadSelectionInfo | null;
  /** web_cad_status 轻量快照时携带 */
  recent_snapshots?: CadSnapshotFrame[];
}

/** 由画布文档构造 GLB 产物的同源 URL（经全局认证 cookie 保护） */
export function artifactUrl(path: string): string {
  return `/api/cad/artifact?path=${encodeURIComponent(path)}`;
}
