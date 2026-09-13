/**
 * @fileoverview 画布工作台节点卡片
 *
 * 按 kind 渲染不同风格的卡片：需求（蓝）/ 方案分支（紫）/ 3D 预览
 * （内嵌 model-viewer）/ 截图 / 参数表 / 备注。preview 卡首次挂载时
 * 动态 import @google/model-viewer 注册自定义元素（按需加载 ~200KB）。
 */

import { useEffect, useMemo, useState } from 'react';
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import { t, type UiLanguage } from '../../i18n';
import { GitForkIcon, ListChecksIcon, PenIcon } from '../icons';
import { artifactUrl, type CanvasNode } from '../../types/canvas';

/** model-viewer 自定义元素的 JSX 声明（@types/react 18 全局 JSX 命名空间） */
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      'model-viewer': Record<string, unknown>;
    }
  }
}

/** model-viewer 模块加载状态（模块级缓存，首次加载后全局可用；PreviewModal 复用） */
let modelViewerLoading: Promise<unknown> | null = null;
export function ensureModelViewer(): Promise<unknown> {
  if (!modelViewerLoading) {
    modelViewerLoading = import('@google/model-viewer');
  }
  return modelViewerLoading;
}

/** 各节点类型：粉彩图标章（--pastel-* 令牌，深浅色自适应）+ 标签 */
interface KindTheme {
  chipBg: string;
  labelKey: string;
  icon: (className: string) => JSX.Element;
}

/** 各 kind 的字形（16px，stroke currentColor） */
const Glyph = {
  requirement: (c: string) => (
    <svg className={c} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 14V2.5" /><path d="M3 3h8.5l-1.8 2.75L11.5 8.5H3" />
    </svg>
  ),
  variant: (c: string) => <GitForkIcon className={c} />,
  preview: (c: string) => (
    <svg className={c} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 1.5l5.5 3v6L8 14.5l-5.5-4v-6L8 1.5z" /><path d="M2.5 4.5L8 7.5l5.5-3M8 7.5v7" />
    </svg>
  ),
  snapshot: (c: string) => (
    <svg className={c} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1.5 5.5A1.5 1.5 0 013 4h1.5l1-1.5h5L11.5 4H13a1.5 1.5 0 011.5 1.5v6A1.5 1.5 0 0113 13H3a1.5 1.5 0 01-1.5-1.5v-6z" />
      <circle cx="8" cy="8" r="2.5" />
    </svg>
  ),
  spec: (c: string) => <ListChecksIcon className={c} />,
  note: (c: string) => <PenIcon className={c} />,
} as const;

const NOTE_THEME: KindTheme = {
  chipBg: 'var(--bg-hover)',
  labelKey: 'canvas:kind.note',
  icon: Glyph.note,
};

const KIND_THEME: Record<string, KindTheme> = {
  requirement: { chipBg: 'var(--pastel-sky)', labelKey: 'canvas:kind.requirement', icon: Glyph.requirement },
  variant: { chipBg: 'var(--pastel-lilac)', labelKey: 'canvas:kind.variant', icon: Glyph.variant },
  preview: { chipBg: 'var(--pastel-mint)', labelKey: 'canvas:kind.preview', icon: Glyph.preview },
  snapshot: { chipBg: 'var(--pastel-coral)', labelKey: 'canvas:kind.snapshot', icon: Glyph.snapshot },
  spec: { chipBg: 'var(--pastel-cream)', labelKey: 'canvas:kind.spec', icon: Glyph.spec },
  note: NOTE_THEME,
};

/** React Flow 节点数据：CanvasNode（映射类型，满足 RF 的 Record 约束）+ 渲染语言 + 引用回调 */
export type WorkbenchNodeData = { [K in keyof CanvasNode]: CanvasNode[K] } & {
  renderLang: UiLanguage;
  onReference?: (id: string, title: string) => void;
  /** 双击/放大钮：展开大视口交互预览 */
  onExpand?: (id: string) => void;
};

export type WorkbenchFlowNode = Node<WorkbenchNodeData, 'workbench'>;

