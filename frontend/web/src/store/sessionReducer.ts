/**
 * @fileoverview 会话域状态迁移（纯函数 reducer）
 *
 * 会话注册表的所有变更收敛于此处的纯函数，保证：
 * - 不可变更新：任何字段修改都产生新对象，杜绝"setState 后突变"
 *   与引用共享导致的渲染丢失（历史上 web_sessions 处理器的顽疾）；
 * - 可测试性：状态迁移无 React/定时器副作用，副作用（恢复超时等）
 *   由 useWebSocketSession 在 dispatch 前后统一管理；
 * - 单一语义：web_sessions 推送只重建元数据（busy 仅对未恢复视图
 *   只升不降兜底、goal 仅补缺），运行时字段由事件流权威驱动。
 *
 * @module store/sessionReducer
 */

import type { WebSessionItem } from '../types/protocol';
import {
  createSessionRecord,
  type ActivationIntent,
  type SessionRecord,
  type SessionStoreState,
} from './sessionStore';

/**
 * 会话级上下文/用量字段（随 web_sessions 推送，行任务结束时刷新）
 *
 * 多会话模式下这些数据按会话推送（后端全局 state_snapshot 已剔除），
 * web_sessions 到达时合并进对应会话记录的 status，供右栏展示。
 */
export const SESSION_STATUS_FIELDS = [
  'context_tokens',
  'input_tokens',
  'output_tokens',
  'cache_read_input_tokens',
  'cache_creation_input_tokens',
  'context_cache_read',
  'context_cache_creation',
  'context_input',
  'context_output',
  'goal',
] as const;

/**
 * restore_completed 的 state 载荷中属于会话的键
 *
 * 后端 _session_state_payload 基于全局 app_state 生成，包含全局键
 * （model/effort/permission_mode/ui_language 等）。这些全局键必须由
 * 全局 state_snapshot / web_setting_changed 驱动，若存入 record.status
 * 会用恢复时的旧值影子化后续全局更新（工具栏下拉显示过期）。
 */
export const SESSION_STATUS_KEYS = new Set<string>([
  ...SESSION_STATUS_FIELDS,
  'session_id',
  'phase',
  // 注意：context_window 是全局设置，由 state_snapshot 权威驱动，
  // 不放入会话键——否则恢复快照会影子化用户后续的窗口调整
]);

/**
 * tombstone 存活时长（毫秒）：超过后若推送列表仍缺席则清除标记
 *
 * tombstone 的职责是阻断"删除后在途事件重建幻影视图"；2 分钟足以
 * 覆盖所有在途事件的生命周期，之后清理避免无限累积。
 */
const TOMBSTONE_TTL_MS = 120_000;

/**
 * 会话域动作
 */
export type SessionAction =
  /** 通用不可变补丁（记录缺失时创建；tombstone 中的会话拒绝重建） */
  | { type: 'patch'; sid: string; patch: Partial<SessionRecord> }
  /** 确保会话记录存在（tombstone 中的会话拒绝创建） */
  | { type: 'ensure'; sid: string; cwd?: string }
  /** 设置活跃会话（本地切换权威） */
  | { type: 'activate'; sid: string | null }
  /** 登记/清除激活意图 */
  | { type: 'setActivation'; activation: ActivationIntent | null }
  /** web_sessions 推送：重建元数据与列表顺序 */
  | { type: 'sessionsPush'; items: WebSessionItem[]; backendActiveId?: string | null }
  /** 删除会话：移除记录并立 tombstone */
  | { type: 'remove'; sids: string[] }
  /** 连接关闭：清除全部恢复中与激活意图（重连后由后端推送重新同步） */
  | { type: 'connectionClosed' };

/**
 * 会话域 reducer（纯函数）
 *
 * @param state - 当前状态
 * @param action - 动作
 * @returns 新状态（无变化时返回原引用）
 */
