# Goal 功能

IllusionForge 的 goal 子系统提供**会话内持久化的完成目标**与**自动续跑轮次**：把一个跨多轮的长任务绑定为当前会话上的一个目标，每轮结束后自动注入轮次消息继续执行，直到完成、受阻或达到轮次上限。目标生命周期与权限由统一的状态机管理，完成声明经过单个对抗性验证者的校验。

## 概念

- **goal**：绑定在当前会话上的一个持久化完成目标。相位为 `active | paused | blocked | complete`；每次可持久变更递增 `revision`（CAS 栅栏，见下文）。
- **goal round**：一次自动续跑轮次。激活的 goal 在每轮结束后自动注入 `<goal_round>` 用户消息继续执行，直到完成、受阻或达到轮次上限（`max_goal_rounds`，默认 256）。
- **goal activation**：进程内武装状态（`armed | disarmed`），**不持久化**。会话恢复/新建后恒为 `disarmed`——必须由人类以任何措辞要求继续（模型调用 `update_goal action=resume`）才会重新武装。

### 相位转换

| 操作 | 前置相位 | 目标相位 | 权威来源 | 说明 |
| --- | --- | --- | --- | --- |
| `create` | 无目标 | `active`（armed） | human | 创建即武装，立即开始自动轮次 |
| `edit` | active / paused / blocked | 保持 | human | 替换 objective / 轮次上限；complete 不可编辑 |
| `pause` | active | `paused`（disarmed） | human | 当前轮完成后停止，不再自动续跑 |
| `resume` | paused / blocked | `active`（armed） | human | **唯一 rearm 途径** |
| `complete` | active / paused / blocked | `complete`（disarmed） | human 或 goal round | 经对抗性验证通过后才落终态 |
| `blocked` | active / paused | `blocked`（disarmed） | human、goal round 或内部 | 受阻并记录原因码 |

> 注意：`resume` 是唯一能重新武装（rearm）的路径。因此 `/resume`、`/fork` 或任何会话恢复之后，activation 恒为 `disarmed`，goal 不会自行续跑，必须由人类明确要求继续。

### CAS revision 栅栏

`revision` 是**比较并交换**（compare-and-swap）栅栏：从 1 起，每次可持久变更递增。所有变更操作必须携带调用方读到的精确 `(id, revision)`；不匹配时操作被拒绝，错误消息会携带当前精确值，模型可据此直接重试（消除猜测 id/revision 失败的额外往返）。

## 使用方式

### 人类命令

```
/goal [<objective>|clear|edit <objective>|pause|resume]
```

- `/goal 修复登录闪退`：创建目标并立即开始自动轮次
- `/goal`：查看当前目标状态（objective / phase / activation / rounds / revision）
- `/goal pause`：暂停（当前轮完成后停止）
- `/goal resume`：恢复并立即驱动续跑
- `/goal edit <新目标>`：编辑目标文本
- `/goal clear`：清除目标

创建与 `resume` 返回 `drive_goal=True`，由行处理逻辑立即驱动 goal 轮次；其余操作为纯状态变更。

### 模型工具

| 工具 | 用途 |
| --- | --- |
| `get_goal` | 读取当前 goal（精确 id/revision/相位/轮次/激活状态/受阻原因）；更新前应先调用 |
| `create_goal` | 创建 goal（要求人类来源的轮次；可从直接请求推断意图，无需用户明确说"创建目标"） |
| `update_goal` | `edit / pause / resume / complete / blocked`（edit/pause/resume 要求人类；complete/blocked 允许人类或 goal round） |

三个工具共享统一的 `GOAL_OUTPUT` 紧凑 JSON 输出格式：`{ goal: { id, revision, objective, phase, roundsStarted, maxGoalRounds, blockedReason? }, activation }`。

## 轮次驱动

引擎在每轮结束后询问 `should_continue()`，仅在 **active + armed + 未达轮次上限 + 无待注入 wrap-up** 时注入下一个 `<goal_round>` 轮次消息：

- `admit_round()` 每次准入将 `rounds_started` 加一；若已达上限，自动 `block('round-limit')` 并停止。
- 轮次消息来源标记为 `goal`，据此判定工具操作的权威来源（`human` vs `goal`）。
- 后台驱动（`backend_host` / `ws_host`）在 `resume` 且会话空闲时立即驱动续跑，并守护活跃行任务唯一性，防止快速连按产生孤儿任务。

## 完成验证

