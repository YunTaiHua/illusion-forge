/**
 * 全局图片预览事件（轻量通信）
 *
 * 任意组件通过 openImagePreview 派发事件，ImagePreview 组件（App 根节点
 * 挂载一次）监听后打开全屏预览。避免把预览状态层层下传。
 */

/** 图片预览事件名 */
export const IMAGE_PREVIEW_EVENT = 'illusion:image-preview';

/**
 * 打开应用内图片预览
 *
 * @param url - 图片 URL（http/https 或相对路径）
 */
export function openImagePreview(url: string): void {
  window.dispatchEvent(new CustomEvent(IMAGE_PREVIEW_EVENT, { detail: url }));
}
