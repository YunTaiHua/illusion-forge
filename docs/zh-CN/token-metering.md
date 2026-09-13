# Token 计量与上下文管理

本文档详细解释 IllusionForge 如何计量 token 用量、计算上下文占用，以及通过压缩管理上下文窗口。

---

## 1. Token 计量

### 1.1 `/context usage` 输出详解

`/context usage` 命令显示当前上下文状态的完整分项。示例输出（正常对话、存在缓存命中时）：

```
上下文窗口：1,000,000 tokens
输入（缓存）：175,200 tokens (18%)
输入（未缓存）：12,700 tokens (1%)
输出：12,200 tokens (1%)
缓存命中率：93%
已用上下文：200,100 tokens (20%)
剩余：799,900 tokens
累积用量：缓存=1,230,000 未缓存=187,900 输出=12,200
```

| 行 | 含义 | 数据来源 |
|----|------|----------|
| 上下文窗口 | 配置的上下文窗口大小 | `settings.context_window` |
| 输入（缓存） | **最后一次 API 调用**的缓存输入 = `cache_read` + `cache_creation`（含命中和写入） | `last_api_usage` |
| 输入（未缓存） | **最后一次 API 调用**的未缓存输入（这些 token 会被自动缓存写入，下次调用即为缓存） | `last_api_usage.input_tokens` |
| 输出 | **最后一次 API 调用**的输出 | `last_api_usage.output_tokens` |
| 缓存命中率 | `cache_read` / (`cache_read` + `cache_creation` + `input_tokens`)，只统计真正从缓存读取的 token（见 §1.4） | `last_api_usage` |
| 已用上下文 | 当前上下文占用 = 最后一次 API 调用的 `context_size` + 其后新增消息的估算增量（§1.5） | `engine.current_context_tokens()` |
| 剩余 | 上下文窗口 − 已用上下文 | 计算得出 |
| 累积用量 | 会话期间所有 API 调用的总和，由 `CostTracker` 累加（缓存 = 命中 + 写入） | `engine.total_usage` |

注意：前三行（输入缓存/未缓存/输出）和缓存命中率描述的是**最后一次 API 调用**，最后一行描述的是**整个会话**——两者的统计口径不同。

在首次 API 调用之前，或压缩后（`last_api_usage` 被清除），只显示估算行：

```
上下文窗口：1,000,000 tokens
已用上下文：0 tokens (0%)
剩余：1,000,000 tokens
累积用量：命中=0 未命中=0 输出=0
```

### 1.2 数据来源

系统跟踪两组独立数据：

- **最后一次 API 调用用量**（`last_api_usage`）：最近一次 API 调用返回的精确 `usage` 对象（含缓存分项）。是 StatusBar 与上下文占用显示的基础。
- **累积用量**（`total_usage`）：会话期间所有 API 调用的总和，由 `CostTracker` 累加。显示在 `/context usage` 与 Web 右侧面板的"累积 API 用量"区块。

### 1.3 协议差异（重要）

不同 API 格式的 usage 字段含义不同：

**Anthropic Messages API：**

```json
"usage": {
    "input_tokens": 8,                        // 非缓存输入（计费）
    "cache_creation_input_tokens": 5501,      // 写入缓存的 token
    "cache_read_input_tokens": 0,             // 命中缓存的 token
    "output_tokens": 4
}
```

- `input_tokens` **不包含**缓存部分。
- 完整输入 = `input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens`。

**OpenAI Chat Completions / Responses API：**

```json
"usage": {
    "prompt_tokens": 5509,                    // 总输入（包含缓存）
    "completion_tokens": 4,
    "prompt_tokens_details": { "cached_tokens": 5501 }
}
```

- `prompt_tokens`（Responses 中为 `input_tokens`）**包含**缓存命中部分。
- 非缓存输入 = `prompt_tokens` - `cached_tokens`（嵌套在 `prompt_tokens_details` / `input_tokens_details` 中）。

**统一字段映射：**

| 内部字段 | Anthropic 来源 | OpenAI 来源 |
|----------|----------------|-------------|
| `input_tokens`（未命中） | `usage.input_tokens` | `prompt_tokens - cached_tokens` |
| `cache_read_input_tokens`（命中） | `usage.cache_read_input_tokens` | `prompt_tokens_details.cached_tokens` |
| `cache_creation_input_tokens`（写入） | `usage.cache_creation_input_tokens` | `0`（不区分） |
| `output_tokens` | `usage.output_tokens` | `completion_tokens` |

### 1.4 缓存命中率

- **命中率** = `cache_read_input_tokens` / (`cache_read_input_tokens` + `cache_creation_input_tokens` + `input_tokens`)

只统计真正从缓存**读取**的 token（`cache_read`），不把首次写入缓存的 token（`cache_creation`）算作命中。写入缓存的 token 下次调用才会命中。