export function sessionReducer(state: SessionStoreState, action: SessionAction): SessionStoreState {
  switch (action.type) {
    case 'patch': {
      const prev = state.sessions[action.sid];
      if (!prev && state.tombstones[action.sid] !== undefined) return state;
      const base = prev ?? createSessionRecord(action.sid);
      // no-op 短路：补丁未改变任何字段时返回原引用（流式 delta 高频
      // 场景下避免无意义的新对象引发整树重渲染）
      const keys = Object.keys(action.patch) as (keyof SessionRecord)[];
      if (prev && keys.every((k) => action.patch[k] === prev[k])) return state;
      return {
        ...state,
        sessions: { ...state.sessions, [action.sid]: { ...base, ...action.patch, id: action.sid } },
      };
    }

    case 'ensure': {
      if (state.sessions[action.sid]) {
        // 仅在携带新 cwd 时更新归属（切会话时后端权威目录可能迟到）
        if (action.cwd && state.sessions[action.sid]!.cwd !== action.cwd) {
          return {
            ...state,
            sessions: {
              ...state.sessions,
              [action.sid]: { ...state.sessions[action.sid]!, cwd: action.cwd },
            },
          };
        }
        return state;
      }
      if (state.tombstones[action.sid] !== undefined) return state;
      return {
        ...state,
        sessions: { ...state.sessions, [action.sid]: createSessionRecord(action.sid, action.cwd ?? '') },
      };
    }

    case 'activate': {
      if (state.activeId === action.sid) return state;
      return { ...state, activeId: action.sid };
    }

    case 'setActivation': {
      return { ...state, activation: action.activation };
    }

    case 'sessionsPush': {
      const now = Date.now();
      const sessions: Record<string, SessionRecord> = { ...state.sessions };
      const tombstones = { ...state.tombstones };
      const order: string[] = [];
      const seen = new Set<string>();
      for (const item of action.items) {
        const id = String(item.id ?? '');
        if (!id) continue;
        seen.add(id);
        order.push(id);
        // 后端仍列出 = 删除未生效（如运行中会话被跳过），解除 tombstone 复活
        delete tombstones[id];
        const base = sessions[id] ?? createSessionRecord(id);
        // 会话级 status：用量字段以推送为准刷新（本通道是其唯一来源）；
        // goal 仅补缺——其权威通道是 state_snapshot/goal_status 实时事件，
        // 列表推送滞后于行任务结束，覆盖会把新 goal 拉回旧值
        const status = { ...base.status };
        for (const field of SESSION_STATUS_FIELDS) {
          const value = item[field];
          if (value === undefined) continue;
          if (field === 'goal') {
            if (status.goal === undefined) status.goal = value;
          } else {
            status[field] = value;
          }
        }
        sessions[id] = {
          ...base,
          label: String(item.label ?? base.label),
          cwd: String(item.cwd ?? '') || base.cwd,
          createdAt: Number(item.created_at ?? base.createdAt),
          turnCount: Number(item.turn_count ?? base.turnCount),
          summary: String(item.summary ?? base.summary),
          title: String(item.title ?? base.title),
          workbench: item.workbench === true,
          inMemory: item.in_memory !== false,
          listed: true,
          // busy 只升不降且仅对未恢复视图兜底：本地 busy 由事件即时驱动，
          // 推送滞后于行任务结束，降下会造成运行中会话闪烁
          busy: base.busy || (!base.materialized && item.busy === true),
          phase: item.phase ?? base.phase,
          status,
        };
      }
      // 未列入本次推送的既有记录：保留运行时数据但退出列表
      // （推送可能分页；显式删除走 remove 动作的 tombstone 通道）
      for (const id of Object.keys(sessions)) {
        const rec = sessions[id]!;
        if (rec.listed && !seen.has(id)) {
          sessions[id] = { ...rec, listed: false };
        }
      }
      // 清理过期 tombstone（推送即权威列表：仍缺席且已过存活期）
      for (const [id, ts] of Object.entries(tombstones)) {
        if (!seen.has(id) && now - ts > TOMBSTONE_TTL_MS) delete tombstones[id];
      }
      // 活跃会话：仅当本地尚无有效活跃记录（首次连接/重连）时采用后端权威；
      // 本地切换会话是纯前端操作，后端推送的 active 不代表用户当前视图
      let activeId = state.activeId;
      const backendActive = action.backendActiveId || null;
      if (backendActive && (activeId == null || sessions[activeId] === undefined)) {
        activeId = backendActive;
        if (!sessions[backendActive]) {
          sessions[backendActive] = createSessionRecord(backendActive);
        }
      }
      return { ...state, sessions, order, tombstones, activeId };
    }

    case 'remove': {
      const sessions = { ...state.sessions };
      const tombstones = { ...state.tombstones };
      const now = Date.now();
      let changed = false;
      for (const sid of action.sids) {
        if (sessions[sid]) {
          delete sessions[sid];
          changed = true;
        }
        tombstones[sid] = now;
      }
      // 激活意图指向被删会话时一并作废（等待一个永远不会来的响应）
      const activation = state.activation && state.activation.sessionId
        && action.sids.includes(state.activation.sessionId) ? null : state.activation;
      if (!changed && activation === state.activation) {
        // 仍要落 tombstone（记录本就不存在时，仅追加标记）
        return { ...state, tombstones, activation };
      }
      return { ...state, sessions, tombstones, activation };
    }

    case 'connectionClosed': {
      // 断线清理：restoring/busy/stopping/流式缓冲等瞬态运行标志全部复位——
      // 断线期间到达不了的事件（line_complete 等）不会重发，不复位会让
      // busy/stopping 永久卡死（输入框永久禁用）。重连后由 web_sessions
      // 推送与 web_restore_completed 载荷重新校准真实状态。
      const sessions: Record<string, SessionRecord> = {};
      let changed = false;
      for (const [id, rec] of Object.entries(state.sessions)) {
        if (rec.restoring || rec.busy || rec.stopping || rec.reasoningStreaming
          || rec.assistantBuffer || rec.streamingReasoning) {
          sessions[id] = {
            ...rec,
            restoring: false,
            busy: false,
            stopping: false,
            reasoningStreaming: false,
            assistantBuffer: '',
            streamingReasoning: '',
          };
          changed = true;
        } else {
          sessions[id] = rec;
        }
      }
      return {
        ...state,
        sessions: changed ? sessions : state.sessions,
        activation: null,
      };
    }

    default:
      return state;
  }
}
