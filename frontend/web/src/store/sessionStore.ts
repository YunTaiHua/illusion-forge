/**
 * @fileoverview 会话注册表（单一数据源）
 *
 * 会话域的唯一真源：元数据（web_sessions 推送权威）与运行时视图
 * （WS 事件驱动权威）合并在同一张注册表中，取代历史上 sessionList
 * 与 sessionViews 双数据源 + 暴露层逐项合并的架构。
 *
 * 设计约束：
 * - 所有状态迁移必须经 sessionReducer 的纯函数完成，禁止原地突变；
 * - 侧栏列表是派生 selector（selectSessionList），无独立存储；
 * - 激活意图（ActivationIntent）携带唯一 client_token，与后端回显
 *   精确配对，杜绝迟到事件劫持活跃会话；
 * - tombstones 记录近期删除的会话 ID，在途事件不得重建幻影视图。
 *
 * @module store/sessionStore
 */

import type {
  PendingToolCall,
  TodoItemSnapshot,
  TranscriptItem,
  TurnOutlineEntry,
} from '../types/protocol';

/**
 * 选择请求载荷（后端 select_request 驱动的多步选择 / 前端本地内联选项）
 */
export type SelectRequestPayload = {
  /** 关联的命令名称 */
  command: string;
  /** 对话框标题 */
  title: string;
  /** 可选项列表 */
  options: Array<{ value: string; label: string; description?: string; active?: boolean }>;
};

/**
 * 会话记录：元数据 + 运行时视图的合一模型
 *
 * 元数据字段由 web_sessions 推送重建；运行时字段由会话级事件驱动。
 * 任何更新都必须产生新对象（不可变），引用稳定即 memo 生效前提。
 */
export interface SessionRecord {
  // === 元数据（web_sessions 推送权威）===
  /** 会话 ID */
  id: string;
  /** 显示标签（后端自动命名） */
  label: string;
  /** 所属工作区目录（侧栏分组与目录按钮展示依据） */
  cwd: string;
  /** 创建时间（秒级时间戳） */
  createdAt: number;
  /** 轮次数 */
  turnCount: number;
  /** 摘要 */
  summary: string;
  /** 标题（用户重命名优先于 summary/label 展示） */
  title: string;
  /** 是否工作台（canvas）类型会话 */
  workbench: boolean;
  /** 后端是否持有该会话的内存运行时 */
  inMemory: boolean;
  /** 是否在当前后端推送的会话列表中（未列入的既有记录保留运行时数据但不渲染） */
  listed: boolean;
  // === 运行时（WS 事件驱动权威）===
  /** 是否正在运行任务（assistant_delta/tool_started/line_complete 即时驱动） */
  busy: boolean;
  /** 会话阶段：idle/thinking/tool_executing/awaiting_input */
  phase: string;
  /** 是否已加载转录（恢复完成） */
  materialized: boolean;
  /** 是否正在恢复中（beginRestore/endRestore 统一管理，必配超时兜底） */
  restoring: boolean;
  /** 转录项列表 */
  items: TranscriptItem[];
  /** 助手流式缓冲 */
  assistantBuffer: string;
  /** 流式思考文本 */
  streamingReasoning: string;
  /** 待处理工具调用 */
  pendingToolCalls: PendingToolCall[];
  /** 会话级状态（goal/用量等，白名单键） */
  status: Record<string, unknown>;
  /** 会话级模态框（权限/问答/计划审批） */
  modal: Record<string, unknown> | null;
  /** 会话级待办事项 */
  todoItems: TodoItemSnapshot[];
  /** 会话级内联选项（B 通道多步选择） */
  inlineOptions: SelectRequestPayload | null;
  /** reasoning 是否正在流式（大脑脉冲动画跟随） */
  reasoningStreaming: boolean;
  /** 停止请求已发送、等待后端确认 */
  stopping: boolean;
  /** 全量轮次大纲（null = 无后端大纲，导航退化为本地已载入轮次） */
  turnOutline: TurnOutlineEntry[] | null;
  /** 已载入最小轮号（1-based；分页恢复的头部边界） */
  firstLoadedTurn: number;
  /** 历史分页加载中 */
  loadingHistory: boolean;
  /** 转录整体替换信号（rewind/compact，Date.now()）；ChatArea 据此强制回底部 */
  transcriptReplaceTick: number;
}

