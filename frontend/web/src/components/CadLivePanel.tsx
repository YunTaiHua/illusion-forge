/**
 * @fileoverview SolidWorks 建模实时浮动卡（工作台模式）
 *
 * 默认折叠为右上角小浮动卡；cad_connect 工具调用时自动展开（autoOpenTick）。
 * 展开后为带 tab 顶栏的小卡片：实时视口 / 特征树 / 快照历史，浮动在画布
 * 右上角——不占画布布局宽度，也不挤压输入框。数据源：cad_update 事件。
 */

import { useEffect, useMemo, useState } from 'react';
import { t, type UiLanguage } from '../i18n';
import { WbModelingIcon, WbSnapshotsIcon, WbTreeIcon, WbViewportIcon } from './canvas/workbenchIcons';
import { artifactUrl, type CadUpdatePayload } from '../types/canvas';

interface CadLivePanelProps {
  lang: UiLanguage;
  /** cad_update 载荷（null = 尚无数据） */
  cadState: CadUpdatePayload | null;
  /** 把 SolidWorks 窗口置前 */
  onFocusSolidWorks: () => void;
  /** 展开状态（受控：默认折叠，cad_connect 时自动展开） */
  open: boolean;
  onToggle: () => void;
  /** cad_connect 启动计数：>0 时自动展开一次 */
  autoOpenTick: number;
}

type Tab = 'viewport' | 'features' | 'snapshots';

