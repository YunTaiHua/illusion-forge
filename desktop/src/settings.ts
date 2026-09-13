/**
 * 用户设置读取模块
 * ==================
 *
 * 读取 ~/.illusion/settings.json 中的 ui_language 等字段，
 * 用于决定托盘菜单等用户可见文本的语言。
 *
 * 配置目录解析顺序（与后端 illusion_forge.config.paths.get_config_dir 保持一致）：
 *   1. ILLUSION_CONFIG_DIR 环境变量
 *   2. ~/.illusion/（默认）
 *
 * 注意：本模块仅读取，不创建目录、不写回。后端首次启动会自行创建。
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

/** 支持的界面语言（与后端 illusion_forge.config.i18n 取值一致） */
export type UiLanguage = 'zh-CN' | 'en-US';

/** settings.json 的部分字段（仅取桌面壳关心的） */
export interface Settings {
  ui_language?: string;
  [key: string]: unknown;
}

/**
 * 返回配置目录路径（不创建）。
 * 对应后端 illusion_forge.config.paths.get_config_dir。
 */
export function getConfigDir(): string {
  const envDir = process.env.ILLUSION_CONFIG_DIR;
  if (envDir) return envDir;
  return path.join(os.homedir(), '.illusion');
}

/** 返回 settings.json 完整路径 */
export function getSettingsPath(): string {
  return path.join(getConfigDir(), 'settings.json');
}

/**
 * 读取 settings.json，失败返回空对象。
 * 文件不存在或 JSON 非法时不抛错，由调用方决定回退策略。
 */
export function loadSettings(): Settings {
  try {
    const raw = fs.readFileSync(getSettingsPath(), 'utf8');
    return JSON.parse(raw) as Settings;
  } catch {
    return {};
  }
}

/**
 * 获取当前界面语言，默认 zh-CN。
 * 仅接受 'zh-CN' / 'en-US'，其他值回退到 zh-CN。
 */
export function getUiLanguage(): UiLanguage {
  const lang = loadSettings().ui_language;
  return lang === 'en-US' ? 'en-US' : 'zh-CN';
}