export function WorkbenchNode({ data, selected }: NodeProps<WorkbenchFlowNode>) {
  const lang = data.renderLang;
  const theme = KIND_THEME[data.kind] ?? NOTE_THEME;
  const glbPath = typeof data.data?.glb_path === 'string' ? data.data.glb_path : '';
  const imagePath = typeof data.data?.image_path === 'string' ? data.data.image_path : '';
  const [viewerReady, setViewerReady] = useState(false);

  useEffect(() => {
    if (data.kind === 'preview' && glbPath) {
      ensureModelViewer().then(() => setViewerReady(true)).catch(() => setViewerReady(false));
    }
  }, [data.kind, glbPath]);

  const bounds = useMemo(() => {
    const b = data.data?.bounds as { min?: number[]; max?: number[] } | undefined;
    if (!b?.min || !b?.max) return null;
    const dx = Math.max(0.01, (b.max[0] ?? 0) - (b.min[0] ?? 0));
    const dy = Math.max(0.01, (b.max[1] ?? 0) - (b.min[1] ?? 0));
    const dz = Math.max(0.01, (b.max[2] ?? 0) - (b.min[2] ?? 0));
    return `${dx.toFixed(0)} × ${dy.toFixed(0)} × ${dz.toFixed(0)}`;
  }, [data.data]);

  return (
    <div className={`group w-[320px] rounded-2xl bg-surface-card border transition-all
      ${selected ? 'border-primary ring-2 ring-primary/25' : 'border-border-light hover:border-border-medium hover:shadow-lg'}`}
      style={{ boxShadow: undefined }}>
      {/* 连接桩：小而低调，hover 卡片时浮现 */}
      <Handle type="target" position={Position.Left} className="!w-1.5 !h-1.5 !bg-border-strong !-ml-0.5 opacity-0 group-hover:opacity-100 !transition-opacity" />
      <Handle type="source" position={Position.Right} className="!w-1.5 !h-1.5 !bg-border-strong !-mr-0.5 opacity-0 group-hover:opacity-100 !transition-opacity" />

      <div className="p-4">
        {/* 类型章 + 标签 */}
        <div className="flex items-center gap-2.5 mb-2">
          <span className="w-8 h-8 rounded-lg flex items-center justify-center text-content-primary shrink-0"
            style={{ background: theme.chipBg }}>
            {theme.icon('w-4 h-4')}
          </span>
          <span className="text-[11px] font-medium tracking-wide text-content-secondary">
            {t(lang, theme.labelKey)}
          </span>
          {data.kind === 'preview' && bounds && (
            <span className="ml-auto text-[10px] text-content-disabled">{bounds} mm</span>
          )}
        </div>

        {/* 标题 + hover 引用钮（点击把卡片引用插入输入框） */}
        <div className="flex items-start justify-between gap-2">
          <div className="text-[15px] font-semibold text-content-primary leading-snug break-words min-w-0">
            {data.title || t(lang, 'canvas:untitled')}
          </div>
          {data.onReference && (
            <button
              onClick={(e) => { e.stopPropagation(); data.onReference?.(data.id, data.title || data.kind); }}
              title={t(lang, 'canvas:referenceTooltip')}
              className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity px-1.5 py-0.5 rounded-md
                bg-primary-light text-primary text-[10px] cursor-pointer hover:bg-primary hover:text-white"
            >
              {t(lang, 'canvas:reference')}
            </button>
          )}
        </div>

        {/* 正文 */}
        {data.body && (
          <div className="mt-1.5 text-xs leading-[1.7] text-content-secondary whitespace-pre-wrap break-words">
            {data.body}
          </div>
        )}
      </div>

      {/* 3D 预览：小窗为非交互自动旋转（指针事件穿透给节点拖拽），双击/放大钮进交互模式 */}
      {data.kind === 'preview' && glbPath && (
        <div className="relative mx-4 mb-3 h-[176px] rounded-xl overflow-hidden bg-surface-hover/60">
          <div className="absolute inset-0 pointer-events-none">
            {viewerReady ? (
              <model-viewer
                src={artifactUrl(glbPath)}
                alt={data.title}
                auto-rotate
                rotation-per-second="10deg"
                shadow-intensity="0.6"
                exposure="1.05"
                style={{ width: '100%', height: '100%' }}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-xs text-content-disabled">
                {t(lang, 'canvas:viewerLoading')}
              </div>
            )}
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); data.onExpand?.(data.id); }}
            title={t(lang, 'canvas:expandPreview')}
            className="absolute top-1.5 right-1.5 w-6 h-6 flex items-center justify-center rounded-md
              bg-black/35 text-white opacity-0 group-hover:opacity-100 transition-opacity
              hover:bg-black/55 cursor-pointer pointer-events-auto"
          >
            <svg className="w-3 h-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <path d="M9.5 2h4.5v4.5M6.5 14H2V9.5M13.5 2L9 6.5M2.5 13.5L7 9" />
            </svg>
          </button>
          <span className="absolute bottom-1 left-1.5 text-[9px] text-content-disabled pointer-events-none">
            {t(lang, 'canvas:dblClickHint')}
          </span>
        </div>
      )}
      {data.kind === 'snapshot' && imagePath && (
        <img src={artifactUrl(imagePath)} alt={data.title}
          className="mx-4 mb-3 max-h-[180px] rounded-xl object-contain bg-surface-hover/60" />
      )}

      {/* 血缘页脚：方案卡绑定实机模型后显示（cad_document_link 写入） */}
      {typeof data.data?.model_title === 'string' && data.data.model_title && (
        <div className="px-4 py-2 border-t border-border-light flex items-center gap-1.5 text-[10px] text-content-disabled"
          title={String(data.data.model_path || '')}>
          <GitForkIcon className="w-3 h-3 shrink-0" />
          <span className="truncate">
            {t(lang, 'canvas:linkedModel')}: {String(data.data.model_title)}
            {typeof data.data?.linked_at === 'string' && ` · ${String(data.data.linked_at).slice(5, 16)}`}
          </span>
        </div>
      )}
    </div>
  );
}

export const workbenchNodeTypes = { workbench: WorkbenchNode };