export function CadLivePanel({ lang, cadState, onFocusSolidWorks, open, onToggle, autoOpenTick }: CadLivePanelProps) {
  const connected = cadState?.state.connected ?? false;
  const busyLabel = cadState?.state.busy_label ?? null;
  const document = cadState?.document ?? null;
  const tree = useMemo(() => cadState?.tree ?? [], [cadState?.tree]);
  const latestFrame = cadState?.latest_frame ?? null;
  const recent = cadState?.recent_snapshots ?? [];
  const [tab, setTab] = useState<Tab>('viewport');

  // cad_connect 调用 → 自动展开（父级 open 受控，onToggle 通知切换）
  useEffect(() => {
    if (autoOpenTick > 0 && !open) onToggle?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpenTick]);

  // 折叠态：右上角小浮动卡
  if (!open) {
    return (
      <div className="absolute top-3 right-3 z-20 select-none">
        <button
          onClick={onToggle}
          title={t(lang, 'cad:panelTitle')}
          className="flex items-center gap-2 rounded-xl border border-border-medium bg-surface-card
            px-3 py-2 shadow-card text-xs text-content-secondary
            hover:text-content-primary hover:shadow-lg transition-all cursor-pointer"
        >
          <WbModelingIcon className="w-4 h-4 text-primary" />
          <span className="font-medium">{t(lang, 'cad:panelTitle')}</span>
          <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400' : 'bg-zinc-400 dark:bg-zinc-600'}`} />
        </button>
      </div>
    );
  }

  // 展开态：右上角浮动小卡（tab 顶栏）
  return (
    <div className="absolute top-3 right-3 z-20 w-[300px] max-h-[75%] select-none flex flex-col
      rounded-xl border border-border-light bg-surface-card shadow-card overflow-hidden">
      {/* 标题行：状态 + 置前 + 折叠 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border-light shrink-0">
        <WbModelingIcon className="w-4 h-4 text-primary shrink-0" />
        <span className="text-xs font-bold text-content-primary truncate">{t(lang, 'cad:panelTitle')}</span>
        <div className="flex-1" />
        <button
          onClick={connected ? onFocusSolidWorks : undefined}
          disabled={!connected}
          title={t(lang, 'cad:focusHint')}
          className="w-6 h-6 flex items-center justify-center rounded-md text-content-secondary
            hover:text-primary hover:bg-surface-hover transition-colors cursor-pointer disabled:opacity-40"
        >
          <WbViewportIcon className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={onToggle}
          title={t(lang, 'cad:collapse')}
          className="w-6 h-6 flex items-center justify-center rounded-md text-content-secondary
            hover:text-content-primary hover:bg-surface-hover transition-colors cursor-pointer"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
            <path d="M2 5h6M4.5 2.5L2 5l2.5 2.5" />
          </svg>
        </button>
      </div>

      {/* 会话状态（常驻） */}
      <div className="px-3 py-2 space-y-1 border-b border-border-light shrink-0">
        <div className="flex items-center gap-1.5 text-[11px]">
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${connected ? 'bg-emerald-400' : 'bg-zinc-400 dark:bg-zinc-600'}`} />
          <span className="text-content-secondary">
            {connected ? t(lang, 'cad:sessionConnected') : t(lang, 'cad:sessionDisconnected')}
          </span>
          {busyLabel && (
            <span className="text-[10px] px-1 rounded bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300">
              {busyLabel}
            </span>
          )}
        </div>
        {document && (
          <div className="text-[10px] text-content-disabled truncate" title={document.path}>
            {document.title} · {document.doc_type || document.type}
          </div>
        )}
        {cadState?.selection && cadState.selection.count > 0 && (
          <div className="text-[10px] text-sky-600 dark:text-sky-300 truncate">
            {t(lang, 'cad:selectionLabel')}: {cadState.selection.items.slice(0, 2)
              .map((item) => item.type + (item.component ? `@${item.component}` : '')).join(', ')}
          </div>
        )}
      </div>

      {/* tab 顶栏 */}
      <div className="flex shrink-0 border-b border-border-light">
        {([
          { key: 'viewport', label: t(lang, 'cad:viewport'), icon: <WbViewportIcon className="w-3 h-3" /> },
          { key: 'features', label: t(lang, 'cad:featureTree'), icon: <WbTreeIcon className="w-3 h-3" /> },
          { key: 'snapshots', label: t(lang, 'cad:snapshots'), icon: <WbSnapshotsIcon className="w-3 h-3" /> },
        ] as const).map((item) => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            className={`flex items-center justify-center gap-1 flex-1 px-2 py-1.5 text-[11px] transition-colors cursor-pointer ${
              tab === item.key
                ? 'text-primary border-b-2 border-primary font-medium'
                : 'text-content-secondary hover:text-content-primary'
            }`}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </div>

      {/* tab 内容 */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2">
        {tab === 'viewport' && (
          latestFrame ? (
            <div className="relative rounded-lg overflow-hidden bg-surface-hover/40">
              <img src={artifactUrl(latestFrame.path)} alt={latestFrame.label}
                className="w-full h-auto object-contain" />
              <span className="absolute bottom-1.5 left-1.5 text-[10px] px-1.5 rounded bg-black/45 text-white">
                {latestFrame.view} · {latestFrame.created_at.slice(11)}
              </span>
            </div>
          ) : (
            <div className="h-[120px] flex items-center justify-center text-[11px] text-content-disabled">
              {t(lang, 'cad:noFrameYet')}
            </div>
          )
        )}
        {tab === 'features' && (
          tree.length === 0 ? (
            <div className="text-[11px] text-content-disabled py-2">{t(lang, 'cad:treeEmpty')}</div>
          ) : (
            <ul className="space-y-0.5">
              {tree.map((feature, index) => (
                <li key={`${feature.name}-${index}`}
                  className="flex items-center gap-1.5 text-[11px] leading-4 text-content-secondary">
                  <span className="w-1 h-1 rounded-full bg-border-strong shrink-0" />
                  <span className="truncate">{feature.name}</span>
                  <span className="ml-auto shrink-0 text-[9px] text-content-disabled">{feature.type}</span>
                </li>
              ))}
            </ul>
          )
        )}
        {tab === 'snapshots' && (
          recent.length === 0 ? (
            <div className="text-[11px] text-content-disabled py-2">{t(lang, 'cad:noFrameYet')}</div>
          ) : (
            <div className="grid grid-cols-2 gap-1.5">
              {recent.slice(0, 8).map((frame) => (
                <div key={frame.path} className="relative rounded-md overflow-hidden bg-surface-hover/40">
                  <img src={artifactUrl(frame.path)} alt={frame.label}
                    className="w-full h-auto max-h-[80px] object-contain" />
                  <span className="absolute bottom-0.5 left-0.5 text-[9px] px-1 rounded bg-black/45 text-white">
                    {frame.view}
                  </span>
                </div>
              ))}
            </div>
          )
        )}
      </div>
    </div>
  );
}
