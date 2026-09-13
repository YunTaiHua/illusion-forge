/**
 * @fileoverview CAD 工作台布局（工作台模式的完整结构）
 *
 *   ┌────────── 共享画布（flex-1 全宽）──────────┬──── 对话面板（460px）────┐
 *   │  [卡片画布]            [建模卡浮动右上角]  │ │  完整消息流（轮次/思考/  │
 *   │                                           │ │  工具气泡/rewind/fork） │
 *   └──────────────────────────────────────────────────────────┘ │  [输入框停靠底部]   │
 *                                                                 └────────────────────┘
 *
 * 对话面板承载完整聊天体验（App 构建的 ChatArea + composer 元素槽位）：
 * 轮次导航、思考过程、完整工具气泡、rewind/fork 全部可用——与普通聊天
 * 完全一致的交互，收进工作台右侧面板。
 *
 * App 只负责构建 chatArea / composer / goalBar 元素槽位并传入；本组件
 * 负责布局、建模卡折叠状态、画布挂载/聚焦时的文档重取（兜底 CLI 等跨
 * 进程修改 board.json 后 web 画布不同步的问题）。
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { t, type UiLanguage } from '../i18n';
import { CanvasWorkbench } from './canvas/CanvasWorkbench';
import { PreviewModal } from './canvas/PreviewModal';
import { CadLivePanel } from './CadLivePanel';
import { WorkbenchWelcome } from './WorkbenchWelcome';
import type { CanvasDoc, CadUpdatePayload } from '../types/canvas';

interface WorkbenchViewProps {
  lang: UiLanguage;
  /** 对话面板主体（App 构建的 ChatArea 元素槽位：轮次/思考/工具气泡/rewind/fork） */
  chatArea: ReactNode;
  /** 输入框 + 工具栏（App 构建的 composer 元素槽位，停靠对话面板底部） */
  composer: ReactNode;
  /** Goal 状态条（App 构建的元素槽位，位于输入框上方） */
  goalBar: ReactNode;
  /** 画布文档（cad_canvas_update 推送） */
  canvasDoc: CanvasDoc | null;
  /** 提交用户整板编辑 */
  onPushDoc: (doc: { nodes: CanvasDoc['nodes']; edges: CanvasDoc['edges'] }) => void;
  /** CAD 会话状态（cad_update 推送） */
  cadState: CadUpdatePayload | null;
  /** 把 SolidWorks 窗口置前 */
  onFocusSolidWorks: () => void;
  /** 返回对话布局 */
  onBackToChat: () => void;
  /** WS 连接状态 */
  connected: boolean;
  /** 对话面板空会话：渲染工作台专属欢迎屏 */
  conversationEmpty: boolean;
  /** 重取画布文档（web_canvas_get）：挂载 / 窗口聚焦时触发 */
  onRefreshCanvas: () => void;
  /** cad_connect 工具启动计数（浮动卡自动展开信号） */
  cadConnectTick: number;
}

/** 对话面板固定宽度（完整聊天体验所需最小宽度） */
const CONV_PANEL_WIDTH = 460;

export function WorkbenchView({
  lang, chatArea, composer, goalBar, canvasDoc, onPushDoc,
  cadState, onFocusSolidWorks, onBackToChat, connected, onRefreshCanvas,
  cadConnectTick, conversationEmpty,
}: WorkbenchViewProps) {
  // 建模实时浮动卡：默认折叠，cad_connect 时自动展开
  const [modelCardOpen, setModelCardOpen] = useState(false);
  // 3D 预览大视口：双击预览卡/放大钮展开（目标节点 ID；节点被删时自动关闭）
  const [expandedPreviewId, setExpandedPreviewId] = useState<string | null>(null);
  const handleExpandPreview = useCallback((id: string) => setExpandedPreviewId(id), []);
  const handleClosePreview = useCallback(() => setExpandedPreviewId(null), []);
  // 由画布文档解析目标节点的标题与 GLB 路径（节点随文档同步，删除即关闭）
  const expandedPreview = useMemo(() => {
    if (!expandedPreviewId || !canvasDoc) return null;
    const node = canvasDoc.nodes.find((n) => n.id === expandedPreviewId);
    const glbPath = typeof node?.data?.glb_path === 'string' ? node.data.glb_path : '';
    if (!node || !glbPath) return null;
    return { title: node.title || t(lang, 'canvas:untitled'), glbPath };
  }, [expandedPreviewId, canvasDoc, lang]);

  // 跨进程同步：挂载、窗口重新聚焦时重取画布文档——CLI 会话或外部工具
  // 对 board.json 的修改没有进程内广播，靠这里兜底拉取
  useEffect(() => {
    onRefreshCanvas();
    const onFocus = () => onRefreshCanvas();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      {/* 共享画布（全宽，无遮挡） */}
      <div className="relative flex-1 min-h-0 min-w-0 flex flex-col">
        <CanvasWorkbench lang={lang} doc={canvasDoc}
          onPushDoc={onPushDoc}
          onBackToChat={onBackToChat}
          connected={connected}
          onRefresh={onRefreshCanvas}
          onExpandPreview={handleExpandPreview} />

        {/* 3D 预览大视口交互弹窗（双击预览卡/放大钮展开） */}
        {expandedPreview && (
          <PreviewModal lang={lang} title={expandedPreview.title}
            glbPath={expandedPreview.glbPath} onClose={handleClosePreview} />
        )}

        {/* 建模实时浮动卡（默认折叠在右上角；cad_connect 时自动展开） */}
        <CadLivePanel lang={lang} cadState={cadState}
          onFocusSolidWorks={onFocusSolidWorks}
          open={modelCardOpen}
          onToggle={() => setModelCardOpen((v) => !v)}
          autoOpenTick={cadConnectTick} />
      </div>

      {/* 对话面板：完整聊天体验（消息流 + 底部输入框） */}
      {/* data-dropdown-boundary / wb-conversation-card：工作台窄卡限定标记——
          Toolbar 下拉据此自适应翻转限宽、CSS 据此强制长内联代码断行；chat 模式无这些标记，行为不变 */}
      <aside data-dropdown-boundary
        className="wb-conversation-card panel-card panel-card-right-stack relative flex flex-col h-full shrink-0 select-none"
        style={{ width: `${CONV_PANEL_WIDTH}px` }}>
        {/* 标题行 */}
        <div className="grid grid-cols-3 items-center px-5 pt-4 pb-3 shrink-0">
          <span />
          <span className="justify-self-center font-body font-bold text-content-primary text-sm tracking-wider">
            {t(lang, 'canvas:convTitle')}
          </span>
          <span />
        </div>
        {conversationEmpty ? (
          /* 工作台专属欢迎屏（独立组件，不复用聊天欢迎屏） */
          <WorkbenchWelcome lang={lang} />
        ) : (
          /* 完整对话区：轮次导航 + 完整气泡（思考/工具/rewind/fork）+ 回复流 */
          <div className="flex-1 min-h-0 flex">
            {chatArea}
          </div>
        )}
        {/* 输入框停靠底部 */}
        <div className="shrink-0 px-3 pb-3 flex flex-col gap-1.5 min-w-0">
          {goalBar}
          {composer}
        </div>
      </aside>
    </>
  );
}
