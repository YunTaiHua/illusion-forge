/**
 * @fileoverview WebSocket 会话管理 Hook（多会话并发）
 *
 * 本模块提供 useWebSocketSession Hook，用于管理与后端的 WebSocket 通信。
 *
 * 多会话架构：
 * - 后端为每个会话维护独立运行时（独立引擎），行任务并发执行互不阻塞。
 * - 前端为每个会话维护独立视图（SessionView）：转录、流式缓冲、工具调用、
 *   模态框、busy 状态等全部按会话隔离。
 * - 后端事件携带 session_id 字段，本 hook 按会话路由到对应视图；
 *   全局事件（设置/任务/资源/模型）保持全局。
 * - 切换会话为纯本地切换（视图已就绪时），无需请求后端；
 *   首次打开/页面刷新后的会话通过 web_restore_session 惰性恢复。
 * - 对外暴露的 API 表面保持单会话语义：staticItems / assistantBuffer /
 *   busy / modal 等均读取"活跃会话"视图，上层组件无需感知多会话。
 *
 * @module useWebSocketSession
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import { attachAuthHeaders } from '../utils/launchToken';
import {
  createInitialSessionState,
  selectSessionList,
  type ActivationIntent,
  type SelectRequestPayload,
  type SessionRecord,
} from '../store/sessionStore';
import { SESSION_STATUS_KEYS, sessionReducer, type SessionAction } from '../store/sessionReducer';

import type { CanvasDoc, CadUpdatePayload } from '../types/canvas';
import type {
  AgentCatalog,
  AgentModelOption,
  AgentTaskItem,
  BackendEvent,
  FileContentPayload,
  FileTreeNode,
  FileMentionCandidate,
  FrontendRequest,
  GitStatusSnapshot,
  GoalStatus,
  McpServerSnapshot,
  PendingToolCall,
  PluginSnapshot,
  RuleSnapshot,
  SessionFileItem,
  SkillSnapshot,
  SwarmNotificationSnapshot,
  SwarmTeammateSnapshot,
  TaskSnapshot,
  TodoItemSnapshot,
  ToastPayload,
  TranscriptItem,
  TurnOutlineEntry,
  WebWorkspaceItem,
} from '../types/protocol';

// SelectRequestPayload 已迁移至 store/sessionStore（会话域模型的一部分），此处 re-export 兼容既有引用
export type { SelectRequestPayload } from '../store/sessionStore';

/**
 * 助手流式回复刷新间隔（毫秒）
 * 控制助手回复文本在屏幕上的更新频率
 */
const ASSISTANT_DELTA_FLUSH_MS = 8;

/**
 * 助手流式回复刷新字符阈值
 * 当缓冲的字符数达到此值时立即刷新
 */
const ASSISTANT_DELTA_FLUSH_CHARS = 16;

/**
 * 遮罩层连接错误分类。
 * - auth：认证失败（凭据缺失 / 无效 / 后端重启后 token 过期且 cookie 失效）；
 * - unreachable：后端不可达（未启动 / 崩溃 / 网络中断）。
 */
export interface WebConnectionError {
  kind: 'auth' | 'unreachable';
}

/**
 * 连接失败时探测后端可达性（REST 轻量探测，携带 launch token）。
 *
 * WS 握手失败拿不到状态码（浏览器规范所限），只能靠 REST 旁路区分
 * 「认证失败」与「服务不可达」，遮罩据此展示不同的解决方式。
 *
 * @returns 认证失败 / 不可达；后端实际可达（瞬间抖动）时为 null
 */
async function probeBackendError(): Promise<WebConnectionError | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  let res: Response;
  try {
    res = await fetch('/api/envs', {
      headers: attachAuthHeaders({}),
      signal: controller.signal,
    });
  } catch {
    return { kind: 'unreachable' };
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 401 || res.status === 403) return { kind: 'auth' };
  if (res.ok) return null; // 后端可达：可能是瞬断，遮罩继续等待重连
  return { kind: 'unreachable' };
}

/**
 * 工具调用行匹配正则表达式
 *
 * 匹配模型可能嵌入在助手文本中的工具调用预览行。
 * 例如："  bash (git add ...)" 或 "read (file_path: ...)"
 */
const TOOL_CALL_LINE_RE = /^\s{2,}\w[\w-]*\s*\(.*\)\s*$/;

/**
 * 变更类工具集合
 *
 * 这些工具执行完成后可能改动工作区（文件/目录/配置），右栏数据
 * （文件树 / Git 状态 / 资源快照）需要随之无感刷新。触发后经统一
 * 刷新函数（refreshRightPanel）防抖合并，避免工具链内连续变更时
 * 重复请求。
 */
const CHANGE_TOOLS = new Set(['edit_file', 'write_file', 'bash', 'powershell', 'agent']);

/**
 * 从助手文本中移除工具调用预览行
 *
 * @param text - 原始助手文本
 * @returns 移除工具调用行后的文本
 */
function stripToolCallLines(text: string): string {
  const lines = text.split('\n');
  const filtered = lines.filter((line) => !TOOL_CALL_LINE_RE.test(line));
  return filtered.length > 0 ? filtered.join('\n') : text;
}

/**
 * 重放/恢复的 assistant 消息剥离工具调用预览行
 *
 * 直播路径（assistant_complete / tool_started flush）pushStatic 前都会
 * stripToolCallLines，而 rewind/restore 重放的 msg.text 是未清洗的原始文本，
 * 此处统一清洗，保证与直播显示一致。
 */
function stripReplayItems(items: TranscriptItem[]): TranscriptItem[] {
  return items.map((item) =>
    item.role === 'assistant' && item.text
      ? { ...item, text: stripToolCallLines(item.text) }
      : item,
  );
}

/**
 * 计算转录头部前 nTurns 轮消耗的条目数（去掉前 nTurns 轮的起始下标）
 *
 * web_history 前插时用于截掉与新页重叠的头部轮次。
 *
 * @param items - 转录项列表（user 条目开轮）
 * @param turns - 要跳过的轮数（<= 0 返回 0）
 * @returns 截掉前 turns 轮后的起始下标（不足时为 items.length）
 */
function countLeadingTurnItems(items: TranscriptItem[], turns: number): number {
  if (turns <= 0) return 0;
  let seen = 0;
  for (let i = 0; i < items.length; i++) {
    if (items[i]!.role === 'user') {
      seen += 1;
      if (seen > turns) return i;
    }
  }
  return items.length;
}

/**
 * 会话级事件类型：必须携带 session_id（缺失即丢弃并告警）
 *
 * 后端所有会话级 emit 路径（_make_render_event 闭包、_emit(session_id=...)）
 * 均已全量标记；缺失说明后端路由缺陷。静默回退到活跃会话是多会话并发下
 * 的串话通道，此处显式封堵。
 */
const SESSION_SCOPED_EVENTS = new Set([
  'assistant_delta',
  'assistant_complete',
  'line_complete',
  'transcript_item',
  'tool_started',
  'tool_completed',
  'tool_input_updated',
  'tool_progress',
  'clear_transcript',
  'replace_transcript',
  'modal_request',
  'select_request',
  'todo_update',
  'web_restore_started',
  'web_restore_completed',
  'web_session_ready',
]);

/**
 * 允许回退到活跃会话的事件（历史兼容：后端个别路径未标记 session_id，
 * 如全局错误、web_history 的 session_not_found 错误页等）
 */
const ACTIVE_FALLBACK_EVENTS = new Set([
  'error',
  'bg_agent_status',
  'web_query_result',
  'web_history',
  'session_rewind',
]);

/**
 * 选项类型
 */
type Option = { value: string; label: string; active?: boolean };

/**
 * 会话级流式缓冲
 *
 * assistant_delta 等流式事件按会话分桶缓冲，避免并发会话互相串扰。
 */
interface StreamBuffer {
  pending: string;
  raw: string;
  reasoning: string;
  flushedForTool: boolean;
  timer: ReturnType<typeof setTimeout> | null;
}

/**
 * WebSocket 会话状态接口
 *
 * 定义了 useWebSocketSession Hook 返回的所有状态和操作方法。
 * 会话级字段（staticItems/assistantBuffer/busy/modal 等）均指向
 * 当前活跃会话的视图；全局字段（tasks/modelOptions/connected 等）
 * 与具体会话无关。
 */
