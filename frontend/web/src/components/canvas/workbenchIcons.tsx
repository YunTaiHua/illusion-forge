/**
 * @fileoverview CAD 工作台专用图标集（线性风格）
 *
 * 全部为工作台定制的 16×16 线性 SVG：stroke 1.4、圆角线帽、几何对称。
 * 独立于聊天区 icons.tsx，修改互不影响。
 */

import type { ReactNode } from 'react';

const S = ({ children, className }: { children: ReactNode; className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor"
    strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    {children}
  </svg>
);

/** 工作台（画布陈列板）：圆角板面 + 双节点连线 */
export function WbBoardIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <rect x="2" y="2" width="12" height="12" rx="2.5" />
      <rect x="4.2" y="4.2" width="3" height="3" rx="0.8" />
      <rect x="8.8" y="8.8" width="3" height="3" rx="0.8" />
      <path d="M7.2 5.7h2.6a1 1 0 0 1 1 1v2.1" />
    </S>
  );
}

/** 对话模式：气泡 + 双线 */
export function WbChatIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <path d="M13.5 7.6a5.5 5.5 0 0 1-8 4.9L2.5 13.5l1.1-3A5.5 5.5 0 1 1 13.5 7.6z" />
      <path d="M5.5 6.3h5M5.5 8.3h3.2" />
    </S>
  );
}

/** 建模实时：等轴测立方体 */
export function WbModelingIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <path d="M8 1.6l5.4 3v6.8L8 14.4l-5.4-3V4.6l5.4-3z" />
      <path d="M2.6 4.6L8 7.6l5.4-3" />
      <path d="M8 7.6v6.8" />
    </S>
  );
}

/** 实时视口：显示器 + 山形 */
export function WbViewportIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <rect x="1.5" y="2.5" width="13" height="9" rx="1.5" />
      <path d="M3 9l3-3 2.4 2.2L11 5.6l2.5 2.2" />
      <path d="M6 14.2h4" />
    </S>
  );
}

/** 特征树：层级节点 */
export function WbTreeIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <rect x="5.5" y="1.8" width="5" height="3.4" rx="1" />
      <rect x="1.5" y="10.8" width="5" height="3.4" rx="1" />
      <rect x="9.5" y="10.8" width="5" height="3.4" rx="1" />
      <path d="M8 5.2v2.6M8 7.8H4v3M8 7.8h4v3" />
    </S>
  );
}

/** 快照历史：照片 + 山形 + 叠层 */
export function WbSnapshotsIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <rect x="1.5" y="4.3" width="10.4" height="8.2" rx="1.5" />
      <path d="M4.2 4.3V3a1.4 1.4 0 0 1 1.4-1.4h6.4A1.4 1.4 0 0 1 13.4 3v5.6a1.4 1.4 0 0 1-1 1.35" />
      <circle cx="4.6" cy="7" r="1" />
      <path d="M3.2 10.8l2.4-2.4 1.8 1.8 2-2 1.8 1.8" />
    </S>
  );
}

/** 3D 预览：等轴测立方体（同建模，供预览/空态使用） */
export function WbCubeIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <path d="M8 1.6l5.4 3v6.8L8 14.4l-5.4-3V4.6l5.4-3z" />
      <path d="M2.6 4.6L8 7.6l5.4-3" />
      <path d="M8 7.6v6.8" />
    </S>
  );
}

/** 需求：旗标 */
export function WbRequirementIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <path d="M3.5 14.5v-12" />
      <path d="M3.5 3h8l-2 2.5 2 2.5h-8" />
    </S>
  );
}

/** 方案分支 */
export function WbVariantIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <circle cx="4.2" cy="3.6" r="1.6" />
      <circle cx="11.8" cy="4.6" r="1.6" />
      <circle cx="4.2" cy="12.4" r="1.6" />
      <path d="M4.2 5.2v2.6a3 3 0 0 0 3 3h2.6M5.7 4.2h3.6" />
    </S>
  );
}

/** 参数表：双滑杆 */
export function WbSpecIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <path d="M2 4.5h12M2 11.5h12" />
      <circle cx="6" cy="4.5" r="1.7" />
      <circle cx="10.5" cy="11.5" r="1.7" />
    </S>
  );
}

/** 备注：笔 */
export function WbNoteIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <path d="M10.6 2.2l3.2 3.2-8.2 8.2-4 .8.8-4 8.2-8.2z" />
      <path d="M9.2 3.6l3.2 3.2" />
    </S>
  );
}

/** 前置 SolidWorks：窗口 + 箭头 */
export function WbFocusIcon({ className }: { className?: string }) {
  return (
    <S className={className}>
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
      <path d="M6 10l4-4M10 9.2V6H6.8" />
    </S>
  );
}
