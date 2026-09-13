/**
 * @fileoverview CAD 画布工作台（React Flow 无限画布）
 *
 * AI 漫剧式工作台的 CAD 落地：左侧对话流继续走聊天布局，本组件
 * 占据主区域渲染共享画布——需求卡 / 方案分支卡 / 3D 预览卡 /
 * 快照卡 / 参数表 / 备注由 agent（canvas_* 工具）与用户共同编辑，
 * 文档真源在后端（.illusion/cad_artifacts/canvas/board.json），
 * 双向经 web_canvas_update / cad_canvas_update 同步（revision 抑制回声）。
 *
 * 与 agent 工具开关无关：settings.workbench.enabled 仅控制 agent
 * 侧工具注册，画布本身始终可用（可手动拖卡片、写备注）。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  type Edge,
  type NodeChange,
  type EdgeChange,
  type Connection,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { t, type UiLanguage } from '../../i18n';
import { workbenchNodeTypes, type WorkbenchFlowNode } from './WorkbenchNode';
import type { CanvasDoc } from '../../types/canvas';

interface CanvasWorkbenchProps {
  lang: UiLanguage;
  /** 后端画布文档（cad_canvas_update 推送 / web_canvas_get 拉取） */
  doc: CanvasDoc | null;
  /** 向后端提交整板编辑（前端 hook 发 web_canvas_update） */
  onPushDoc: (doc: { nodes: CanvasDoc['nodes']; edges: CanvasDoc['edges'] }) => void;
  /** 返回对话布局 */
  onBackToChat: () => void;
  /** 画布文档是否已加载（null = 尚未收到后端推送） */
  connected: boolean;
  /** 重取画布文档（挂载/窗口聚焦触发，兜底跨进程修改） */
  onRefresh?: () => void;
  /** 点击卡片"引用"钮：把引用文本插入输入框 */
  onReferenceCard?: (id: string, title: string) => void;
  /** 双击 3D 预览卡：展开大视口交互 */
  onExpandPreview?: (id: string) => void;
}

/** 后端文档节点 → React Flow 节点 */
function toFlowNodes(doc: CanvasDoc | null, lang: UiLanguage, onReference?: (id: string, title: string) => void, onExpand?: (id: string) => void): WorkbenchFlowNode[] {
  if (!doc) return [];
  return doc.nodes.map((node) => ({
    id: node.id,
    type: 'workbench' as const,
    position: node.position,
    data: { ...node, renderLang: lang, onReference, onExpand },
  }));
}

function toFlowEdges(doc: CanvasDoc | null): Edge[] {
  if (!doc) return [];
  return doc.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label || undefined,
    animated: false,
    style: { stroke: 'var(--border-strong, #b6bdc9)', strokeWidth: 1.2 },
  }));
}

/**
 * 构造"追加一张备注卡"后的画布文档（纯函数）。
 * 顶栏"添加卡片"与左栏折叠态按钮列的"添加卡片"共用此逻辑。
 */
export function buildAddNoteDoc(doc: CanvasDoc): { nodes: CanvasDoc['nodes']; edges: CanvasDoc['edges'] } {
  return {
    nodes: [
      ...doc.nodes,
      {
        id: `n_manual_${Date.now().toString(36)}`,
        kind: 'note',
        title: '',
        body: '',
        data: {},
        position: { x: 120 + (doc.nodes.length % 5) * 330, y: 60 + Math.floor(doc.nodes.length / 5) * 250 },
        created_at: new Date().toISOString().slice(0, 19),
      },
    ],
    edges: doc.edges,
  };
}