export interface WebSocketSessionState {
  // === 活跃会话视图（单会话语义，兼容既有组件）===
  staticItems: TranscriptItem[];
  assistantBuffer: string;
  streamingReasoning: string;
  status: Record<string, unknown>;
  busy: boolean;
  modal: Record<string, unknown> | null;
  todoItems: TodoItemSnapshot[];
  pendingToolCalls: PendingToolCall[];
  /** reasoning 是否正在流式（大脑脉冲动画跟随） */
  reasoningStreaming: boolean;
  /** 正在恢复的会话 ID（null 表示无恢复进行中，活跃视图） */
  restoringSessionId: string | null;
  // === 全局状态 ===
  tasks: TaskSnapshot[];
  commands: string[];
  mcpServers: McpServerSnapshot[];
  skills: SkillSnapshot[];
  plugins: PluginSnapshot[];
  rules: RuleSnapshot[];
  /** 智能体与后台任务列表（web_agent_tasks，随会话隔离；右栏 Agents 区块数据源） */
  agentTasks: AgentTaskItem[];
  /** 文件树缓存：目录相对路径 → 子条目（'' 为根；懒加载，右栏 Files 区块数据源） */
  fileTree: Record<string, FileTreeNode[]>;
  /** 文件树正在加载的目录路径列表（行内加载态） */
  fileTreeLoadingPaths: string[];
  /** 会话内修改文件列表（web_session_files，随会话隔离；右栏会话文件区块数据源） */
  sessionFiles: SessionFileItem[];
  /** 会话文件拉取中（右栏会话文件区块加载态） */
  sessionFilesLoading: boolean;
  /** 全量轮次大纲（null = 无后端大纲，导航退化为本地已载入轮次） */
  turnOutline: TurnOutlineEntry[] | null;
  /** 已载入最小轮号（1-based；分页恢复的头部边界） */
  firstLoadedTurn: number;
  /** 历史轮次分页加载中（导航跳转/加载更早按钮防重标记） */
  loadingHistory: boolean;
  /** 转录整体替换信号（rewind/compact，Date.now()）；ChatArea 据此强制回底部 */
  transcriptReplaceTick: number;
  /** 加载更早的轮次分页（在途/已全载入时自动跳过） */
  requestHistory: () => void;
  /** 分叉当前会话（turns = 保留前 N 轮；后端完成后经 web_restore_completed 自动切换） */
  forkSession: (turns?: number) => void;
  /** @ 提及补全候选订阅：返回取消订阅函数。响应直通订阅方（PromptInput 本地持有缓存），
      不进入 hook 状态，避免每次补全响应触发整页重渲染 */
  subscribeFileMentions: (cb: (result: { requestId: string; query: string; candidates: FileMentionCandidate[] }) => void) => () => void;
  /** 拉取 @ 提及补全候选（web_request_file_mentions，绑定当前活跃会话工作区） */
  requestFileMentions: (query: string, requestId: string) => void;
  /** Git 状态快照（null = 未拉取；is_repo=false 前端隐藏区块） */
  gitStatus: GitStatusSnapshot | null;
  /** Git 状态加载中 */
  gitLoading: boolean;
  /** 文件预览载荷（null = 预览关闭；error 字段非空表示读取失败） */
  filePreview: FileContentPayload | null;
  /** 文件预览加载中 */
  filePreviewLoading: boolean;
  modelOptions: Option[];
  ready: boolean;
  /** 首帧引导中：ready 后首个会话内容（web_restore_completed）尚未呈现 */
  bootstrapping: boolean;
  /** 新建会话等待中（newSession 发出后、restore_completed 到达前；聊天区局部加载反馈） */
  awaitingNewSession: boolean;
  /** 首次登录标识（后端 ready 事件携带，无 env_N 且无 working_directory 时为 true） */
  firstLogin: boolean;
  showThinking: boolean;
  swarmTeammates: SwarmTeammateSnapshot[];
  swarmNotifications: SwarmNotificationSnapshot[];
  bgAgentLabel: string | null;
  connected: boolean;
  /** 遮罩层连接错误（认证失败 / 后端不可达），连接后自动清空 */
  connectionError: WebConnectionError | null;
  /** 模型是否正在切换中 */
  modelSwitching: boolean;
  /** 设置模型切换状态 */
  setModelSwitching: (v: boolean) => void;
  // === 多会话管理 ===
  /** 会话列表（含 busy/phase/active/cwd 状态，供侧边栏按目录分组渲染）；
   *  派生自会话注册表（selectSessionList），busy/phase 为运行时实时值 */
  sessions: { value: string; label: string; busy: boolean; phase: string; active: boolean; cwd: string; createdAt: number; turnCount: number; summary: string; title: string; workbench: boolean }[];
  /** 确保存在指定类型的活跃会话（后端原子：复用或创建并激活）。
   *  视图切换时调用；前端不做任何类型推断。 */
  ensureSession: (workbench: boolean) => void;
  /** 注册的工作区列表（默认目录恒在首位，web_workspaces 事件驱动） */
  workspaces: WebWorkspaceItem[];
  /** 当前资源快照所属的工作区目录（null 表示尚未收到） */
  resourcesCwd: string | null;
  /** 活跃会话所属工作区目录（无活跃会话时为 null） */
  activeWorkspaceCwd: string | null;
  /** 当前活跃会话 ID（null 表示尚未建立） */
  activeSessionId: string | null;
  /** 切换活跃会话：视图已就绪时纯本地切换；未恢复的会话自动请求恢复；cwd 为会话所属目录（恢复请求携带） */
  activateSession: (id: string, cwd?: string) => void;
  /** 新建会话（后端创建后自动切换为活跃）；cwd 指定目标工作区（缺省 = 默认工作区） */
  newSession: (cwd?: string, workbench?: boolean) => void;
  /** 拉取工作区列表（web_request_workspaces） */
  requestWorkspaces: () => void;
  /** 注册新目录空间（web_add_workspace） */
  addWorkspace: (path: string) => void;
  /** 移除已注册目录空间（web_remove_workspace） */
  removeWorkspace: (path: string) => void;
  /** 拉取资源快照（web_request_resources，可指定会话/工作区；缺省 = 活跃会话） */
  requestResources: (sessionId?: string, cwd?: string) => void;
  /** 拉取文件树单层条目（web_request_file_tree；path 为工作区相对目录，缺省根；
   *  已有缓存且非 force 时跳过） */
  requestFileTree: (path?: string, force?: boolean) => void;
  /** 拉取 Git 状态快照（web_request_git_status） */
  requestGitStatus: () => void;
  /** 打开文件预览（web_read_file，内容视图；同视图同路径读取中直接忽略连点） */
  openFilePreview: (path: string) => void;
  /** 打开文件 diff 预览（web_file_diff，相对 HEAD 的变更视图） */
  openFileDiff: (path: string) => void;
  /** 关闭文件预览 */
  closeFilePreview: () => void;
  /** 拉取智能体与后台任务（web_request_agent_tasks，随活跃会话） */
  requestAgentTasks: () => void;
  /** 查看智能体/任务摘要（复用 /agent 指令，结果在预览面板展示） */
  viewAgentSummary: (id: string) => void;
  /** 拉取会话内修改文件列表（web_request_session_files，随活跃会话） */
  requestSessionFiles: () => void;
  /** 打开会话内修改文件预览（web_read_session_file；支持工作区外/非 Git 追踪的文件） */
  openSessionFile: (path: string) => void;
  /** 会话级内联选项（活跃视图） */
  inlineOptions: SelectRequestPayload | null;
  /** 设置活跃会话的内联选项（/rename 等前端本地弹出的选择框） */
  setInlineOptions: (payload: SelectRequestPayload | null) => void;
  // ---- agent 向导相关（全局）----
  /** agent 向导可选工具列表（来自 agent_wizard_init_response） */
  agentWizardTools: { name: string; description: string }[] | null;
  /** agent 向导可选模型列表（来自 agent_wizard_init_response，name 为 env_N.model_M 引用或 'inherit'） */
  agentWizardModels: AgentModelOption[] | null;
  /** LLM 生成的 agent 草稿（来自 agent_generate_response） */
  agentGenerated: { identifier: string; when_to_use: string; system_prompt: string } | null;
  /** agent 生成中标志 */
  agentGenerateLoading: boolean;
  /** agent 生成错误文本 */
  agentGenerateError: string | null;
  /** agent 向导提交结果（来自 agent_wizard_result） */
  agentWizardResult: { success: boolean; path?: string; errors?: Record<string, string>; error?: string } | null;
  /** 请求初始化 agent 向导：发 agent_wizard_init */
  sendAgentWizardInit: () => void;
  /** 请求 LLM 生成 agent 草稿：生成 request_id，发 agent_generate_request，置 loading */
  sendAgentGenerateRequest: (prompt: string, model: string) => void;
  /** 提交 agent 向导表单：发 agent_wizard_submit（项目级 cwd 指定目标工作区） */
  sendAgentWizardSubmit: (fields: Record<string, unknown>, scope: 'user' | 'project', cwd?: string) => void;
  /** 清空所有 agent 向导状态（关闭表单时调用） */
  clearAgentWizardState: () => void;
  // ---- agent 管理相关（设置表单 AgentsTab，全局）----
  /** 代理分组目录（来自 web_agents 推送） */
  agentCatalog: AgentCatalog | null;
  /** 代理目录拉取中 */
  agentCatalogLoading: boolean;
  /** 最近一次代理操作结果（来自 web_agent_op_result） */
  agentOpResult: { op: string; success: boolean; error?: string } | null;
  /** 拉取代理目录：发 web_request_agents */
  requestAgents: () => void;
  /** 更新代理配置（内置改 settings，用户级改 .md）：发 web_update_agent */
  updateAgent: (fields: Record<string, unknown>) => void;
  /** 删除用户创建的代理：发 web_delete_agent */
  deleteAgent: (fields: Record<string, unknown>) => void;
  /** 清除代理操作结果（UI 消费后调用） */
  clearAgentOpResult: () => void;
  /** 首次登录配置保存后清除 firstLogin 状态 */
  clearFirstLogin: () => void;
  deleteSessions: (sessionIds: string[], deleteAll?: boolean, cwd?: string) => void;
  clearModal: () => void;
  setBusyTrue: () => void;
  /** 乐观提交用户文本：立即渲染 user 消息（后端回执按文本去重），杜绝消息被吞/卡住 */
  optimisticSubmit: (line: string) => void;
  requestSelectCommand: (command: string) => void;
  setEffortValue: (value: string) => void;
  setModelValue: (value: string) => void;
  /** 发送请求（自动附带当前活跃会话 ID，无需调用方填写） */
  sendRequest: (payload: FrontendRequest) => void;
  // ---- Goal 状态栏相关（活跃视图）----
  /** goal_action 最近一次失败（GoalBar 行内显示；成功/新操作时清除） */
  goalActionError: { code: string; message: string } | null;
  /** 发送 GoalBar 操作（pause/resume/edit/clear）：CAS ref 从当前 goal 状态调用时读取 */
  sendGoalAction: (action: 'pause' | 'resume' | 'edit' | 'clear', objective?: string) => void;
  /** 清除 goal 操作错误（GoalBar 关闭错误提示时调用） */
  clearGoalActionError: () => void;
  /** 停止请求已发送、等待后端确认（按钮旋转动画），line_complete 后清除 */
  stopping: boolean;
  /** 发送停止请求（针对活跃会话，自动管理 stopping 状态与超时兜底） */
  sendStop: () => void;
  /** CAD 画布工作台文档（cad_canvas_update 推送；null = 未加载） */
  canvasDoc: CanvasDoc | null;
  /** 提交用户在画布上的整板编辑（web_canvas_update） */
  updateCanvasDoc: (doc: { nodes: CanvasDoc['nodes']; edges: CanvasDoc['edges'] }) => void;
  /** CAD 建模会话状态（cad_update 推送；null = 无数据） */
  cadState: CadUpdatePayload | null;
  /** 重取当前会话的画布文档（跨进程修改兜底） */
  refreshCanvas: () => void;
  /** 把 SolidWorks 主窗口置前（用户接管交互） */
  focusSolidWorks: () => void;
  /** 手动生成 SolidWorks 快照帧 */
  sendSnapshot: () => void;
  /** cad_connect 工具启动计数（>0 表示本次运行至少调用过一次连接） */
  cadConnectTick: number;
  clearStaticItems: () => void;
  setOnSelectRequest: (fn: ((payload: SelectRequestPayload) => void) | null) => void;
  setOnCommandResult: (fn: ((text: string, type: string, requestId?: string) => void) | null) => void;
  /** 注册版本更新提醒回调（update_available 事件触发，参数为最新版本号） */
  setOnUpdateAvailable: (fn: ((latestVersion: string) => void) | null) => void;
  /** 注册 rewind 回填回调（session_rewind 事件触发，参数为被回退的 user 消息） */
  setOnRewindRestored: (fn: ((text: string) => void) | null) => void;
  /** 注册 toast 通知回调（toast 事件触发：监管判定 / 音效 / 系统级通知透传由 App 决策） */
  setOnToast: (fn: ((payload: ToastPayload) => void) | null) => void;
}

/**
 * 生成唯一请求 ID（agent generate / 激活意图 token 用）
 *
 * 优先使用 crypto.randomUUID，不可用时回退到时间戳+随机串兜底。
 */