/**
 * 激活意图：一次"期望切换活跃会话"的操作登记
 *
 * 每次 new/ensure/restore/fork/删除补位生成唯一 token 并随请求发给后端，
 * 响应事件（web_session_ready/web_restore_completed）回显该 token，
 * 仅精确匹配时才执行激活——迟到的被动推送永远无法劫持活跃会话。
 */
export interface ActivationIntent {
  /** 本次操作的唯一关联令牌（client_token） */
  token: string;
  /** 操作类别 */
  kind: 'restore' | 'new' | 'ensure' | 'fork' | 'delete-fallback';
  /** 目标会话 ID（restore 类为具体 ID；创建类为 null，等响应揭晓） */
  sessionId: string | null;
}

/**
 * 会话域状态
 */
export interface SessionStoreState {
  /** 会话注册表：id → 记录（元数据 + 运行时合一） */
  sessions: Record<string, SessionRecord>;
  /** 列表顺序（web_sessions 推送顺序；侧栏分组前的权威顺序） */
  order: string[];
  /** 当前活跃会话 ID（本地切换权威；后端推送仅首次连接采用） */
  activeId: string | null;
  /** 当前激活意图（无待激活操作时为 null） */
  activation: ActivationIntent | null;
  /** 近期删除的会话 ID → 删除时间戳（阻断在途事件重建幻影视图） */
  tombstones: Record<string, number>;
}

/**
 * 创建空会话记录
 *
 * @param id - 会话 ID
 * @param cwd - 所属工作区目录
 * @returns 初始会话记录
 */
export function createSessionRecord(id: string, cwd: string = ''): SessionRecord {
  return {
    id,
    label: '',
    cwd,
    createdAt: 0,
    turnCount: 0,
    summary: '',
    title: '',
    workbench: false,
    inMemory: true,
    listed: false,
    busy: false,
    phase: 'idle',
    materialized: false,
    restoring: false,
    items: [],
    assistantBuffer: '',
    streamingReasoning: '',
    pendingToolCalls: [],
    status: {},
    modal: null,
    todoItems: [],
    inlineOptions: null,
    reasoningStreaming: false,
    stopping: false,
    turnOutline: null,
    firstLoadedTurn: 1,
    loadingHistory: false,
    transcriptReplaceTick: 0,
  };
}

/**
 * 创建会话域初始状态
 */
export function createInitialSessionState(): SessionStoreState {
  return { sessions: {}, order: [], activeId: null, activation: null, tombstones: {} };
}

/**
 * 派生侧栏会话列表（推送顺序，仅含当前列入后端列表的会话）
 *
 * 列表不再独立存储：order + sessions 的纯派生，busy/phase/active
 * 等实时字段天然与运行时一致，不存在双源合并。
 *
 * @param state - 会话域状态
 * @returns 按推送顺序排列的已列入会话记录
 */
export function selectSessionList(state: SessionStoreState): SessionRecord[] {
  const out: SessionRecord[] = [];
  for (const id of state.order) {
    const rec = state.sessions[id];
    if (rec && rec.listed) out.push(rec);
  }
  return out;
}

/**
 * 派生活跃会话记录
 *
 * @param state - 会话域状态
 * @returns 活跃会话记录（无活跃或记录缺失时为 undefined）
 */
export function selectActiveRecord(state: SessionStoreState): SessionRecord | undefined {
  return state.activeId ? state.sessions[state.activeId] : undefined;
}
