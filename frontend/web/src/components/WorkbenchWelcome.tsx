/**
 * @fileoverview 工作台专属欢迎屏（对话面板空会话态）
 *
 * 独立组件，不复用聊天欢迎屏：为 CAD 工作台定制的引导态——
 * 专属图标、标题、操作提示。渲染在对话面板 440px 宽度内自动居中。
 */

import { t, type UiLanguage } from '../i18n';

interface WorkbenchWelcomeProps {
  lang: UiLanguage;
}

export function WorkbenchWelcome({ lang }: WorkbenchWelcomeProps) {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto flex flex-col items-center justify-center px-8 py-8 text-center">
      {/* 专属标识 */}
      <img src="/icon.png" alt="" draggable={false}
        className="w-16 h-16 rounded-2xl select-none mb-4"
        style={{ filter: 'drop-shadow(0 3px 10px rgba(0, 0, 0, 0.19)) drop-shadow(0 14px 40px rgba(0, 0, 0, 0.36))' }} />
      <div className="text-base font-bold text-content-primary font-body mb-1.5">
        {t(lang, 'wb:welcomeTitle')}
      </div>

    </div>
  );
}