示例（假设 `cache_read=8000`, `cache_creation=4000`, `input=8000`）：

```
命中率 = 8000 / (8000 + 4000 + 8000) = 40%
```

| 前端 | 显示 |
|------|------|
| Terminal StatusBar | 格式 `cached↓ input↓ output↑ XX%`，XX 为命中率 |
| Web RightPanel | 单独一行"缓存命中率" |
| `/context usage` | 单独一行"缓存命中率" |

> **注意：首次调用命中率为 0%。** 首次 API 调用时 `cache_read=0`（缓存为空），`cache_creation>0`（正在写入缓存），因此命中率为 0%。第二次调用起命中率才会上升。

### 1.5 上下文占用计算

```
context_tokens = last_api_usage.context_size + 估算(最后一次 API 调用之后新增的消息)
```

其中：

```
context_size = input_tokens + cache_read_input_tokens + cache_creation_input_tokens + output_tokens
```

以最后一次 API 调用的真实 `context_size` 为基准，对之后新增的消息做本地估算（字符数启发式，乘以 4/3 保守系数）。这与 Claude Code 的 `tokenCountWithEstimation` 思路一致——真实用量为基准、仅对增量做估算——以避免低估上下文（低估会导致压缩触发过晚、API 调用失败）。

压缩后 `last_api_usage` 会被清除，上下文回退到纯估算，直到下一次 API 调用提供新的真实值。

---

## 2. 压缩

当对话过长时，压缩用于释放上下文窗口空间。分为两个层级：

### 2.1 微压缩（Microcompact）

**做什么**：清除旧的可压缩工具结果内容（来自 `read_file`、`bash`、`grep`、`glob`、`web_search`、`web_fetch`、`edit_file`、`write_file`），替换为占位符 `[Old tool result content cleared]`。保留最近 5 个可压缩工具结果。无需调用 LLM，廉价且快速。

**何时触发**：作为自动压缩的第一步（见下文）。如果微压缩单独释放的 token 足以使占用降到阈值以下，则跳过全压缩。

### 2.2 全压缩（LLM 摘要）

**做什么**：调用 LLM 为较早的消息生成结构化摘要并替换之。保留最近 6 条消息原样不动。结果为 `[摘要] + [COMPACT_BOUNDARY 标记] + 最近消息`。代价是一次额外的 LLM 调用。

**何时触发**：当微压缩不足以释放足够空间时，或通过 `/compact` 手动触发。

### 2.3 阈值

```
effective_context_window = context_window - min(max_output_tokens, 20,000)   // 为输出预留空间
auto_compact_threshold    = effective_context_window - 13,000                // 缓冲
warning_threshold         = auto_compact_threshold - 20,000                  // "接近上限"警告
blocking_limit            = context_window - 3,000                           // 自动压缩被禁用时
```

| 阈值 | 条件 | 行为 |
|------|------|------|
| 警告 | `context_tokens >= warning_threshold` | 显示"上下文即将占满"状态 |
| 自动压缩 | `context_tokens >= auto_compact_threshold` | 先微压缩，不足则全压缩 |
| 阻塞 | `context_tokens >= blocking_limit`（自动压缩被禁用） | 阻止继续输入，直到手动压缩 |

检查在 `run_query` 的每个 agent 轮次开始时、调用 API 之前执行。使用的上下文值与 `/context usage` 显示的一致（最后一次 API 调用的真实 `context_size` + 估算增量），保证两者口径统一。

### 2.4 自动压缩流程

1. 每轮开始，若 `context_tokens >= auto_compact_threshold`，先执行微压缩。
2. 将释放的 token 从 `context_tokens` 中减去；若此时低于阈值，则仅完成微压缩。
3. 否则执行全压缩（LLM 摘要），保留最近 6 条消息。
4. 连续 3 次压缩失败后，熔断器停止重试（上下文已不可挽回地超限）。

### 2.5 响应式压缩

若 API 返回 `prompt too long` 错误，触发响应式压缩：先尝试微压缩，再尝试全压缩，然后重试请求。若压缩本身的请求也触及 prompt-too-long 限制，则分批截断最旧的消息后重试（最多 3 次）。

### 2.6 压缩与计量

压缩完成后：

- `last_api_usage` 被清除——压缩前的真实用量已不再代表压缩后的上下文。
- `context_tokens` 回退到纯本地估算（含 4/3 保守系数），直到下一次 API 调用返回新的真实值。
- 压缩警告被抑制，直到下一次 API 响应——因为压缩后 token 计数不准确（与 Claude Code 的 `suppressCompactWarning` 行为一致）。
- 压缩 API 调用自身的用量**不计入**累积用量——它属于内部记账，与 Claude Code 相同。

这保证了压缩后上下文显示不会出现陈旧的（虚高的）值，并在下一次 API 调用时自动校正。
