/**
 * 应用内图片预览组件（Lightbox）
 *
 * 全局挂载一次（App 根节点），监听 illusion:image-preview 事件。
 * 点击 markdown 图片/图片链接时在应用内全屏预览，无需跳转外部浏览器
 * （桌面端 Electron 不会被外链劫持、浏览器端无需新开标签）。
 * 提供三种退出方式：右上角关闭按钮、点击遮罩背景、Esc 键。
 *
 * @param props.lang - UI 语言
 */
import { useEffect, useState } from 'react';
import { t, type UiLanguage } from '../i18n';
import { IMAGE_PREVIEW_EVENT } from '../utils/imagePreview';

export default function ImagePreview({ lang }: { lang: UiLanguage }) {
  const [url, setUrl] = useState<string | null>(null);

  // 监听全局图片预览事件
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail;
      setUrl(typeof detail === 'string' && detail ? detail : null);
    };
    window.addEventListener(IMAGE_PREVIEW_EVENT, handler);
    return () => window.removeEventListener(IMAGE_PREVIEW_EVENT, handler);
  }, []);

  // Esc 键关闭
  useEffect(() => {
    if (!url) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setUrl(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [url]);

  if (!url) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75"
      onClick={() => setUrl(null)}
      role="dialog"
      aria-modal="true"
    >
      <img
        src={url}
        alt="preview"
        className="max-w-[92vw] max-h-[85vh] object-contain rounded-lg shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
      {/* 关闭按钮 */}
      <button
        onClick={() => setUrl(null)}
        className="absolute top-4 right-4 w-9 h-9 flex items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors cursor-pointer"
        title={t(lang, 'image_preview_close')}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </button>
      {/* 关闭方式提示 */}
      <span className="absolute bottom-4 left-1/2 -translate-x-1/2 text-xs text-white/60 pointer-events-none">
        {t(lang, 'image_preview_hint')}
      </span>
    </div>
  );
}