function CanvasWorkbenchInner({ lang, doc, onPushDoc, onBackToChat, connected, onRefresh, onReferenceCard, onExpandPreview }: CanvasWorkbenchProps) {
  // 本地受控视图：拖拽/连线时先改本地（流畅），落定后整板推送
  // 初始化即挂载回调（onReference/onExpand），保证首帧卡片的引用钮/放大钮可用
  const [nodes, setNodes] = useState<WorkbenchFlowNode[]>(() => toFlowNodes(doc, lang, onReferenceCard, onExpandPreview));
  const [edges, setEdges] = useState<Edge[]>(() => toFlowEdges(doc));
  const [interacting, setInteracting] = useState(false); // 拖拽中抑制回声应用
  const lastRevisionRef = useRef<number>(-1);
  const pushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 挂载时兜底重取（CLI 等跨进程修改 board.json 无进程内广播）
  const onRefreshRef = useRef(onRefresh);
  onRefreshRef.current = onRefresh;
  useEffect(() => { onRefreshRef.current?.(); }, []);

  // 后端文档到达/更新：非交互态才应用（拖拽中应用会打断手势）
  useEffect(() => {
    if (!doc) return;
    if (interacting) return;
    if (doc.revision === lastRevisionRef.current) return; // 自己推送的回声
    lastRevisionRef.current = doc.revision;
    setNodes(toFlowNodes(doc, lang, onReferenceCard, onExpandPreview));
    setEdges(toFlowEdges(doc));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, interacting, lang, onReferenceCard, onExpandPreview]);

  const schedulePush = useCallback((nextNodes: WorkbenchFlowNode[], nextEdges: Edge[]) => {
    if (pushTimerRef.current) clearTimeout(pushTimerRef.current);
    pushTimerRef.current = setTimeout(() => {
      // 剥离 React Flow 运行时字段（selected/dragging/dimensions 等），只回传文档字段
      onPushDoc({
        nodes: nextNodes.map((n) => ({
          id: n.id,
          kind: n.data.kind,
          title: n.data.title,
          body: n.data.body,
          data: n.data.data,
          position: { x: n.position.x, y: n.position.y },
          created_at: n.data.created_at,
        })),
        edges: nextEdges.map((e) => ({
          id: e.id, source: e.source, target: e.target,
          label: typeof e.label === 'string' ? e.label : '',
        })),
      });
    }, 350);
  }, [onPushDoc]);

  const handleNodeChanges = useCallback((changes: NodeChange<WorkbenchFlowNode>[]) => {
    setNodes((current) => {
      const next = applyNodeChanges(changes, current);
      const dragging = changes.some((c) => c.type === 'position' && c.dragging);
      const dropped = changes.some((c) => c.type === 'position' && c.dragging === false);
      if (dragging) setInteracting(true);
      // 拖拽落定 / 删除 / 选择性变更 → 推送整板
      if (dropped || changes.some((c) => c.type === 'remove')) {
        setInteracting(false);
        schedulePush(next, edges);
      }
      return next;
    });
  }, [edges, schedulePush]);

  const handleEdgeChanges = useCallback((changes: EdgeChange<Edge>[]) => {
    setEdges((current) => {
      const next = applyEdgeChanges(changes, current);
      if (changes.some((c) => c.type === 'remove' || c.type === 'select')) {
        if (changes.some((c) => c.type === 'remove')) schedulePush(nodes, next);
      }
      return next;
    });
  }, [nodes, schedulePush]);

  const handleConnect = useCallback((connection: Connection) => {
    setEdges((current) => {
      const next = addEdge({ ...connection, label: '' }, current);
      schedulePush(nodes, next);
      return next;
    });
  }, [nodes, schedulePush]);

  // 手动加备注卡（无坐标时由后端自动排布，position 传 undefined 后端兜底）
  const handleAddNote = useCallback(() => {
    if (doc) onPushDoc(buildAddNoteDoc(doc));
  }, [doc, onPushDoc]);

  const nodeCount = useMemo(() => nodes.length, [nodes]);

  return (
    <div className="relative flex-1 min-h-0 min-w-0">
      {/* 顶栏：单条玻璃胶囊居中（返回 | 标题·计数 | 添加卡片） */}
      <div className="canvas-topbar absolute top-3 left-3 z-10 pointer-events-none">
        <div className="flex items-center gap-1 glass-surface rounded-full px-2 py-1.5 shadow-card pointer-events-auto">
          <button
            onClick={onBackToChat}
            title={t(lang, 'canvas:backToChat')}
            className="flex items-center gap-1.5 px-3 py-1 rounded-full text-sm text-content-secondary hover:text-content-primary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <path d="M7.5 2L3.5 6l4 4" />
            </svg>
            {t(lang, 'canvas:backToChat')}
          </button>
          <span className="w-px h-4 bg-border-light" />
          <span className="px-2 text-xs text-content-disabled whitespace-nowrap">
            {t(lang, 'canvas:title')} · {nodeCount} {t(lang, 'canvas:nodeCount')}
          </span>
          <span className="w-px h-4 bg-border-light" />
          <button
            onClick={handleAddNote}
            className="px-3 py-1 rounded-full text-sm text-content-secondary hover:text-content-primary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            + {t(lang, 'canvas:addNote')}
          </button>
        </div>
      </div>

      {!connected && doc === null ? (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-content-disabled">
          {t(lang, 'canvas:loading')}
        </div>
      ) : (
        <>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={workbenchNodeTypes}
          onNodesChange={handleNodeChanges}
          onEdgesChange={handleEdgeChanges}
          onConnect={handleConnect}
          onNodeDragStop={() => setInteracting(false)}
          onNodeDoubleClick={(_, n) => { if (n.data.kind === 'preview') onExpandPreview?.(n.id); }}
          onPaneClick={() => setInteracting(false)}
          fitView
          fitViewOptions={{ padding: 0.25, maxZoom: 0.9 }}
          minZoom={0.15}
          deleteKeyCode={['Delete', 'Backspace']}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={26} size={1.1} />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
        
        </>
      )}
    </div>
  );
}

export function CanvasWorkbench(props: CanvasWorkbenchProps) {
  return (
    <ReactFlowProvider>
      <CanvasWorkbenchInner {...props} />
    </ReactFlowProvider>
  );
}
