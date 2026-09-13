/**
 * @fileoverview 3D 预览大视口交互弹窗
 *
 * 与节点小卡的"非交互自动旋转"互补：弹窗内提供完整交互——拖拽旋转、
 * 滚轮缩放、右键平移（model-viewer 内建），外加 旋转暂停/继续、
 * 重置视角、关闭（ESC / 点击遮罩）。
 *
 * GLB 来源与节点小卡相同（/api/cad/artifact 同源地址，认证走 cookie）。
 */

import { useEffect, useRef, useState } from 'react';
import { t, type UiLanguage } from '../../i18n';
import { artifactUrl } from '../../types/canvas';

/** model-viewer 模块懒加载（与 WorkbenchNode 共享同一模块缓存） */
import { ensureModelViewer } from './WorkbenchNode';

interface PreviewModalProps {
  lang: UiLanguage;
  title: string;
  /** GLB 绝对路径（工作区内 artifacts） */
  glbPath: string;
  onClose: () => void;
}

/** model-viewer 的默认相机轨道（重置视角用，等轴测视角） */
const DEFAULT_ORBIT = '45deg 65deg auto';

export function PreviewModal({ lang, title, glbPath, onClose }: PreviewModalProps) {
  const viewerRef = useRef<any>(null);
  const [ready, setReady] = useState(false);
  const [rotating, setRotating] = useState(false);

  useEffect(() => {
    ensureModelViewer().then(() => setReady(true)).catch(() => setReady(false));
  }, []);

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const resetView = () => {
    const el = viewerRef.current;
    if (!el) return;
    el.cameraOrbit = DEFAULT_ORBIT;
    el.fieldOfView = 'auto';
    el.jumpCameraToGoal?.();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black/55 backdrop-blur-sm" />

      {/* 主体：glass 卡片 */}
      <div className="relative m-auto w-[min(960px,94vw)] h-[min(700px,88vh)] rounded-2xl overflow-hidden
        bg-surface-card border border-border-light shadow-card flex flex-col"
        onMouseDown={(e) => e.stopPropagation()}>
        {/* 标题行 */}
        <div className="grid grid-cols-3 items-center px-5 pt-3 pb-2 shrink-0">
          <span className="justify-self-start text-[11px] text-content-disabled">
            {t(lang, 'canvas:previewHint')}
          </span>
          <span className="justify-self-center font-body font-bold text-content-primary text-sm tracking-wider truncate max-w-[60%]">
            {title}
          </span>
          <div className="justify-self-end flex items-center gap-1.5">
            <button
              onClick={() => {
                const el = viewerRef.current;
                if (!el) return;
                el.autoRotate = !el.autoRotate;
                setRotating(!!el.autoRotate);
              }}
              title={t(lang, rotating ? 'canvas:pauseRotate' : 'canvas:resumeRotate')}
              className="px-2.5 py-1 rounded-md text-[11px] text-content-secondary hover:text-primary hover:bg-surface-hover transition-colors cursor-pointer"
            >
              {t(lang, rotating ? 'canvas:pauseRotate' : 'canvas:resumeRotate')}
            </button>
            <button
              onClick={resetView}
              title={t(lang, 'canvas:resetView')}
              className="px-2.5 py-1 rounded-md text-[11px] text-content-secondary hover:text-primary hover:bg-surface-hover transition-colors cursor-pointer"
            >
              {t(lang, 'canvas:resetView')}
            </button>
            <button onClick={onClose} title={t(lang, 'canvas:closePreview')}
              className="w-7 h-7 flex items-center justify-center rounded-lg text-content-secondary hover:text-content-primary hover:bg-surface-hover transition-colors cursor-pointer">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                <path d="M2 2l8 8M10 2l-8 8" />
              </svg>
            </button>
          </div>
        </div>

        {/* 视口 */}
        <div className="flex-1 min-h-0 mx-3 mb-3 rounded-xl overflow-hidden bg-surface-hover/60 relative">
          {ready ? (
            <model-viewer
              ref={viewerRef}
              src={artifactUrl(glbPath)}
              alt={title}
              camera-controls
              auto-rotate
              rotation-per-second="14deg"
              shadow-intensity="0.7"
              exposure="1.05"
              camera-orbit={DEFAULT_ORBIT}
              style={{ width: '100%', height: '100%' }}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-sm text-content-disabled">
              {t(lang, 'canvas:viewerLoading')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
