/**
 * @fileoverview ANSI 转义码渲染工具
 *
 * 将工具结果中的 ANSI SGR 颜色转义码（如 \x1b[32m...\x1b[0m）解析为
 * React 元素，使 bash 等彩色输出在前端正常显示颜色。
 *
 * 支持的 SGR 码：
 * - 0 重置（默认色）
 * - 1 加粗
 * - 30-37 / 90-97 前景色（含明亮色）
 * - 40-47 / 100-107 背景色
 * 其余 SGR 码（下划线/闪烁等）忽略，保持文本不变。
 *
 * @module ansi
 */

import type { ReactNode } from 'react';

/** ANSI 颜色码 → CSS 颜色映射（与终端默认配色接近） */
const FG_COLORS: Record<string, string> = {
  '30': '#3f3f46', '31': '#e5484d', '32': '#46a758', '33': '#d97706',
  '34': '#3e63dd', '35': '#8e4ec6', '36': '#0d9488', '37': '#e4e4e7',
  '90': '#71717a', '91': '#ff6369', '92': '#7ee2a0', '93': '#fbbf24',
  '94': '#7aa2f7', '95': '#c792ea', '96': '#22d3ee', '97': '#fafafa',
};

const BG_COLORS: Record<string, string> = {
  '40': '#27272a', '41': '#7f1d1d', '42': '#14532d', '43': '#713f12',
  '44': '#1e3a5f', '45': '#4c1d95', '46': '#134e4a', '47': '#3f3f46',
  '100': '#52525b', '101': '#b91c1c', '102': '#15803d', '103': '#a16207',
  '104': '#1d4ed8', '105': '#6d28d9', '106': '#0f766e', '107': '#a1a1aa',
};

const ANSI_RE = /\x1b\[([0-9;]*)m/g;

interface AnsiStyle {
  color?: string;
  background?: string;
  bold?: boolean;
}

/**
 * 解析 ANSI 转义码文本为 React 元素
 *
 * 维护一个样式栈：遇到 SGR 码 push 新样式，遇到 0 重置清栈。
 * 输出为 span 嵌套结构（样式累积）。
 *
 * @param text - 可能含 ANSI 转义码的文本
 * @returns React 节点数组
 */
export function renderAnsi(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const stack: AnsiStyle[] = [];
  let lastIndex = 0;
  let key = 0;

  const pushText = (plain: string) => {
    if (!plain) return;
    const current = stack[stack.length - 1];
    if (!current) {
      nodes.push(plain);
    } else {
      const style: React.CSSProperties = {};
      if (current.color) style.color = current.color;
      if (current.background) style.backgroundColor = current.background;
      if (current.bold) style.fontWeight = 'bold';
      nodes.push(<span key={key++} style={style}>{plain}</span>);
    }
  };

  let match: RegExpExecArray | null;
  ANSI_RE.lastIndex = 0;
  while ((match = ANSI_RE.exec(text)) !== null) {
    pushText(text.slice(lastIndex, match.index));
    lastIndex = match.index + match[0].length;

    const codes = match[1] ? match[1].split(';') : ['0'];
    let color: string | undefined;
    let background: string | undefined;
    let bold: boolean | undefined;
    for (const raw of codes) {
      const code = raw.trim() || '0';
      if (code === '0') {
        color = undefined;
        background = undefined;
        bold = undefined;
      } else if (code === '1') {
        bold = true;
      } else if (FG_COLORS[code]) {
        color = FG_COLORS[code];
      } else if (BG_COLORS[code]) {
        background = BG_COLORS[code];
      }
      // 其余码（2/3/4/5/7/9 等）忽略
    }
    if (color !== undefined || background !== undefined || bold !== undefined) {
      stack.push({ color, background, bold });
    } else {
      // 纯重置（0）或全部忽略：清空样式栈
      stack.length = 0;
    }
  }
  pushText(text.slice(lastIndex));

  return nodes;
}
