/**
 * @fileoverview CAD 工作台设置页签
 *
 * 自包含数据加载（与 CronTab/AgentsTab 同模式）：读取 GET /api/settings
 * 的 workbench 区块回显，修改即时 PATCH /api/settings/workbench 落盘。
 * 附带环境健康摘要（SolidWorks 探测/依赖可用性，health 接口经
 * cad_health_check 工具同源的本地探测逻辑在前端只展示设置侧事实）。
 *
 * enabled 开关只影响"新会话"的 agent 工具注册；画布视图本身不受限。
 */

import { useCallback, useEffect, useState } from 'react';
import { settingsApi } from '../api';
import { t, type UiLanguage } from '../i18n';
import ToggleSwitch from './ToggleSwitch';
import type { WorkbenchSettingsPayload } from '../types/canvas';

interface WorkbenchTabProps {
  lang: UiLanguage;
}

export function WorkbenchTab({ lang }: WorkbenchTabProps) {
  const [config, setConfig] = useState<WorkbenchSettingsPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    settingsApi.get().then((s) => {
      if (!cancelled && s.workbench) setConfig(s.workbench);
      else if (!cancelled) setLoadError(t(lang, 'workbench:notConfigured'));
    }).catch((exc: unknown) => {
      if (!cancelled) setLoadError(String(exc instanceof Error ? exc.message : exc));
    });
    return () => { cancelled = true; };
  }, [lang]);

  const patch = useCallback(async (payload: Partial<WorkbenchSettingsPayload>) => {
    setSaving(true);
    setSaveMessage(null);
    try {
      const result = await settingsApi.updateWorkbench(payload as Parameters<typeof settingsApi.updateWorkbench>[0]);
      setConfig((current) => (current ? { ...current, ...payload } : current));
      setSaveMessage(t(lang, 'workbench:saved'));
      void result;
    } catch (exc) {
      setSaveMessage(`${t(lang, 'workbench:saveFailed')}: ${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setSaving(false);
    }
  }, [lang]);

  if (loadError) {
    return <div className="text-sm text-danger py-4">{t(lang, 'workbench:loadFailed')}: {loadError}</div>;
  }
  if (!config) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-content-disabled">
        <svg className="w-4 h-4 animate-spin mr-2" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" strokeOpacity="0.4" />
          <path d="M14 8a6 6 0 0 0-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        {t(lang, 'setupFormSaving')}
      </div>
    );
  }

  const labelClass = 'block text-sm font-medium text-content-primary mb-2';
  const sectionClass = 'mb-6';

  return (
    <div className="max-w-xl">
      {/* 启用状态说明：仅由侧栏「对话流 | 工作台」分段按钮控制，此处只读展示 */}
      <div className={sectionClass}>
        <div className="flex items-center justify-between mb-1">
          <span className={labelClass}>{t(lang, 'workbench:enable')}</span>
          <span className={`text-[11px] font-medium ${config.enabled ? 'text-primary' : 'text-content-disabled'}`}>
            {t(lang, config.enabled ? 'workbench:viewCanvas' : 'workbench:viewChat')}
          </span>
        </div>
        <p className="text-xs text-content-secondary leading-5">{t(lang, 'workbench:enableHint')}</p>
      </div>

      {/* 默认视图 */}
      <div className={sectionClass}>
        <span className={labelClass}>{t(lang, 'workbench:defaultView')}</span>
        <div className="flex gap-2">
          {(['chat', 'canvas'] as const).map((view) => (
            <button key={view} onClick={() => patch({ default_view: view })}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors cursor-pointer ${
                config.default_view === view
                  ? 'bg-primary text-white border-primary'
                  : 'bg-surface-card border-border-light text-content-secondary hover:bg-surface-hover'
              }`}>
              {t(lang, view === 'chat' ? 'workbench:viewChat' : 'workbench:viewCanvas')}
            </button>
          ))}
        </div>
        <p className="text-xs text-content-secondary leading-5 mt-1">{t(lang, 'workbench:defaultViewHint')}</p>
      </div>

      {/* 无头 OCCT（讨论期 3D 预览的 STEP/IGES 交换格式开关） */}
      <div className={sectionClass}>
        <div className="flex items-center justify-between mb-1">
          <span className={labelClass}>{t(lang, 'workbench:headlessOcct')}</span>
          <ToggleSwitch checked={config.headless_occt} onChange={(v) => patch({ headless_occt: v })}
            label={t(lang, 'workbench:headlessOcct')} />
        </div>
        <p className="text-xs text-content-secondary leading-5">{t(lang, 'workbench:headlessOcctHint')}</p>
      </div>

      {/* 产物目录（只读展示，M3 支持自定义） */}
      <div className={sectionClass}>
        <span className={labelClass}>{t(lang, 'workbench:artifactsDir')}</span>
        <p className="text-xs text-content-secondary font-mono bg-surface-hover/50 rounded-lg px-3 py-2 break-all">
          {config.artifacts_dir || t(lang, 'workbench:artifactsDirDefault')}
        </p>
      </div>

      {/* 保存反馈 */}
      {saving && <p className="text-xs text-content-disabled">{t(lang, 'setupFormSaving')}</p>}
      {!saving && saveMessage && <p className="text-xs text-content-secondary">{saveMessage}</p>}
    </div>
  );
}