模型调用 `update_goal(action: "complete")` 声明完成时，由 harness（而非模型自主决定）同步生成**单个对抗性验证子代理**——复用 IllusionForge 自己的 `verification` 代理定义（`coordinator/agent_definitions.py`，其系统提示词要求以 `VERDICT: PASS|FAIL|PARTIAL` 结尾）。

- 证据包组织为：`OBJECTIVE / CHANGES_FILE / CHANGED_FILES / PLAN_CHANGES / FINAL_RESPONSE / PRIOR_GAPS`（优先 git porcelain + `git diff HEAD`，无仓库时回退 file-history；patch 文件截断 256 KiB）。
- **fail-closed**：验证者输出不可解析 → 合成 FAIL，拒绝完成声明。
- **infra fail-open**：验证者无法生成（基础设施故障）→ 视为通过，避免 harness 缺陷卡死用户。
- FAIL/PARTIAL → 缺陷回灌给实现者继续修复（goal 保持 active）。
- 连续拒绝达 `verification_max_attempts`（默认 10）→ 自动置 `blocked (verification-cap)`。
- 同一缺陷指纹（归一化报告哈希）连续重复 → 自动置 `blocked (verification-stall)`。
- goal round 来源下，`blocked` 早于 `blocked_after_consecutive_rounds`（默认 3）轮时被机械拒绝（`GOAL_TOOL_BLOCK_THRESHOLD`）。

### 受阻原因码

| code | 触发 |
| --- | --- |
| `round-limit` | 自动轮次达到 `max_goal_rounds` 上限 |
| `model-reported` | 模型通过 `update_goal(action="blocked")` 报告受阻 |
| `verification-cap` | 验证拒绝累计达 `verification_max_attempts` |
| `verification-stall` | 同一缺陷指纹跨连续尝试重复出现 |

## 前端

- **Web**：输入框上方的 GoalBar——相位标签 + 目标 + 轮次计数（`roundsStarted/maxGoalRounds`）+ 操作图标（active 显示暂停、paused 显示恢复、恒有编辑与清除）。编辑切换为行内表单（Enter 保存、Esc 取消、空白禁用保存）。blocked 时显示受阻原因。编辑在活跃状态即可进行，对后续轮次实时生效、不打断当前轮；暂停为"当前轮完成后停止"。

## 配置（`settings.json`）

```json
{
  "goal": {
    "enabled": true,
    "default_max_goal_rounds": 256,
    "blocked_after_consecutive_rounds": 3,
    "verification_enabled": true,
    "verification_max_attempts": 10
  }
}
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否启用 goal 子系统 |
| `default_max_goal_rounds` | `256` | 默认自动续跑轮次上限 |
| `blocked_after_consecutive_rounds` | `3` | goal round 来源下允许置 blocked 的最小轮次门槛 |
| `verification_enabled` | `true` | 是否启用对抗性验证 |
| `verification_max_attempts` | `10` | 验证连续拒绝达此值自动置 blocked |

## 持久化

goal 状态以 `_goal` 行（last-wins 快照）写入会话的 `context.jsonl`；`/resume`、`/fork` 后自动恢复，但 activation 恒为 `disarmed`（需人类授权 resume 重新武装）。`/new`、full_reset 完全清空目标状态。

## 错误码

| code | 语义 |
| --- | --- |
| `GOAL_TOOL_INVALID_UPDATE` | 参数或 CAS 校验失败（objective 为空、id/revision 不匹配等） |
| `GOAL_TOOL_AUTHORITY_REQUIRED` | 权威不足：变更类操作要求 human 或当前 goal round |
| `GOAL_TOOL_BLOCK_THRESHOLD` | goal round 来源下 blocked 早于最小轮次门槛 |
| `GOAL_TOOL_CONFLICT` | 状态冲突（如会话中已有目标时再次创建） |

## 典型工作流

1. 用户提出长任务 → 模型调用 `create_goal`（或人类直接 `/goal 任务描述`），goal 进入 `active` 并武装。
2. 每轮结束自动注入 `<goal_round>` 继续执行，直至任务完成或受阻。
3. 模型声明 `complete` → 对抗性验证：PASS 落终态；FAIL/PARTIAL 回灌缺陷继续修复。
4. 人类可随时 `/goal pause`（当前轮完成后停止）、`/goal edit`（改写目标，后续轮次生效）、`/goal resume`（恢复并续跑）或 `/goal clear`（清除）。