function genRequestId(prefix: string): string {
  return (typeof crypto !== 'undefined' && 'randomUUID' in crypto)
    ? crypto.randomUUID()
    : `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useWebSocketSession(url: string): WebSocketSessionState {
  // === 全局状态 ===
  const [status, setStatus] = useState<Record<string, unknown>>({});
  // status 的 ref 镜像：handleEvent 闭包内读取最新语言等字段（不随状态重建监听）
  const statusRef = useRef<Record<string, unknown>>({});
  useEffect(() => {
    statusRef.current = status;
  }, [status]);
  const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
  const [commands, setCommands] = useState<string[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerSnapshot[]>([]);
  const [skills, setSkills] = useState<SkillSnapshot[]>([]);
  const [plugins, setPlugins] = useState<PluginSnapshot[]>([]);
  const [rules, setRules] = useState<RuleSnapshot[]>([]);
  // === 右栏扩展：智能体与任务 / 文件树 / Git 状态 / 文件预览 ===
  const [agentTasks, setAgentTasks] = useState<AgentTaskItem[]>([]);
  const [fileTree, setFileTree] = useState<Record<string, FileTreeNode[]>>({});
  const [fileTreeLoadingPaths, setFileTreeLoadingPaths] = useState<string[]>([]);
  // 会话内修改文件列表（会话文件区块；随会话隔离，切会话清空后重拉）
  const [sessionFiles, setSessionFiles] = useState<SessionFileItem[]>([]);
  /** 会话文件拉取中（区块加载态） */
  const [sessionFilesLoading, setSessionFilesLoading] = useState(false);
  // @ 提及补全：响应直通订阅方（PromptInput 持有缓存），不设状态避免整页重渲染
  const fileMentionListenersRef = useRef<Set<(r: { requestId: string; query: string; candidates: FileMentionCandidate[] }) => void>>(new Set());
  const subscribeFileMentions = useCallback((cb: (r: { requestId: string; query: string; candidates: FileMentionCandidate[] }) => void): (() => void) => {
    fileMentionListenersRef.current.add(cb);
    return () => { fileMentionListenersRef.current.delete(cb); };
  }, []);
  const [gitStatus, setGitStatus] = useState<GitStatusSnapshot | null>(null);
  const [gitLoading, setGitLoading] = useState(false);
  // CAD 画布工作台文档（cad_canvas_update 推送 / ready 后 web_canvas_get 拉取；
  // 全局文档，按工作区真源在后端，多会话共享同一块画布）
  const [canvasDoc, setCanvasDoc] = useState<CanvasDoc | null>(null);
  // CAD 建模会话状态（cad_update 推送：状态/文档/特征树/最新快照帧）
  const [cadState, setCadState] = useState<CadUpdatePayload | null>(null);
  // cad_connect 工具启动计数（工作台浮动建模卡自动展开信号）
  const [cadConnectTick, setCadConnectTick] = useState(0);
  const [filePreview, setFilePreview] = useState<FileContentPayload | null>(null);
  const [filePreviewLoading, setFilePreviewLoading] = useState(false);
  const [modelOptions, setModelOptions] = useState<Option[]>([]);
  const [ready, setReady] = useState(false);
  /** 首帧引导中：ready 后首个会话内容（web_restore_completed）尚未呈现。
      期间用全屏遮罩覆盖，避免"连接→欢迎→恢复→欢迎"的时序翻转闪烁。 */
  const [bootstrapping, setBootstrapping] = useState(true);
  /** 新建会话等待中：newSession 发出后、后端 web_restore_completed 到达前，
      聊天区显示局部加载卡（跨目录首建需后端懒构建工作区 bundle，秒级耗时） */
  const [awaitingNewSession, setAwaitingNewSession] = useState(false);
  const [showThinking, setShowThinking] = useState(true);
  const [swarmTeammates, setSwarmTeammates] = useState<SwarmTeammateSnapshot[]>([]);
  const [swarmNotifications, setSwarmNotifications] = useState<SwarmNotificationSnapshot[]>([]);
  const [bgAgentLabel, setBgAgentLabel] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  /** 遮罩层连接错误（认证失败 / 后端不可达），onopen 与探测到可达时清空 */
  const [connectionError, setConnectionError] = useState<WebConnectionError | null>(null);
  /** 首次登录标识（后端 ready 事件携带，无 env_N 且无 working_directory 时为 true） */
  const [firstLogin, setFirstLogin] = useState(false);
  // 模型切换中（用于 Toolbar 显示加载动画）
  const [modelSwitching, setModelSwitching] = useState(false);

  // === 会话域状态（单一注册表：元数据 + 运行时合一，见 store/sessionStore）===
  const [sessionState, dispatchSession] = useReducer(sessionReducer, undefined, createInitialSessionState);
  // 会话域 ref 镜像：事件处理器（WS 闭包）与回调中读取最新值，避免陈旧闭包
  const sessionStateRef = useRef(sessionState);
  const viewsRef = useRef<Record<string, SessionRecord>>({});
  const activeSessionIdRef = useRef<string | null>(null);
  /** 会话域动作统一入口：同步 ref 镜像后 dispatch（reducer 为纯函数，结果一致） */
  const dispatch = useCallback((action: SessionAction): void => {
    const next = sessionReducer(sessionStateRef.current, action);
    sessionStateRef.current = next;
    viewsRef.current = next.sessions;
    activeSessionIdRef.current = next.activeId;
    dispatchSession(action);
  }, []);
  // 全局切换加载态：ensureSession 直接控制（目标空会话可能尚不存在、无记录可挂）
  const [ensureRestoring, setEnsureRestoring] = useState<string | null>(null);
  const ensureRestoringRef = useRef<string | null>(null);
  const activeSessionId = sessionState.activeId;
  // === 工作区（目录空间）状态 ===
  const [workspaces, setWorkspaces] = useState<WebWorkspaceItem[]>([]);
  const [resourcesCwd, setResourcesCwd] = useState<string | null>(null);
  // resourcesCwd 的 ref 镜像：事件处理器闭包内判断树/Git 快照归属工作区
  const resourcesCwdRef = useRef<string | null>(null);
  // 文件树正在加载的目录集合（ref 镜像，防同目录并发重复请求）
  const fileTreeLoadingRef = useRef<Set<string>>(new Set());
  // 文件预览正在读取的键（`kind|path`，防同视图同路径连点重复请求）
  const filePreviewKeyRef = useRef<string | null>(null);
  // 待展示的智能体摘要请求（viewAgentSummary 发起的 web_query request_id → 条目 id）
  const agentViewRef = useRef<{ requestId: string; id: string } | null>(null);
  // 会话级流式缓冲（assistant_delta 分桶）
  const buffersRef = useRef<Record<string, StreamBuffer>>({});
  const pendingToolCallsRef = useRef<Record<string, PendingToolCall[]>>({});
  const showThinkingRef = useRef(true);
  // 会话级 stop 超时定时器（sendStop 15s 兜底，line_complete 时清理）
  const stopTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  // 右栏统一刷新防抖定时器（工具链内连续变更工具只刷一次）
  const rightPanelRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 会话级恢复超时定时器（beginRestore 10s 兜底，restore_completed 时清理）
  const restoreTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  // 激活意图超时定时器（所有 new/ensure/fork/删除补位共用；按 token 精确作废）
  const awaitingNewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // === agent 向导状态（全局）===
  const [agentWizardTools, setAgentWizardTools] = useState<{ name: string; description: string }[] | null>(null);
  const [agentWizardModels, setAgentWizardModels] = useState<AgentModelOption[] | null>(null);
  const [agentGenerated, setAgentGenerated] = useState<{ identifier: string; when_to_use: string; system_prompt: string } | null>(null);
  const [agentGenerateLoading, setAgentGenerateLoading] = useState(false);
  const [agentGenerateError, setAgentGenerateError] = useState<string | null>(null);
  const [agentWizardResult, setAgentWizardResult] = useState<{ success: boolean; path?: string; errors?: Record<string, string>; error?: string } | null>(null);
  // === agent 管理状态（设置表单 AgentsTab，全局）===
  const [agentCatalog, setAgentCatalog] = useState<AgentCatalog | null>(null);
  const [agentCatalogLoading, setAgentCatalogLoading] = useState(false);
  const [agentOpResult, setAgentOpResult] = useState<{ op: string; success: boolean; error?: string } | null>(null);
  // GoalBar 操作结果（失败行内显示；成功/新操作时清除）
  const [goalActionError, setGoalActionError] = useState<{ code: string; message: string } | null>(null);
  /** agent generate 请求 ID 的 ref：handleEvent 闭包中读取当前活跃 ID，避免过期响应覆盖新请求状态 */
  const agentGenerateRequestIdRef = useRef<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  // 回调 refs：App 注入，用于 select_request 和 command_result 事件
  const onSelectRequestRef = useRef<((payload: SelectRequestPayload) => void) | null>(null);
  const onCommandResultRef = useRef<((text: string, type: string, requestId?: string) => void) | null>(null);
  /** rewind 被回退的 user 消息回调（App 注册，回填输入框） */
  const onRewindRestoredRef = useRef<((text: string) => void) | null>(null);
  const onUpdateAvailableRef = useRef<((latestVersion: string) => void) | null>(null);
  /** toast 事件回调（App 注册：监管判定 + 音效 + 系统级通知透传） */
  const onToastRef = useRef<((payload: ToastPayload) => void) | null>(null);
  const suppressCommandResultCountRef = useRef(0);
  const suppressTranscriptRef = useRef(false);
  // 乐观渲染的用户消息（按会话维护待确认 FIFO 队列，用于回执去重）。
  // 前端提交普通文本时立即本地渲染该 user 消息，杜绝"用户消息被吞/卡住"偶发问题；
  // 后端回执 transcript_item 时按文本精确匹配出队，快速连发相同文本也不会错配。
  const optimisticUserRef = useRef<Record<string, string[]>>({});

  const setOnSelectRequest = useCallback((fn: ((payload: SelectRequestPayload) => void) | null) => { onSelectRequestRef.current = fn; }, []);
  const setOnCommandResult = useCallback((fn: ((text: string, type: string) => void) | null) => { onCommandResultRef.current = fn; }, []);
  const setOnRewindRestored = useCallback((fn: ((text: string) => void) | null) => { onRewindRestoredRef.current = fn; }, []);
  const setOnUpdateAvailable = useCallback((fn: ((latestVersion: string) => void) | null) => { onUpdateAvailableRef.current = fn; }, []);
  const setOnToast = useCallback((fn: ((payload: ToastPayload) => void) | null) => { onToastRef.current = fn; }, []);

  /**
   * 不可变修补会话记录（dispatch 纯函数迁移；记录缺失时创建，
   * tombstone 中的已删会话拒绝重建——杜绝在途事件产生幻影视图）
   *
   * @param sid - 会话 ID
   * @param patch - 记录字段补丁
   */
  const patchView = useCallback((sid: string, patch: Partial<SessionRecord>) => {
    dispatch({ type: 'patch', sid, patch });
  }, [dispatch]);

  /**
   * 确保会话记录存在（未知会话 ID 惰性创建；tombstone 拒绝创建）
   *
   * @param sid - 会话 ID
   * @returns 会话记录（ref 中的最新值；tombstoned 时为 undefined）
   */
  const ensureView = useCallback((sid: string): SessionRecord | undefined => {
    dispatch({ type: 'ensure', sid });
    return sessionStateRef.current.sessions[sid];
  }, [dispatch]);

  /**
   * 登记激活意图：生成唯一 client_token 并写入 store。
   * 对应请求必须携带该 token；响应事件回显匹配时才执行激活。
   */
  const beginActivation = useCallback((kind: ActivationIntent['kind'], sessionId: string | null): string => {
    const token = genRequestId('act');
    dispatch({ type: 'setActivation', activation: { token, kind, sessionId } });
    return token;
  }, [dispatch]);

  /**
   * 激活意图超时兜底（10s）：响应事件丢失/后端异常时清除意图与等待态，
   * 避免"正在创建会话"加载卡永久挂起。仅当意图未被消费/覆盖（token
   * 仍匹配）时清除——用户中途的手动切换不受超时影响。
   */
  const armActivationTimeout = useCallback((token: string): void => {
    if (awaitingNewTimerRef.current) clearTimeout(awaitingNewTimerRef.current);
    awaitingNewTimerRef.current = setTimeout(() => {
      awaitingNewTimerRef.current = null;
      if (sessionStateRef.current.activation?.token === token) {
        dispatch({ type: 'setActivation', activation: null });
      }
      setAwaitingNewSession(false);
      ensureRestoringRef.current = null;
      setEnsureRestoring(null);
    }, 10000);
  }, [dispatch]);

  /** 清除激活意图与等待态（响应到达/手动本地切换时调用） */
  const settleActivation = useCallback((): void => {
    if (awaitingNewTimerRef.current) {
      clearTimeout(awaitingNewTimerRef.current);
      awaitingNewTimerRef.current = null;
    }
    setAwaitingNewSession(false);
    ensureRestoringRef.current = null;
    setEnsureRestoring(null);
  }, []);

  /**
   * 开始恢复会话（restoring 唯一入口）：置位 + 10s 超时兜底。
   * 任何路径（点击切换/初始推送/web_restore_started）都经此入口，
   * 杜绝"置 true 无超时"导致的加载动画永久挂起。
   */
  const beginRestore = useCallback((sid: string): void => {
    dispatch({ type: 'patch', sid, patch: { restoring: true } });
    const prev = restoreTimersRef.current[sid];
    if (prev) clearTimeout(prev);
    restoreTimersRef.current[sid] = setTimeout(() => {
      delete restoreTimersRef.current[sid];
      dispatch({ type: 'patch', sid, patch: { restoring: false } });
    }, 10000);
  }, [dispatch]);

  /** 结束恢复会话：清除超时兜底定时器（restoring 字段由主流程 patch 清除） */
  const clearRestoreTimer = useCallback((sid: string): void => {
    const prev = restoreTimersRef.current[sid];
    if (prev) {
      clearTimeout(prev);
      delete restoreTimersRef.current[sid];
    }
  }, []);

  // === 流式缓冲（按会话分桶）===

  const getBuffer = useCallback((sid: string): StreamBuffer => {
    let buf = buffersRef.current[sid];
    if (!buf) {
      buf = { pending: '', raw: '', reasoning: '', flushedForTool: false, timer: null };
      buffersRef.current[sid] = buf;
    }
    return buf;
  }, []);

  const flushAssistantDelta = useCallback((sid: string): void => {
    const buf = getBuffer(sid);
    const pending = buf.pending;
    if (!pending) return;
    buf.pending = '';
    buf.raw += pending;
    let displayText = buf.raw
      .replace(/<think\b[^>]*>[\s\S]*?<\/think\b[^>]*>/gi, '')
      .replace(/<\/think\b[^>]*>/gi, '')
      .replace(/<think\b[^>]*>/gi, '')
      .replace(/<th(?:i(?:n(?:k)?)?)?\s*$/i, '');
    patchView(sid, { assistantBuffer: displayText });
  }, [getBuffer, patchView]);

  const clearAssistantDelta = useCallback((sid: string): void => {
    const buf = getBuffer(sid);
    buf.pending = '';
    buf.raw = '';
    buf.reasoning = '';
    if (buf.timer) { clearTimeout(buf.timer); buf.timer = null; }
    patchView(sid, { assistantBuffer: '', streamingReasoning: '' });
  }, [getBuffer, patchView]);

  /** 向指定会话追加转录项 */
  const pushStatic = useCallback((sid: string, item: TranscriptItem): void => {
    const view = viewsRef.current[sid];
    if (!view) return;
    patchView(sid, { items: [...view.items, item] });
  }, [patchView]);

  // resourcesCwd ref 镜像 + 工作区切换失效：文件树与 Git 快照按目录归属，
  // 切换工作区（web_resources 的 cwd 变化）时清空缓存与加载态
  useEffect(() => {
    resourcesCwdRef.current = resourcesCwd;
    setFileTree({});
    setFileTreeLoadingPaths([]);
    setGitStatus(null);
    setGitLoading(false);
    fileTreeLoadingRef.current.clear();
  }, [resourcesCwd]);

  /** 发送原始请求（不注入 session_id，供内部使用）；类型化通道，禁止裸发未声明的请求 */
  const sendRaw = useCallback((payload: FrontendRequest): void => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(payload));
  }, []);

  /** 发送请求（自动附带当前活跃会话 ID） */
  const sendRequest = useCallback((payload: FrontendRequest): void => {
    // 显式 session_id 支持：侧边栏操作目标会话可能不是活跃会话
    // （如跨目录重命名），此时必须以目标会话 ID 路由到后端正确的工作区
    const explicit = 'session_id' in payload ? payload.session_id : undefined;
    const sid = explicit ?? activeSessionIdRef.current ?? undefined;
    sendRaw(sid ? ({ ...payload, session_id: sid } as FrontendRequest) : payload);
  }, [sendRaw]);

  /**
   * 停止请求（针对活跃会话）：按钮进入旋转动画，直到后端确认（line_complete）清除；
   * 15s 超时兜底（后端异常挂起时避免按钮永久旋转）
   */
  const sendStop = useCallback((): void => {
    const sid = activeSessionIdRef.current;
    if (!sid) return;
    patchView(sid, { stopping: true });
    sendRequest({ type: 'stop' });
    // 15s 超时兜底（后端异常挂起时避免按钮永久旋转）；重复 stop 先清旧定时器
    const prev = stopTimersRef.current[sid];
    if (prev) clearTimeout(prev);
    stopTimersRef.current[sid] = setTimeout(() => {
      delete stopTimersRef.current[sid];
      patchView(sid, { stopping: false });
    }, 15000);
  }, [patchView, sendRequest]);

  const setBusyTrue = useCallback((): void => {
    const sid = activeSessionIdRef.current;
    if (sid) patchView(sid, { busy: true });
  }, [patchView]);

  // 活跃会话变化（恢复/切换/新建）→ 重取该会话的画布文档与会话状态
  useEffect(() => {
    if (!activeSessionId) return;
    sendRequest({ type: 'web_canvas_get', session_id: activeSessionId });
    sendRequest({ type: 'web_cad_status' });
  }, [activeSessionId, sendRequest]);

  /** 提交用户在画布上的整板编辑（web_canvas_update；带当前会话 ID，后端按会话隔离） */
  const updateCanvasDoc = useCallback((doc: { nodes: CanvasDoc['nodes']; edges: CanvasDoc['edges'] }): void => {
    sendRequest({ type: 'web_canvas_update', canvas: doc, session_id: activeSessionIdRef.current ?? undefined });
  }, [sendRequest]);

  /** 重取当前会话的画布文档（web_canvas_get；切会话/聚焦时兜底跨进程修改） */
  const refreshCanvas = useCallback((): void => {
    const sid = activeSessionIdRef.current;
    sendRequest({ type: 'web_canvas_get', ...(sid ? { session_id: sid } : {}) });
  }, [sendRequest]);

  /** 把 SolidWorks 主窗口置前（web_cad_focus；用户接管交互桥） */
  const focusSolidWorks = useCallback((): void => {
    sendRequest({ type: 'web_cad_focus' });
  }, [sendRequest]);

  /** 手动生成 SolidWorks 快照帧（web_cad_snapshot） */
  const sendSnapshot = useCallback((): void => {
    sendRequest({ type: 'web_cad_snapshot' });
  }, [sendRequest]);

  /**
   * 乐观提交用户文本：立即在活跃会话中渲染一条 user 消息。
   *
   * 后端会先回执 user transcript_item 再进入流式，正常路径下本方法仅承担
   * "即时展示"角色；一旦回执在偶发竞态/丢包中丢失，该本地项仍保留，
   * 保证用户消息绝不"被吞"或导致界面卡住。回执到达时按文本去重（见
   * transcript_item 处理器），不会出现重复。仅处理文本通道的真实用户消息
   * （含以 / 开头的非命令文本，如未命中命令注册表的中文输入）。
   *
   * @param line - 用户输入的原始文本
   */
  const optimisticSubmit = useCallback((line: string): void => {
    const sid = activeSessionIdRef.current;
    if (!sid) return;
    const trimmed = line.trim();
    // 文本通道的真实用户消息一律乐观渲染（含以 / 开头的非命令文本）；
    // 命令由通道 1 分发（web_query/apply_select_command），不会走到这里
    if (!trimmed) return;
    (optimisticUserRef.current[sid] ??= []).push(trimmed);
    ensureView(sid);
    pushStatic(sid, { role: 'user', text: trimmed });
  }, [ensureView, pushStatic]);

  const clearStaticItems = useCallback((): void => {
    const sid = activeSessionIdRef.current;
    if (!sid) return;
    clearAssistantDelta(sid);
    patchView(sid, { items: [], pendingToolCalls: [] });
    pendingToolCallsRef.current[sid] = [];
  }, [clearAssistantDelta, patchView]);

  const deleteSessions = useCallback((
    sessionIds: string[],
    deleteAll: boolean = false,
    cwd?: string,
  ): void => {
    // 立即从注册表移除并立 tombstone（阻断在途事件重建幻影视图），
    // 后端推送 web_sessions 兜底同步：若删除被后端跳过（运行中会话），
    // 下次推送仍列出该会话 → sessionsPush 自动解除 tombstone 复活。
    // busy 会话必须与后端口径一致地跳过：本地先行移除会"消失又复活"，
    // 且活跃 busy 会话被误删后 activeId 会指向幻影（转录消失+转圈）
    const removed = deleteAll
      ? Object.values(sessionStateRef.current.sessions)
          .filter((r) => (!cwd || r.cwd === cwd) && !r.busy)
          .map((r) => r.id)
      : sessionIds;
    if (removed.length > 0) {
      dispatch({ type: 'remove', sids: removed });
      for (const sid of removed) {
        delete buffersRef.current[sid];
        delete pendingToolCallsRef.current[sid];
        delete optimisticUserRef.current[sid]; // 同步清理乐观待确认队列
        const stopTimer = stopTimersRef.current[sid];
        if (stopTimer) {
          clearTimeout(stopTimer);
          delete stopTimersRef.current[sid];
        }
        clearRestoreTimer(sid);
      }
    }

    // 发送删除请求到后端（携带目录限定 delete_all 范围）
    // 活跃会话确在删除范围内（delete_all 需活跃会话属于目标目录）时：
    // 后端会原子补位同类型新会话并推送 web_session_ready（回显 client_token）。
    // 登记 delete-fallback 激活意图：仅该补位响应可激活新会话；
    // 活跃会话不在范围时不会有补位响应，登记只会白等超时
    let token: string | undefined;
    const activeSid = activeSessionIdRef.current;
    const activeInScope = activeSid != null
      && (deleteAll
        ? !cwd || sessionStateRef.current.sessions[activeSid]?.cwd === cwd
        : sessionIds.includes(activeSid));
    if (activeSid && activeInScope) {
      token = beginActivation('delete-fallback', null);
      setAwaitingNewSession(true);
      armActivationTimeout(token);
    }
    sendRaw({
      type: 'web_delete_sessions',
      session_ids: sessionIds,
      delete_all: deleteAll,
      ...(cwd ? { cwd } : {}),
      ...(token ? { client_token: token } : {}),
    });
  }, [dispatch, clearRestoreTimer, beginActivation, armActivationTimeout, sendRaw]);

  const clearModal = useCallback((): void => {
    const sid = activeSessionIdRef.current;
    if (sid) patchView(sid, { modal: null });
  }, [patchView]);

  const requestSelectCommand = useCallback((command: string): void => {
    sendRequest({ type: 'select_command', command });
  }, [sendRequest]);

  const setEffortValue = useCallback((value: string): void => {
    sendRequest({ type: 'apply_select_command', command: 'effort', value });
  }, [sendRequest]);

  const setModelValue = useCallback((value: string): void => {
    sendRequest({ type: 'apply_select_command', command: 'model', value });
  }, [sendRequest]);

  /** 切换活跃会话：记录已就绪时纯本地切换；未恢复或已被后端淘汰的会话自动请求恢复 */
  const activateSession = useCallback((id: string, cwd?: string) => {
    const rec = sessionStateRef.current.sessions[id];
    // 用户显式切换 = 最后操作为准：先作废在途意图并清除其等待态
    // （"正在创建会话"卡/输入禁用不得覆盖到新目标会话上）
    settleActivation();
    if (!rec || !rec.materialized || !rec.inMemory) {
      // 记录未就绪或后端已淘汰运行时（in_memory=false）：
      // 必须重新恢复，否则提交请求会因后端无此会话而静默丢弃。
      // 登记 restore 激活意图：仅回显该 token 的 web_restore_completed 可完成激活
      const token = beginActivation('restore', id);
      dispatch({ type: 'activate', sid: id });
      // 记录可能尚未存在（如页面刷新后首次点击该会话），先 ensure 再置恢复中
      dispatch({ type: 'ensure', sid: id, cwd });
      if (cwd) patchView(id, { cwd });
      beginRestore(id);
      sendRaw({ type: 'web_restore_session', session_id: id, ...(cwd ? { cwd } : {}), client_token: token });
      // 意图超时兜底：恢复响应丢失时作废意图（restoring 本身由 beginRestore 超时兜底）
      armActivationTimeout(token);
    } else {
      // 记录已就绪：纯本地切换，作废任何在途激活意图
      dispatch({ type: 'setActivation', activation: null });
      dispatch({ type: 'activate', sid: id });
      if (cwd) patchView(id, { cwd });
      clearRestoreTimer(id);
      // 右栏资源联动由 activeSessionId 变化的统一刷新 effect 承担
      // （覆盖资源 / Git / 文件树根 / 智能体任务），此处不再单独发请求
    }
  }, [beginActivation, armActivationTimeout, settleActivation, dispatch, patchView, beginRestore, clearRestoreTimer, sendRaw]);

  /** 确保存在指定类型的活跃会话：后端原子判定（同类型活跃 → 只同步；
   *  否则复用最近的同类型会话；再没有 → 创建）。进入等待态直到
   *  web_session_ready（回显 client_token）到达或超时。前端不做任何类型推断。 */
  const ensureSession = useCallback((workbench: boolean) => {
    const token = beginActivation('ensure', null);
    setAwaitingNewSession(true);
    // 视图切换加载态与 newSession 一致：ChatArea 显示"正在创建会话"，
    // web_session_ready（后端 ensure 必发）到达后由统一处理器清除
    ensureRestoringRef.current = '__pending_new__';
    setEnsureRestoring('__pending_new__');
    armActivationTimeout(token);
    sendRaw({ type: 'web_ensure_session', workbench, client_token: token });
  }, [beginActivation, armActivationTimeout, sendRaw]);

  /** 新建会话：后端创建后通过 web_session_ready（回显 client_token）自动切换为活跃；
   *  cwd 指定目标工作区。发出请求即进入等待态（聊天区局部加载卡即时反馈），
   *  10s 超时兜底——跨目录首建时后端懒构建工作区 bundle 耗秒级，不能无反馈 */
  const newSession = useCallback((cwd?: string, workbench?: boolean) => {
    const token = beginActivation('new', null);
    setAwaitingNewSession(true);
    armActivationTimeout(token);
    sendRaw({ type: 'web_new_session', ...(cwd ? { cwd } : {}), ...(workbench ? { workbench: true } : {}), client_token: token });
  }, [beginActivation, armActivationTimeout, sendRaw]);

  /** 拉取工作区列表 */
  const requestWorkspaces = useCallback((): void => {
    sendRaw({ type: 'web_request_workspaces' });
  }, [sendRaw]);

  /** 注册新目录空间（后端校验并推送 web_workspaces + web_sessions） */
  const addWorkspace = useCallback((path: string): void => {
    sendRaw({ type: 'web_add_workspace', path });
  }, [sendRaw]);

  /** 移除已注册目录空间（默认目录不可移除） */
  const removeWorkspace = useCallback((path: string): void => {
    sendRaw({ type: 'web_remove_workspace', path });
  }, [sendRaw]);

  /** 拉取资源快照（缺省 = 活跃会话所在工作区） */
  const requestResources = useCallback((sessionId?: string, cwd?: string): void => {
    sendRaw({
      type: 'web_request_resources',
      ...(sessionId ? { session_id: sessionId } : {}),
      ...(cwd ? { cwd } : {}),
    });
  }, [sendRaw]);

  /** 拉取文件树单层条目（path 为工作区相对目录，'' 为根；同目录加载中去重复请求。
   *  请求显式绑定当前活跃会话，后端按 session_id 路由到目标工作区，避免本地切会话后
   *  仍按后端旧活跃会话取到上一个目录的目录树 */
  const requestFileTree = useCallback((path?: string, force?: boolean): void => {
    const dir = path ?? '';
    if (!force && fileTreeLoadingRef.current.has(dir)) return;
    fileTreeLoadingRef.current.add(dir);
    setFileTreeLoadingPaths((prev) => (prev.includes(dir) ? prev : [...prev, dir]));
    sendRaw({
      type: 'web_request_file_tree',
      ...(dir ? { path: dir } : {}),
      session_id: activeSessionIdRef.current ?? undefined,
    });
  }, [sendRaw]);

  /** 拉取 Git 状态快照（显式绑定当前活跃会话，同文件树） */
  const requestGitStatus = useCallback((): void => {
    setGitLoading(true);
    sendRaw({ type: 'web_request_git_status', session_id: activeSessionIdRef.current ?? undefined });
  }, [sendRaw]);

  /** 拉取 @ 提及补全候选（requestId 由调用方生成，响应原样回显用于丢弃过期结果） */
  const requestFileMentions = useCallback((query: string, requestId: string): void => {
    sendRaw({
      type: 'web_request_file_mentions',
      query,
      request_id: requestId,
      session_id: activeSessionIdRef.current ?? undefined,
    });
  }, [sendRaw]);

  /** 打开文件预览（内容视图；同视图同路径读取中直接忽略连点；
   *  显式绑定当前活跃会话，避免本地切会话后读到上一个会话目录的文件） */
  const openFilePreview = useCallback((path: string): void => {
    const key = `content|${path}`;
    if (filePreviewKeyRef.current === key) return;
    filePreviewKeyRef.current = key;
    setFilePreviewLoading(true);
    setFilePreview({ path });
    sendRaw({ type: 'web_read_file', path, session_id: activeSessionIdRef.current ?? undefined });
  }, [sendRaw]);

  /** 打开文件 diff 预览（相对 HEAD 的变更视图；同样绑定当前活跃会话） */
  const openFileDiff = useCallback((path: string): void => {
    const key = `diff|${path}`;
    if (filePreviewKeyRef.current === key) return;
    filePreviewKeyRef.current = key;
    setFilePreviewLoading(true);
    setFilePreview({ path, kind: 'diff' });
    sendRaw({ type: 'web_file_diff', path, session_id: activeSessionIdRef.current ?? undefined });
  }, [sendRaw]);

  /** 关闭文件预览 */
  const closeFilePreview = useCallback((): void => {
    filePreviewKeyRef.current = null;
    agentViewRef.current = null;
    setFilePreviewLoading(false);
    setFilePreview(null);
  }, []);

  /** 拉取智能体与后台任务（随活跃会话；切会话后由统一刷新触发重拉） */
  const requestAgentTasks = useCallback((): void => {
    sendRequest({ type: 'web_request_agent_tasks' });
  }, [sendRequest]);

  /** 拉取会话内修改文件列表（随活跃会话；显式绑定会话，切会话后由统一刷新重拉） */
  const requestSessionFiles = useCallback((): void => {
    setSessionFilesLoading(true);
    sendRaw({ type: 'web_request_session_files', session_id: activeSessionIdRef.current ?? undefined });
  }, [sendRaw]);

  /**
   * 加载更早的轮次分页（长会话导航跳转未载入轮次）
   *
   * 请求携带当前已载入最小轮号；响应 web_history 前插转录并前移边界。
   * loadingHistory 防重（在途时跳过）；每次请求重置兜底计时器（10s
   * 超时清除加载态），上一次的超时不清除新请求的加载态。
   */
  const historyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestHistory = useCallback((): void => {
    const sid = activeSessionIdRef.current;
    if (!sid) return;
    const view = viewsRef.current[sid];
    if (!view || view.loadingHistory) return;
    // 无后端大纲（本地新建/rewind 后）或已全载入：无需分页
    if (!view.turnOutline || (view.firstLoadedTurn ?? 1) <= 1) return;
    patchView(sid, { loadingHistory: true });
    sendRaw({
      type: 'web_request_history',
      before_turn: view.firstLoadedTurn ?? 1,
      session_id: sid,
    });
    if (historyTimerRef.current) clearTimeout(historyTimerRef.current);
    historyTimerRef.current = setTimeout(
      () => patchView(sid, { loadingHistory: false }), 10000);
  }, [patchView, sendRaw]);

  /**
   * 分叉当前会话（可截断到前 N 轮）
   *
   * 后端复制源会话并物化新会话后推 web_restore_completed（分页载荷，
   * 回显 client_token），前端据此自动切换到新会话视图；源会话不受影响。
   * fork 激活意图的 token 保证：fork 失败/超时后，迟到的其他
   * restore_completed 不会把用户拽到错误的会话。
   */
  const forkSession = useCallback((turns?: number): void => {
    const sid = activeSessionIdRef.current;
    if (!sid) return;
    const token = beginActivation('fork', null);
    sendRaw({
      type: 'web_fork_session',
      session_id: sid,
      ...(turns != null ? { turns } : {}),
      client_token: token,
    });
    // 10s 兜底：fork 失败（后端异常/会话丢失）没有明确的失败事件，
    // 统一由激活意图超时清理
    armActivationTimeout(token);
  }, [beginActivation, armActivationTimeout, sendRaw]);

  /** 打开会话内修改文件预览（内容视图；支持工作区外/非 Git 追踪的文件；
   *  同样绑定当前活跃会话，同视图同路径读取中忽略连点） */
  const openSessionFile = useCallback((path: string): void => {
    const key = `content|${path}`;
    if (filePreviewKeyRef.current === key) return;
    filePreviewKeyRef.current = key;
    setFilePreviewLoading(true);
    setFilePreview({ path });
    sendRaw({ type: 'web_read_session_file', path, session_id: activeSessionIdRef.current ?? undefined });
  }, [sendRaw]);

  /**
   * 统一刷新右栏数据（资源 + Git + 文件树根 + 智能体任务 + 会话文件）
   *
   * 覆盖"切换目录 / 切换会话 / 调用变更工具"三类触发场景，作为唯一
   * 刷新入口统一管理。防抖合并：工具链内连续调用（多个变更工具先后
   * 完成）只触发一次。只覆盖数据源本身、不清空已有缓存，避免刷新
   * 瞬间出现空态闪烁（无感）。
   *
   * @returns 无返回值
   */
  const refreshRightPanel = useCallback((): void => {
    if (rightPanelRefreshTimerRef.current) clearTimeout(rightPanelRefreshTimerRef.current);
    rightPanelRefreshTimerRef.current = setTimeout(() => {
      rightPanelRefreshTimerRef.current = null;
      const sid = activeSessionIdRef.current ?? undefined;
      requestResources(sid);
      requestGitStatus();
      requestAgentTasks();
      requestFileTree(''); // 根目录（请求内部已绑定会话）
      requestSessionFiles();
    }, 150);
  }, [requestResources, requestGitStatus, requestAgentTasks, requestFileTree, requestSessionFiles]);

  // 切换会话 / 切换目录（新建会话）时统一刷新右栏：资源随目标会话工作区
  // 联动；跨目录时 Git/文件树由 resourcesCwd 变化的缓存失效 + 区块自拉取
  // 兜底（GitSection/FileTreeSection 各自 effect），无感更新、不抖动
  // （清空策略见下方活跃会话切换 effect：按目录区分全量/会话级清理）
  useEffect(() => {
    if (activeSessionId) refreshRightPanel();
  }, [activeSessionId, refreshRightPanel]);

  /**
   * 清空会话隔离数据（agentTasks / sessionFiles）
   *
   * 切换会话（无论是否跨目录）都需要清理的数据：它们按会话隔离，
   * 残留会导致新会话显示上一会话的任务与变更文件。
   *
   * @returns 无返回值
   */
  const clearSessionScopedData = useCallback((): void => {
    setAgentTasks([]);
    setSessionFiles([]);
    setSessionFilesLoading(false);
  }, []);

  /**
   * 清空右栏目录相关数据（置于未加载态）
   *
   * 仅在切换工作区目录（跨 cwd）时由活跃会话切换逻辑调用，随后
   * refreshRightPanel 重拉新目录数据。避免跨目录后、新数据到达前右栏
   * 残留上一目录的资源快照（skills/mcp/plugins/rules、文件树与 Git 状态）。
   * 同目录切会话不清这些共享缓存（数据相同，清了只会闪占位符）。
   *
   * @returns 无返回值
   */
  const resetWorkspaceResources = useCallback((): void => {
    setSkills([]);
    setMcpServers([]);
    setPlugins([]);
    setRules([]);
    clearSessionScopedData();
    setFileTree({});
    setFileTreeLoadingPaths([]);
    setGitStatus(null);
    setGitLoading(false);
    fileTreeLoadingRef.current.clear();
  }, [clearSessionScopedData]);

  // 上次活跃会话的工作区目录：切换时判断跨目录（决定全量清空还是仅清会话数据）
  const prevActiveCwdRef = useRef<string | null>(null);

  // 活跃会话切换的清空策略（与上方 refreshRightPanel 同一触发源，分置以
  // 满足声明顺序）：跨目录全量清空（防串档）；同目录仅清会话隔离数据
  // （agentTasks/sessionFiles），保留文件树/Git/资源缓存——数据
  // 相同，清了只会让区块闪占位符（切换流畅性）。
  useEffect(() => {
    if (!activeSessionId) return;
    const nextCwd = viewsRef.current[activeSessionId]?.cwd ?? null;
    if (prevActiveCwdRef.current !== null) {
      if (prevActiveCwdRef.current !== nextCwd) resetWorkspaceResources();
      else clearSessionScopedData();
    }
    prevActiveCwdRef.current = nextCwd;
  }, [activeSessionId, resetWorkspaceResources, clearSessionScopedData]);

  // 组件卸载时清理右栏刷新防抖定时器
  useEffect(() => {
    return () => {
      if (rightPanelRefreshTimerRef.current) {
        clearTimeout(rightPanelRefreshTimerRef.current);
        rightPanelRefreshTimerRef.current = null;
      }
    };
  }, []);

  /** 查看智能体/任务摘要：复用 /agent 指令（web_query），结果路由到预览面板 */
  const viewAgentSummary = useCallback((id: string): void => {
    const requestId = `agentview-${id}-${Date.now()}`;
    agentViewRef.current = { requestId, id };
    filePreviewKeyRef.current = null;
    setFilePreviewLoading(true);
    setFilePreview({ path: `${id} · 摘要` });
    sendRequest({ type: 'web_query', command: 'agent', args: id, request_id: requestId });
  }, [sendRequest]);

  const setInlineOptions = useCallback((payload: SelectRequestPayload | null) => {
    const sid = activeSessionIdRef.current;
    if (sid) patchView(sid, { inlineOptions: payload });
  }, [patchView]);

  /** 发送 GoalBar 操作（CAS ref 从当前会话 goal 状态调用时读取） */
  const sendGoalAction = useCallback(
    (action: 'pause' | 'resume' | 'edit' | 'clear', objective?: string): void => {
      const sid = activeSessionIdRef.current;
      if (!sid) return;
      const view = viewsRef.current[sid];
      const goal = view?.status?.goal as GoalStatus | null | undefined;
      if (!goal) {
        setGoalActionError({ code: 'no-current-goal', message: 'no current goal to mutate' });
        return;
      }
      setGoalActionError(null);
      sendRequest({
        type: 'goal_action',
        goal_action: action,
        goal_id: goal.id,
        revision: goal.revision,
        ...(action === 'edit' && objective ? { objective } : {}),
      });
    },
    [sendRequest],
  );

  /** 清除 goal 操作错误（GoalBar 关闭错误提示时调用） */
  const clearGoalActionError = useCallback((): void => {
    setGoalActionError(null);
  }, []);

  /** 请求初始化 agent 向导（全局） */
  const sendAgentWizardInit = useCallback((): void => {
    sendRequest({ type: 'agent_wizard_init' });
  }, [sendRequest]);

  /** 请求 LLM 生成 agent 草稿（全局表单，使用活跃会话引擎） */
  const sendAgentGenerateRequest = useCallback((prompt: string, model: string): void => {
    const requestId = genRequestId('agent');
    agentGenerateRequestIdRef.current = requestId;
    setAgentGenerateLoading(true);
    setAgentGenerateError(null);
    setAgentGenerated(null);
    sendRequest({ type: 'agent_generate_request', prompt, model, request_id: requestId });
  }, [sendRequest]);

  /** 提交 agent 向导表单（全局；项目级 cwd 指定目标工作区） */
  const sendAgentWizardSubmit = useCallback((fields: Record<string, unknown>, scope: 'user' | 'project', cwd?: string): void => {
    sendRequest({ type: 'agent_wizard_submit', fields, scope, cwd: cwd || undefined });
  }, [sendRequest]);

  /** 清空所有 agent 向导相关状态（关闭表单时调用） */
  const clearAgentWizardState = useCallback((): void => {
    agentGenerateRequestIdRef.current = null;
    setAgentWizardTools(null);
    setAgentWizardModels(null);
    setAgentGenerated(null);
    setAgentWizardResult(null);
    setAgentGenerateLoading(false);
    setAgentGenerateError(null);
  }, []);

  // === agent 管理（设置表单 AgentsTab）===

  /** 拉取代理目录（内置/全局/项目级分组） */
  const requestAgents = useCallback((): void => {
    setAgentCatalogLoading(true);
    sendRequest({ type: 'web_request_agents' });
  }, [sendRequest]);

  /** 更新代理配置（内置改 settings.agent_models，用户级改 .md） */
  const updateAgent = useCallback((fields: Record<string, unknown>): void => {
    sendRequest({ type: 'web_update_agent', fields });
  }, [sendRequest]);

  /** 删除用户创建的代理定义文件 */
  const deleteAgent = useCallback((fields: Record<string, unknown>): void => {
    sendRequest({ type: 'web_delete_agent', fields });
  }, [sendRequest]);

  /** 清除代理操作结果（UI 消费后调用） */
  const clearAgentOpResult = useCallback((): void => {
    setAgentOpResult(null);
  }, []);

  useEffect(() => {
    // 断线自动重连：后端重启/网络抖动后指数退避重建连接（1s→2s→…→30s 上限）。
    // 重连成功后后端重走 ready → web_sessions → web_restore_completed 推送链，
    // 会话列表与活跃会话自动再同步，无需刷新页面。
    let disposed = false;
    let retryCount = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    // 后端主动 shutdown（用户停机）：不再重连——对已停机的服务无限退避重试无意义
    let shuttingDown = false;

    const connect = (): void => {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        retryCount = 0;
        setConnected(true);
        setConnectionError(null);
      };
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        setConnected(false);
        setReady(false);
        setFirstLogin(false);
        // 断线时探测后端：区分「认证失败」与「服务不可达」，遮罩展示解决方式。
        // 认证失败（auth）不再重连——凭据问题重连无意义；其余情况一律重连
        void probeBackendError().then((err) => {
          setConnectionError(err);
          if (err?.kind === 'auth') return;
          if (!disposed && !shuttingDown) {
            const delay = Math.min(30000, 1000 * 2 ** retryCount);
            retryCount += 1;
            reconnectTimer = setTimeout(connect, delay);
          }
        });
        // 断线统一清理会话域等待态：激活意图/恢复中/新建等待全部作废
        // （重连后由后端推送重建语义，杜绝加载卡永久挂起）
        if (awaitingNewTimerRef.current) {
          clearTimeout(awaitingNewTimerRef.current);
          awaitingNewTimerRef.current = null;
        }
        setAwaitingNewSession(false);
        ensureRestoringRef.current = null;
        setEnsureRestoring(null);
        for (const sid of Object.keys(restoreTimersRef.current)) {
          clearTimeout(restoreTimersRef.current[sid]);
          delete restoreTimersRef.current[sid];
        }
        dispatch({ type: 'connectionClosed' });
      };
      ws.onerror = () => {
        setConnected(false);
        // onerror 与 onclose 常成对触发，探测在 onclose 统一进行
      };
      ws.onmessage = (event) => {
        let parsed: BackendEvent;
        try { parsed = JSON.parse(event.data as string) as BackendEvent; } catch { return; }
        handleEvent(parsed);
      };
    };
    connect();

    function handleEvent(evt: BackendEvent): void {
      // === 状态 ===
      if (evt.type === 'ready') {
        setReady(true);
        setFirstLogin(evt.first_login ?? false);
        setStatus(evt.state ?? {});
        const st = evt.state?.show_thinking;
        if (typeof st === 'boolean') { setShowThinking(st); showThinkingRef.current = st; }
        setTasks(evt.tasks ?? []);
        setCommands(evt.commands ?? []);
        setMcpServers((evt.mcp_servers as McpServerSnapshot[]) ?? []);
        // CAD 画布文档与会话状态：等 web_restore_completed 设置活跃会话后
        // 再拉取（携带 session_id，后端按会话返回正确画布）
        // 会话列表 / 活跃会话转录由后端随后的 web_sessions + web_restore_completed 驱动
        return;
      }
      if (evt.type === 'state_snapshot') {
        const newState = evt.state ?? {};
        // 会话级快照（goal_action 成功后按会话回推）：会话键合并进对应视图，
        // 避免某会话的 goal/上下文数据污染全局 status（多会话张冠李戴）
        if (evt.session_id) {
          const sidState = evt.session_id;
          ensureView(sidState);
          const currentView = viewsRef.current[sidState];
          if (currentView) {
            const patch: Record<string, unknown> = {};
            for (const key of Object.keys(newState)) {
              if (SESSION_STATUS_KEYS.has(key)) patch[key] = newState[key];
            }
            if (Object.keys(patch).length > 0) {
              patchView(sidState, { status: { ...currentView.status, ...patch } });
            }
          }
          return;
        }
        // 全局状态快照：工具栏级字段（model/effort/language 等）
        setStatus(newState);
        const st = newState.show_thinking;
        if (typeof st === 'boolean') { setShowThinking(st); showThinkingRef.current = st; }
        // 注意：不外覆盖 MCP 服务器列表。state_snapshot 的 mcp_servers 取自后端
        // 活跃会话 bundle，前端本地切会话后该活跃可能滞后；而 MCP 应与其他资源
        // 一致，统一由绑定会话的 web_resources 驱动，避免被全局快照拉回旧目录状态。
        return;
      }
      if (evt.type === 'tasks_snapshot') { setTasks(evt.tasks ?? []); return; }
      if (evt.type === 'update_available' && evt.latest_version) {
        onUpdateAvailableRef.current?.(evt.latest_version);
        return;
      }

      // === 会话路由（携带 session_id 的会话级事件）===
      // 归属守卫：会话级事件必须携带 session_id（后端经 _make_render_event /
      // _emit(session_id=...) 全量标记）；缺失说明后端路由缺陷，丢弃并告警，
      // 绝不静默落入活跃会话（多会话并发下的串话通道）。
      // 白名单内的事件类型保留活跃会话回退（历史兼容：后端个别路径未标记）。
      if (!evt.session_id && SESSION_SCOPED_EVENTS.has(evt.type)) {
        console.warn(`[session] 丢弃缺失 session_id 的会话级事件: ${evt.type}`);
        return;
      }
      const sid = evt.session_id
        ?? (ACTIVE_FALLBACK_EVENTS.has(evt.type) ? activeSessionIdRef.current : null);
      if (sid) {
        // tombstone 中的已删会话：在途事件一律丢弃，不重建幻影视图
        if (sessionStateRef.current.tombstones[sid] !== undefined) return;
        ensureView(sid);

        // 流式
        if (evt.type === 'assistant_delta') {
          if (evt.reasoning) {
            const buf = getBuffer(sid);
            buf.reasoning += evt.reasoning;
            // reasoning 正在流式：大脑脉冲动画开启
            patchView(sid, { busy: true, streamingReasoning: buf.reasoning, reasoningStreaming: true });
          } else {
            // text 增量（reasoning 已流完或未开始）：大脑脉冲停止
            patchView(sid, { busy: true, reasoningStreaming: false });
          }
          const delta = evt.message ?? '';
          if (delta) {
            const buf = getBuffer(sid);
            buf.pending += delta;
            if (buf.pending.length >= ASSISTANT_DELTA_FLUSH_CHARS) {
              flushAssistantDelta(sid);
            } else if (!buf.timer) {
              buf.timer = setTimeout(() => { buf.timer = null; flushAssistantDelta(sid); }, ASSISTANT_DELTA_FLUSH_MS);
            }
          }
          return;
        }
        if (evt.type === 'assistant_complete') {
          const buf = getBuffer(sid);
          if (buf.timer) { clearTimeout(buf.timer); buf.timer = null; }
          flushAssistantDelta(sid);
          if (!buf.flushedForTool) {
            const text = evt.message ?? buf.raw;
            const reasoning = (evt.reasoning ?? buf.reasoning) || undefined;
            if (text.trim() || (reasoning ?? '').trim()) {
              pushStatic(sid, { role: 'assistant', text: stripToolCallLines(text), reasoning });
            }
          }
          buf.flushedForTool = false;
          clearAssistantDelta(sid);
          // reasoning 流式结束，大脑脉冲停止
          const completePatch: { reasoningStreaming: boolean; busy?: boolean } = { reasoningStreaming: false };
          // 最终答案（不跟随工具链）时立即退出 busy，无需等待 line_complete；
          // 中间步骤（tool_chain_follows=true）保持 busy，避免工具链期间闪烁
          if (evt.tool_chain_follows === false) completePatch.busy = false;
          patchView(sid, completePatch);
          return;
        }
        if (evt.type === 'line_complete') {
          clearAssistantDelta(sid);
          pendingToolCallsRef.current[sid] = [];
          patchView(sid, { pendingToolCalls: [], busy: false });
          // 停止确认：清除按钮旋转动画与超时定时器
          const stopTimer = stopTimersRef.current[sid];
          if (stopTimer) {
            clearTimeout(stopTimer);
            delete stopTimersRef.current[sid];
          }
          patchView(sid, { stopping: false });
          return;
        }

        // 转录
        if (evt.type === 'transcript_item' && evt.item) {
          // 过滤命令产物：后端按命令注册表打 is_command 标记（如 /context set 512000），
          // 不能按文本以 / 开头判断——用户消息也可能以 / 开头（如 "/xxx 帮我看看"），
          // 按前缀过滤会误吞真实消息
          if (evt.item.role === 'user' && evt.item.is_command) return;
          // 过滤后台任务完成通知（<task-notification> XML）：注入给 LLM 的系统消息，
          // 不应作为真实用户消息显示
          if (evt.item.role === 'user' && evt.item.text.startsWith('<task-notification>')) return;
          if (suppressTranscriptRef.current) return;
          // 乐观渲染去重：本 user 项与待确认队列中的文本**精确匹配**时视为回执，
          // 出队并跳过（已在乐观阶段渲染）。FIFO 队列支持快速连发相同文本——
          // 队列清空后到达的重复文本按新消息正常渲染，不错配
          if (evt.item.role === 'user') {
            const queue = optimisticUserRef.current[sid];
            if (queue && queue.length > 0) {
              const idx = queue.indexOf(evt.item.text);
              if (idx !== -1) {
                queue.splice(idx, 1);
                return;
              }
            }
          }
          pushStatic(sid, evt.item);
          return;
        }

        // 工具
        if ((evt.type === 'tool_started' || evt.type === 'tool_completed') && evt.item) {
          if (evt.type === 'tool_started') {
            if (evt.tool_name === 'cad_connect') setCadConnectTick((n) => n + 1);
            const buf = getBuffer(sid);
            if (buf.raw.trim() || buf.pending || buf.reasoning.trim()) {
              if (buf.timer) { clearTimeout(buf.timer); buf.timer = null; }
              flushAssistantDelta(sid);
              const text = buf.raw;
              const reasoning = buf.reasoning || undefined;
              if (text.trim() || (reasoning ?? '').trim()) {
                pushStatic(sid, { role: 'assistant', text: stripToolCallLines(text), reasoning });
              }
              clearAssistantDelta(sid);
              buf.flushedForTool = true;
            }
            // reasoning 流式结束（工具调用前的思考已完整输出），大脑脉冲停止
            patchView(sid, { reasoningStreaming: false });
            const toolInput = evt.item.tool_input ?? evt.tool_input;
            const toolUseId = evt.item.tool_use_id ?? evt.tool_use_id ?? '';
            const pendingList = pendingToolCallsRef.current[sid] ?? [];
            pendingToolCallsRef.current[sid] = [...pendingList, {
              tool_name: evt.item.tool_name ?? evt.tool_name ?? 'tool', tool_use_id: toolUseId,
              tool_input: (toolInput && Object.keys(toolInput as Record<string, unknown>).length > 0) ? toolInput as Record<string, unknown> : undefined,
            }];
            patchView(sid, { busy: true, pendingToolCalls: pendingToolCallsRef.current[sid] });
            return;
          }
          const toolUseId = evt.item.tool_use_id ?? evt.tool_use_id ?? '';
          const pendingList = pendingToolCallsRef.current[sid] ?? [];
          const pendingIdx = pendingList.findIndex((p) => p.tool_use_id === toolUseId);
          let toolName = evt.item.tool_name ?? evt.tool_name ?? 'tool';
          let toolInput = (evt.item.tool_input ?? undefined) as Record<string, unknown> | undefined;
          // 完成时从 pending 保留流式进度（agent 思考过程），随 tool_result 折叠展示
          let progressMessages: Array<{message: string; type?: string}> | undefined;
          if (pendingIdx !== -1) {
            const pending = pendingList[pendingIdx]!;
            toolName = pending.tool_name || toolName; toolInput = pending.tool_input || toolInput;
            progressMessages = pending.progressMessages;
            pendingToolCallsRef.current[sid] = pendingList.filter((p) => p.tool_use_id !== toolUseId);
            patchView(sid, { pendingToolCalls: pendingToolCallsRef.current[sid] });
          }
          pushStatic(sid, { role: 'tool', text: toolName, tool_name: toolName, tool_input: toolInput, tool_use_id: toolUseId || undefined });
          pushStatic(sid, { ...evt.item, role: 'tool_result', tool_name: toolName,
            tool_use_id: toolUseId || undefined, is_error: (evt.item.is_error ?? evt.is_error ?? undefined) as boolean | undefined,
            progress_messages: progressMessages,
            // 变更工具的结构化统计（增减行数等）：随条目持久到转录，
            // 工具气泡据此显示 +N/-M（恢复场景无此字段，前端回退文本解析）
            structured_output: (evt.structured_output ?? undefined) as Record<string, unknown> | undefined });
          // 变更类工具执行完成后统一刷新右栏（文件树 / Git / 资源快照）；
          // 仅活跃会话触发的工具才刷新（后台 agent 的变更不联动活跃会话数据）
          if (CHANGE_TOOLS.has(toolName) && sid === activeSessionIdRef.current) refreshRightPanel();
          return;
        }
        if (evt.type === 'tool_input_updated') {
          const uid = evt.tool_use_id;
          const pendingList = pendingToolCallsRef.current[sid] ?? [];
          pendingToolCallsRef.current[sid] = pendingList.map((p) => p.tool_use_id === uid ? { ...p, tool_input: evt.tool_input ?? undefined } : p);
          patchView(sid, { pendingToolCalls: pendingToolCallsRef.current[sid] });
          return;
        }
        // 流式进度消息：累积到对应 pendingToolCall 的 progressMessages（对称于 terminal 端）
        // thinking/text 为增量片段，累积到同类型最后一条；tool/status 为完整消息，直接追加
        if (evt.type === 'tool_progress') {
          const uid = evt.tool_use_id;
          if (uid) {
            const msgType = evt.progress_type ?? 'status';
            const msgContent = evt.message ?? '';
            const pendingList = pendingToolCallsRef.current[sid] ?? [];
            pendingToolCallsRef.current[sid] = pendingList.map((p) => {
              if (p.tool_use_id !== uid) return p;
              const prev = p.progressMessages ?? [];
              let next;
              if (msgType === 'thinking' || msgType === 'text') {
                const lastIdx = prev.length - 1;
                const lastEntry = lastIdx >= 0 ? prev[lastIdx] : undefined;
                if (lastEntry && lastEntry.type === msgType) {
                  next = [...prev];
                  next[lastIdx] = {message: lastEntry.message + msgContent, type: msgType};
                } else {
                  next = [...prev, {message: msgContent, type: msgType}];
                }
              } else {
                next = [...prev, {message: msgContent, type: msgType}];
              }
              return {...p, progressMessages: next};
            });
            patchView(sid, { pendingToolCalls: pendingToolCallsRef.current[sid] });
          }
          return;
        }

        // 转录管理
        if (evt.type === 'clear_transcript') {
          optimisticUserRef.current[sid] = [];
          pendingToolCallsRef.current[sid] = [];
          clearAssistantDelta(sid);
          // 清空转录 = 新会话语义：轮次大纲归零（本地轮次即全部轮次）
          patchView(sid, { items: [], pendingToolCalls: [], turnOutline: null, firstLoadedTurn: 1, loadingHistory: false });
          return;
        }
        if (evt.type === 'replace_transcript' && evt.items) {
          // 转录整体替换（rewind/checkpoint 重建）：清空乐观待确认队列
          optimisticUserRef.current[sid] = [];
          // 检查是否需要抑制显示（用于左侧栏操作解耦）
          if (suppressTranscriptRef.current) {
            suppressTranscriptRef.current = false;
            return;
          }
          // 过滤命令产物（is_command 标记）与后台任务完成通知（<task-notification> XML）
          const items = (evt.items as TranscriptItem[]).filter((item) => {
            if (item.role !== 'user') return true;
            if (item.is_command) return false;
            if (item.text.startsWith('<task-notification>')) return false;
            return true;
          });
          pendingToolCallsRef.current[sid] = [];
          clearAssistantDelta(sid);
          // 整体替换（rewind/compact）：本地轮次即权威，作废后端大纲
          // （其含已被回退/压缩掉的轮次，保留会导致导航序号错位）
          patchView(sid, {
            items: stripReplayItems(items),
            pendingToolCalls: [],
            turnOutline: null,
            firstLoadedTurn: 1,
            loadingHistory: false,
            // bump 替换信号：ChatArea 收到后强制回到底部（rewind 时用户
            // 往往停在旧消息位置且已停止跟随，不清零会留在错误的相对位置）
            transcriptReplaceTick: Date.now(),
          });
          return;
        }

        // 模态框（权限/问答/计划审批）：按会话路由，仅活跃会话展示
        if (evt.type === 'modal_request') {
          patchView(sid, { modal: evt.modal ?? null });
          return;
        }

        // 内联选项（后端 select_request 驱动的多步选择）
        if (evt.type === 'select_request') {
          const m = evt.modal ?? {};
          const cmd = String(m.command ?? '');
          const rawOpts = evt.select_options ?? [];
          const options = rawOpts.map((o) => ({
            value: String(o.value ?? ''),
            label: String(o.label ?? ''),
            description: o.description ? String(o.description) : undefined,
            active: o.active === true,
          }));
          const payload: SelectRequestPayload = {
            command: cmd,
            title: String(m.title ?? cmd),
            options,
          };
          // 通知 App（旧路径，用于需要全局处理的分支）；同时存入会话视图
          onSelectRequestRef.current?.(payload);
          patchView(sid, { inlineOptions: payload });
          patchView(sid, { busy: false });
          return;
        }

        // 待办事项（TodoWrite 工具产生，按会话隔离）
        if (evt.type === 'todo_update' && evt.todo_items != null) {
          patchView(sid, { todoItems: evt.todo_items });
          return;
        }

        // 会话恢复
        if (evt.type === 'web_restore_started') {
          // 统一经 beginRestore（自带 10s 超时兜底）；记录缺失时 patch 自动创建
          beginRestore(sid);
          return;
        }
        if (evt.type === 'web_restore_completed' || evt.type === 'web_session_ready') {
          // 首个会话内容呈现完成：首帧引导结束，解除遮罩
          setBootstrapping(false);
          pendingToolCallsRef.current[sid] = [];
          // 活跃会话 + 载荷为空 = "新建复用"路径对已激活空会话的重发交付：
          // 不得清空本地内容（可能含在途乐观用户消息），且保留乐观去重队列，
          // 让后续真实 transcript_item 正确去重。在途乐观消息存在时同样按
          // 复用处理——替换 items 会丢掉尚未收到回执的本地消息
          const hasPendingOptimistic = (optimisticUserRef.current[sid]?.length ?? 0) > 0;
          const isActiveReuse = activeSessionIdRef.current === sid
            && (evt.items ?? []).length === 0
            && ((viewsRef.current[sid]?.items?.length ?? 0) > 0 || hasPendingOptimistic);
          if (!isActiveReuse) optimisticUserRef.current[sid] = [];
          const items = isActiveReuse
            ? (viewsRef.current[sid]?.items ?? [])
            : stripReplayItems((evt.items ?? []).filter((i) => !(i.role === 'user' && i.is_command)));
          // 只合并会话专属键：全局键（model/effort 等）由 state_snapshot 权威驱动，
          // 避免恢复快照影子化后续全局设置变更
          const restoreState = evt.state ?? {};
          const sessionStatus: Record<string, unknown> = {};
          for (const key of Object.keys(restoreState)) {
            if (SESSION_STATUS_KEYS.has(key)) sessionStatus[key] = restoreState[key];
          }
          // 流式缓冲复位：断线/重放场景下残留的半截流式文本会与恢复载荷中的
          // 完整消息重复或拼接显示（复用路径除外——该路径载荷为空，本地即权威）
          if (!isActiveReuse) {
            const buf = buffersRef.current[sid];
            if (buf) {
              buf.pending = '';
              buf.raw = '';
              buf.reasoning = '';
              if (buf.timer) { clearTimeout(buf.timer); buf.timer = null; }
            }
          }
          // 长会话分页：items 只含最近一页，全量轻量大纲随事件下发
          patchView(sid, {
            items,
            pendingToolCalls: [],
            materialized: true,
            restoring: false,
            status: sessionStatus,
            turnOutline: (evt.turn_outline as TurnOutlineEntry[] | null | undefined) ?? null,
            firstLoadedTurn: Math.max(1, Number(evt.first_loaded_turn ?? 1) || 1),
            loadingHistory: false,
            // busy 随载荷校准（重连后唯一权威同步点）：断线期间完成或启动的
            // 任务，其 line_complete/assistant_delta 事件已永久丢失
            busy: isActiveReuse ? (viewsRef.current[sid]?.busy ?? false) : restoreState.busy === true,
            reasoningStreaming: false,
            assistantBuffer: isActiveReuse ? (viewsRef.current[sid]?.assistantBuffer ?? '') : '',
            streamingReasoning: isActiveReuse ? (viewsRef.current[sid]?.streamingReasoning ?? '') : '',
            // 恢复载荷携带会话所属工作区目录（多目录分组与目录按钮展示依据）
            ...(typeof restoreState.cwd === 'string' && restoreState.cwd ? { cwd: restoreState.cwd } : {}),
          });
          // 恢复完成：清除超时兜底定时器
          clearRestoreTimer(sid);
          if (evt.web_error) {
            pushStatic(sid, { role: 'system', text: `恢复会话失败: ${evt.web_error}` });
          }
          // 激活语义：client_token 精确配对（后端回显请求携带的激活意图令牌）——
          // 仅当事件是"当前意图的响应"时才激活；无 token 的被动推送
          // （初始推送/重连再同步）只在本地无有效活跃记录时兜底激活，
          // 绝不抢走用户正在浏览的会话。
          const token = evt.client_token ?? null;
          const intent = sessionStateRef.current.activation;
          const tokenMatch = token != null && intent?.token === token;
          const legacyMatch = token == null && intent != null && intent.sessionId === sid;
          const currentActive = sessionStateRef.current.activeId;
          const currentRec = currentActive ? sessionStateRef.current.sessions[currentActive] : undefined;
          const shouldActivate = tokenMatch || legacyMatch || currentRec === undefined;
          if (tokenMatch || legacyMatch) {
            // 意图响应到达：消费意图并解除等待态与超时
            settleActivation();
            dispatch({ type: 'setActivation', activation: null });
          } else if (intent === null) {
            // 无意图挂起时的被动推送：防御性清理等待态（用户中途切走等场景）；
            // 有意图挂起时保持其超时兜底不被本事件裁掉
            settleActivation();
          }
          if (shouldActivate) {
            dispatch({ type: 'activate', sid });
          }
          return;
        }

        // 历史轮次分页（长会话导航跳转"尚未载入"轮次的数据源）：
        // 条目前插到当前转录，头部边界前移
        if (evt.type === 'web_history') {
          const page = evt.web_history;
          const view = viewsRef.current[sid];
          if (!view || !page) {
            return;
          }
          // 大纲已被作废（rewind/compact/clear 后的迟到响应）：该页基于
          // 旧转录计算，前插会污染重置后的转录——直接丢弃
          if (!view.turnOutline) {
            patchView(sid, { loadingHistory: false });
            return;
          }
          if (page.error || !Array.isArray(page.items) || page.items.length === 0 || page.first_turn == null) {
            patchView(sid, { loadingHistory: false });
            if (page.error) {
              pushStatic(sid, { role: 'system', text: `加载历史轮次失败: ${page.error}` });
            }
            return;
          }
          const firstTurn = Math.max(1, Number(page.first_turn) || 1);
          const newItems = stripReplayItems(
            (page.items as TranscriptItem[]).filter((i) => !(i.role === 'user' && i.is_command)));
          const pageTurns = Math.max(1, newItems.filter((i) => i.role === 'user').length);
          // 新页尾部与现有头部的重叠轮数（迟到/重复响应兜底）：
          // 截掉被覆盖的头部轮，再前插新页，保证轮序不重复
          const overlap = Math.max(0, firstTurn + pageTurns - (view.firstLoadedTurn ?? 1));
          patchView(sid, {
            items: [...newItems, ...view.items.slice(countLeadingTurnItems(view.items, overlap))],
            firstLoadedTurn: firstTurn,
            loadingHistory: false,
          });
          return;
        }

        // rewind 被回退的 user 消息：回填输入框（转录已由 replace_transcript 刷新）
        if (evt.type === 'session_rewind' && evt.restored_text) {
          optimisticUserRef.current[sid] = [];
          onRewindRestoredRef.current?.(evt.restored_text);
          return;
        }

        // 会话级错误 → 转录
        if (evt.type === 'error') {
          pushStatic(sid, { role: 'system', text: `error: ${evt.message ?? 'unknown error'}` });
          clearAssistantDelta(sid);
          patchView(sid, { busy: false });
          // 创建类意图的目标会话尚未揭晓（sessionId 为 null），其响应可能
          // 以 error 形式到达当前活跃会话：作废意图并解除等待态，避免挂起的
          // 意图被下一次被动推送误配对（fork/ensure/new/删除补位失败场景）
          const intent = sessionStateRef.current.activation;
          if (intent && intent.sessionId === null && sid === activeSessionIdRef.current) {
            settleActivation();
            dispatch({ type: 'setActivation', activation: null });
          }
          return;
        }

        // 后台 agent 状态提示
        if (evt.type === 'bg_agent_status') {
          setBgAgentLabel(evt.message ?? null);
          return;
        }
      }

      // === 全局事件（无会话路由）===

      if (evt.type === 'web_sessions') {
        // 元数据重建与合并语义全部收敛在 reducer（不可变、单一数据源）：
        // busy 仅对未恢复视图只升不降兜底；goal 仅补缺；列表顺序即推送顺序
        dispatch({
          type: 'sessionsPush',
          items: evt.web_sessions ?? [],
          backendActiveId: evt.active_session_id ?? null,
        });
        // 活跃记录未恢复（初始推送/重连再同步）：经统一入口置恢复中
        // （自带 10s 超时兜底），随后 web_restore_completed 到达时清除
        const activeId = sessionStateRef.current.activeId;
        if (activeId) {
          const rec = sessionStateRef.current.sessions[activeId];
          if (rec && !rec.materialized) beginRestore(activeId);
        }
        return;
      }
      if (evt.type === 'web_setting_changed') {
        // 单项设置变更：合并到全局 status，前端工具栏读 status 字段即时更新
        const key = evt.setting_key;
        const value = evt.setting_value;
        if (key && value !== undefined && value !== null) {
          setStatus((s) => ({ ...s, [key]: value }));
        }
        return;
      }
      if (evt.type === 'web_models') {
        // 后端推送的模型选项，更新 modelOptions（含 active 态）
        const opts = (evt.web_models ?? []).map((o) => ({ value: String(o.value ?? ''), label: String(o.label ?? ''), active: o.active === true }));
        setModelOptions(opts);
        setModelSwitching(false); // 模型切换完成，清除加载态
        return;
      }
      if (evt.type === 'web_resources') {
        // 后端推送的资源快照，结构化更新（废弃旧的文本正则解析）；
        // cwd 标记资源所属工作区（右栏按目录联动的依据）
        const res = evt.web_resources;
        if (!res) return;
        // 目录归属守卫：快速多次切换会话/目录时，前序会话的迟到 web_resources
        // 会覆盖当前会话数据。仅当响应 cwd 与当前活跃会话目录一致（或无法判断
        // 目录时放宽）才应用，否则丢弃，避免"残留上一个会话状态"
        const active = activeSessionIdRef.current
          ? viewsRef.current[activeSessionIdRef.current]
          : undefined;
        if (evt.cwd && active?.cwd && evt.cwd !== active.cwd) return;
        setSkills((res.skills as SkillSnapshot[]) ?? []);
        setPlugins((res.plugins as PluginSnapshot[]) ?? []);
        setRules((res.rules as RuleSnapshot[]) ?? []);
        setMcpServers((res.mcp_servers as McpServerSnapshot[]) ?? []);
        setResourcesCwd(evt.cwd ?? null);
        return;
      }
      if (evt.type === 'web_agent_tasks') {
        // 智能体与后台任务（随会话隔离）：归属活跃会话或未标记时应用
        const sid = evt.session_id;
        if (!sid || !activeSessionIdRef.current || sid === activeSessionIdRef.current) {
          setAgentTasks((evt.web_agent_tasks as AgentTaskItem[]) ?? []);
        }
        return;
      }
      if (evt.type === 'web_session_files') {
        // 会话内修改文件（随会话隔离）：归属活跃会话或未标记时应用，
        // 避免切换会话后迟到响应覆盖新会话的会话文件列表
        const sid = evt.session_id;
        if (!sid || !activeSessionIdRef.current || sid === activeSessionIdRef.current) {
          setSessionFiles((evt.web_session_files as SessionFileItem[]) ?? []);
        }
        setSessionFilesLoading(false);
        return;
      }
      if (evt.type === 'web_file_tree') {
        // 目录单层条目（懒加载）；按事件携带目录归位。
        // 无论归属是否匹配都清理该目录的加载态，避免 cwd-guard 丢弃路径
        // （切换目录后的迟到响应）泄漏 loading 导致 Files 区块永久加载中
        const tree = evt.web_file_tree;
        if (tree) {
          const dir = tree.path ?? '';
          fileTreeLoadingRef.current.delete(dir);
          setFileTreeLoadingPaths((prev) => prev.filter((p) => p !== dir));
          if (!evt.cwd || !resourcesCwdRef.current || evt.cwd === resourcesCwdRef.current) {
            setFileTree((prev) => ({ ...prev, [dir]: tree.entries ?? [] }));
          }
        }
        return;
      }
      if (evt.type === 'web_git_status') {
        // Git 状态快照；迟到响应按 cwd 丢弃，同上
        const snap = evt.web_git_status;
        if (snap && (!evt.cwd || !resourcesCwdRef.current || evt.cwd === resourcesCwdRef.current)) {
          setGitStatus(snap);
        }
        setGitLoading(false);
        return;
      }
      if (evt.type === 'web_file_mentions') {
        // @ 提及补全候选：requestId 不匹配的迟到响应由 PromptInput 侧丢弃；
        // 分区顺序 skills → sessions → files（优先级 Skills > Sessions > Files），
        // kind 供菜单分区渲染。直通订阅方不落状态：补全按击键高频往返，
        // 进状态会拖累整页渲染
        const payload = evt.web_file_mentions;
        if (payload) {
          const result = {
            requestId: evt.request_id ?? '',
            query: payload.query,
            candidates: [
              ...(payload.skills ?? []).map((s) => ({ path: s.name, kind: 'skill' as const, description: s.description })),
              ...(payload.sessions ?? []).map((s) => ({
                path: s.path,
                kind: 'session' as const,
                description: s.description,
                sessionId: s.sessionId,
              })),
              ...(payload.candidates ?? []),
            ],
          };
          // 逐监听器隔离异常：单个订阅方抛错不中断其余分发与消息处理
          for (const cb of fileMentionListenersRef.current) {
            try {
              cb(result);
            } catch (exc) {
              console.error('file mention listener failed:', exc);
            }
          }
        }
        return;
      }
      if (evt.type === 'web_file_content') {
        // 文件预览载荷（error 字段非空表示读取失败）；与发起请求的
        // kind|path 一致才应用（内容/diff 两视图按键精确关联）
        const payload = evt.web_file_content;
        const key = `${payload?.kind === 'diff' ? 'diff' : 'content'}|${payload?.path ?? ''}`;
        if (payload && key === filePreviewKeyRef.current) {
          setFilePreview(payload);
          setFilePreviewLoading(false);
        }
        return;
      }
      // CAD 画布工作台文档变更（agent 工具 / 前端编辑，后端广播）
      if (evt.type === 'cad_canvas_update' && evt.canvas) {
        // cwd 归属守卫：画布按工作区隔离，多工作区场景下其他目录的
        // 广播推送不得覆盖当前视图（与 web_resources 守卫同一语义）
        const active = activeSessionIdRef.current
          ? viewsRef.current[activeSessionIdRef.current]
          : undefined;
        if (evt.cwd && active?.cwd && evt.cwd !== active.cwd) return;
        setCanvasDoc(evt.canvas as CanvasDoc);
        return;
      }
      // CAD 建模会话更新（宿主每操作后广播 / ready 后 web_cad_status 轻量拉取）
      if (evt.type === 'cad_update' && evt.cad_update) {
        setCadState(evt.cad_update as CadUpdatePayload);
        return;
      }
      if (evt.type === 'web_workspaces') {
        // 工作区列表（默认目录在首位；available=false 表示目录已不存在）
        setWorkspaces((evt.web_workspaces ?? []).map((w) => ({
          path: String(w.path ?? ''),
          name: String(w.name ?? ''),
          is_default: w.is_default === true,
          available: w.available !== false,
        })));
        return;
      }
      if (evt.type === 'web_query_result') {
        const payload = evt.web_query_payload;
        // 智能体摘要（viewAgentSummary 发起）：路由到预览面板展示全文
        if (evt.web_command === 'agent' && agentViewRef.current && evt.web_request_id === agentViewRef.current.requestId) {
          const id = agentViewRef.current.id;
          agentViewRef.current = null;
          if (evt.web_query_kind === 'text' && typeof payload === 'string') {
            setFilePreview({
              path: `${id} · 摘要`,
              content: payload,
              size: payload.length,
              truncated: false,
            });
          } else {
            setFilePreview({ path: `${id} · 摘要`, error: '未找到该智能体或任务的摘要' });
          }
          setFilePreviewLoading(false);
          if (sid) patchView(sid, { busy: false });
          return;
        }
        if (evt.web_query_kind === 'text' && typeof payload === 'string') {
          // 所有 B 通道指令的文本结果统一走 toast，不渲染到主会话
          if (payload.trim() && onCommandResultRef.current) {
            onCommandResultRef.current(payload, 'info');
          }
        } else if (evt.web_query_kind === 'transcript_replace' && Array.isArray(payload)) {
          const target = evt.session_id ?? activeSessionIdRef.current;
          if (target) {
            patchView(target, {
              items: payload as TranscriptItem[],
              transcriptReplaceTick: Date.now(),
            });
          }
        }
        if (sid) patchView(sid, { busy: false });
        return;
      }

      // === agent 向导响应（全局）===
      if (evt.type === 'agent_wizard_init_response') {
        setAgentWizardTools(evt.tools ?? null);
        setAgentWizardModels(evt.models ?? null);
        return;
      }
      if (evt.type === 'agent_generate_response') {
        // 无活跃请求时（用户已关闭表单）忽略所有迟到响应
        const activeId = agentGenerateRequestIdRef.current;
        if (!activeId) {
          return;
        }
        // 仅处理与当前活跃 request_id 匹配的响应，避免过期响应覆盖新请求状态
        if (evt.request_id && evt.request_id !== activeId) {
          return;
        }
        setAgentGenerateLoading(false);
        if (evt.error) {
          setAgentGenerateError(evt.error);
          setAgentGenerated(null);
        } else if (evt.agent) {
          setAgentGenerateError(null);
          setAgentGenerated(evt.agent);
        }
        // 保留 agentGenerateRequestId 以便表单消费完成后由 clearAgentWizardState 清理
        return;
      }
      if (evt.type === 'agent_wizard_result') {
        setAgentWizardResult({
          success: Boolean(evt.success),
          path: evt.path ?? undefined,
          errors: evt.errors ?? undefined,
          error: evt.error ?? undefined,
        });
        return;
      }

      // === agent 管理（设置表单 AgentsTab）===
      if (evt.type === 'web_agents' && evt.web_agents) {
        setAgentCatalog(evt.web_agents);
        setAgentCatalogLoading(false);
        return;
      }
      if (evt.type === 'web_agent_op_result') {
        setAgentCatalogLoading(false);
        setAgentOpResult({
          op: evt.web_agent_op ?? 'update',
          success: Boolean(evt.success),
          error: evt.error ?? undefined,
        });
        return;
      }

      // === 其他全局事件 ===
      if (evt.type === 'toast' && evt.toast) {
        // toast 通知：转发给 App 做监管判定（界内不打扰）、播放音效、
        // 页面不可见时透传系统级通知。文案由后端本地化，这里原样传递。
        onToastRef.current?.(evt.toast);
        return;
      }
      if (evt.type === 'command_result' && evt.command_result_data) {
        const msg = evt.command_result_data.message ?? '';
        // 检查是否需要抑制显示
        if (suppressCommandResultCountRef.current > 0) {
          suppressCommandResultCountRef.current--;
          return;
        }
        // 通知 App 显示 toast
        if (onCommandResultRef.current) {
          const reqId = evt.command_result_data?.request_id as string | undefined;
          onCommandResultRef.current(msg, evt.command_result_data.type || 'info', reqId);
        }
        return;
      }
      if (evt.type === 'goal_action_result') {
        // GoalBar 操作回执：失败行内显示（成功时后端随 state_snapshot 推送新 goal）
        if (evt.success === false && evt.goal_error) {
          setGoalActionError(evt.goal_error);
        } else if (evt.success === true) {
          setGoalActionError(null);
        }
        return;
      }
      if (evt.type === 'goal_status' && evt.goal_status) {
        // Goal 轮次生命周期：toast 文案完全由后端 i18n 生成（message），
        // 前端直接展示，避免浏览器语言/前端字符串副本影响显示。
        const gs = evt.goal_status;
        // round 事件同时更新 status.goal.roundsStarted，使 GoalBar 轮次进度实时刷新
        if (gs.kind === 'round' && gs.round != null) {
          setStatus((prev) => {
            const goal = (prev.goal as Record<string, unknown> | undefined);
            if (!goal) return prev;
            return { ...prev, goal: { ...goal, roundsStarted: gs.round } };
          });
        }
        if (gs.message) {
          onCommandResultRef.current?.(gs.message, 'info');
        }
        return;
      }
      if (evt.type === 'swarm_status') {
        if (evt.swarm_teammates != null) setSwarmTeammates(evt.swarm_teammates);
        if (evt.swarm_notifications != null) setSwarmNotifications((prev) => [...prev, ...evt.swarm_notifications!].slice(-20));
        return;
      }
      if (evt.type === 'plan_mode_change' && evt.plan_mode != null) {
        setStatus((s) => ({ ...s, permission_mode: evt.plan_mode }));
        return;
      }
      if (evt.type === 'shutdown') {
        shuttingDown = true;
        wsRef.current?.close();
      }
    }

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      const current = wsRef.current;
      wsRef.current = null;
      current?.close();
    };
  }, [url, dispatch, beginRestore, settleActivation, clearRestoreTimer, ensureView, patchView, getBuffer, flushAssistantDelta, clearAssistantDelta, pushStatic, sendRaw, refreshRightPanel]);

  // 首次登录配置保存后手动清除 firstLogin 状态（避免再次打开表单仍显示首次登录）
  const clearFirstLogin = useCallback(() => setFirstLogin(false), []);

  return useMemo(() => {
    const view = sessionState.activeId ? sessionState.sessions[sessionState.activeId] : undefined;
    return {
      // 活跃会话视图
      staticItems: view?.items ?? [],
      assistantBuffer: view?.assistantBuffer ?? '',
      streamingReasoning: view?.streamingReasoning ?? '',
      status: { ...status, ...(view?.status ?? {}) },
      busy: view?.busy ?? false,
      modal: view?.modal ?? null,
      todoItems: view?.todoItems ?? [],
      pendingToolCalls: view?.pendingToolCalls ?? [],
      reasoningStreaming: view?.reasoningStreaming ?? false,
      restoringSessionId: view?.restoring ? view.id : ensureRestoring,
      // 全局状态
      tasks, commands, mcpServers, skills, plugins, rules, modelOptions,
      agentTasks, fileTree, fileTreeLoadingPaths, gitStatus, gitLoading,
      sessionFiles, sessionFilesLoading,
      turnOutline: view?.turnOutline ?? null,
      firstLoadedTurn: view?.firstLoadedTurn ?? 1,
      loadingHistory: view?.loadingHistory ?? false,
      transcriptReplaceTick: view?.transcriptReplaceTick ?? 0,
      requestHistory, forkSession,
      subscribeFileMentions, requestFileMentions,
      filePreview, filePreviewLoading,
      requestFileTree, requestGitStatus, openFilePreview, openFileDiff, closeFilePreview,
      requestAgentTasks, viewAgentSummary, requestSessionFiles, openSessionFile,
      ready, firstLogin, showThinking,
      swarmTeammates, swarmNotifications, bgAgentLabel, connected, connectionError,
      bootstrapping,
      awaitingNewSession,
      modelSwitching, setModelSwitching,
      // 多会话管理
      // 列表派生自会话注册表（单一数据源）：busy/phase 为运行时实时值
      // （事件驱动，无推送延迟）；active 以本地切换为准（后端推送的
      //  active 仅用于首次连接初始化，见 sessionsPush）。
      ensureSession,
      sessions: selectSessionList(sessionState).map((r) => ({
        value: r.id,
        label: r.label,
        busy: r.busy,
        phase: r.phase,
        active: r.id === sessionState.activeId,
        cwd: r.cwd,
        createdAt: r.createdAt,
        turnCount: r.turnCount,
        summary: r.summary,
        title: r.title,
        workbench: r.workbench,
      })),
      workspaces,
      resourcesCwd,
      activeWorkspaceCwd: view?.cwd || null,
      activeSessionId,
      activateSession,
      newSession,
      requestWorkspaces,
      addWorkspace,
      removeWorkspace,
      requestResources,
      inlineOptions: view?.inlineOptions ?? null,
      setInlineOptions,
      // agent 向导（全局）
      agentWizardTools, agentWizardModels, agentGenerated, agentGenerateLoading,
      agentGenerateError, agentWizardResult,
      sendAgentWizardInit, sendAgentGenerateRequest, sendAgentWizardSubmit, clearAgentWizardState,
      // agent 管理（设置表单 AgentsTab，全局）
      agentCatalog, agentCatalogLoading, agentOpResult,
      requestAgents, updateAgent, deleteAgent, clearAgentOpResult,
      clearFirstLogin,
      deleteSessions, clearModal, setBusyTrue,
      requestSelectCommand, setEffortValue, setModelValue,
      sendRequest, stopping: view?.stopping ?? false, sendStop,
      canvasDoc, updateCanvasDoc, cadState, focusSolidWorks, sendSnapshot, cadConnectTick, refreshCanvas,
      clearStaticItems, optimisticSubmit,
      // GoalBar（活跃视图）
      goalActionError, sendGoalAction, clearGoalActionError,
      setOnSelectRequest, setOnCommandResult, setOnUpdateAvailable, setOnRewindRestored,
      setOnToast,
    };
  }, [
    status, tasks, commands, mcpServers, skills, plugins, rules, modelOptions,
    agentTasks, fileTree, fileTreeLoadingPaths, gitStatus, gitLoading,
    sessionFiles, sessionFilesLoading,
    requestHistory, forkSession,
    subscribeFileMentions, requestFileMentions,
    filePreview, filePreviewLoading,
    requestFileTree, requestGitStatus, openFilePreview, openFileDiff, closeFilePreview,
    requestAgentTasks, viewAgentSummary, requestSessionFiles, openSessionFile,
    ready, firstLogin, showThinking, swarmTeammates, swarmNotifications,
    bgAgentLabel, connected, connectionError, sessionState, ensureRestoring, activeSessionId,
    workspaces, resourcesCwd, awaitingNewSession,
    activateSession, newSession, setInlineOptions, patchView,
    requestWorkspaces, addWorkspace, removeWorkspace, requestResources,
    agentWizardTools, agentWizardModels, agentGenerated, agentGenerateLoading,
    agentGenerateError, agentWizardResult,
    sendAgentWizardInit, sendAgentGenerateRequest, sendAgentWizardSubmit, clearAgentWizardState,
    agentCatalog, agentCatalogLoading, agentOpResult,
    requestAgents, updateAgent, deleteAgent, clearAgentOpResult,
    clearFirstLogin, deleteSessions, clearModal, setBusyTrue,
    requestSelectCommand, setEffortValue, setModelValue,
    sendRequest, sendStop, clearStaticItems, optimisticSubmit,
    canvasDoc, updateCanvasDoc, cadState, focusSolidWorks, refreshCanvas, sendSnapshot, cadConnectTick,
    goalActionError, sendGoalAction, clearGoalActionError,
    setOnSelectRequest, setOnCommandResult, setOnUpdateAvailable, setOnRewindRestored,
    setOnToast,
    modelSwitching, setModelSwitching,
  ]);
}