# Token Metering & Context Management

> [中文](../zh-CN/token-metering.md) | English

This document explains how IllusionForge measures token usage, calculates context occupancy, and manages the context window through compaction.

---

## 1. Token Metering

### 1.1 The `/context usage` Output Explained

The `/context usage` command shows a complete breakdown of the current context state. Example output (after normal conversation with cache hits):

```
Context Window: 1,000,000 tokens
Input (Cached): 175,200 tokens (18%)
Input (Uncached): 12,700 tokens (1%)
Output: 12,200 tokens (1%)
Cache Hit Rate: 93%
Context Used: 200,100 tokens (20%)
Remaining: 799,900 tokens
Cumulative Usage: cached=1,230,000 uncached=187,900 output=12,200
```

| Line | Meaning | Source |
|------|---------|--------|
| Context Window | The configured context window size | `settings.context_window` |
| Input (Cached) | Cached input of the **last API call** = `cache_read` + `cache_creation` (includes hits and writes) | `last_api_usage` |
| Input (Uncached) | Uncached input of the **last API call** (these tokens are written to cache by automatic caching and will be cached on the next call) | `last_api_usage.input_tokens` |
| Output | Output of the **last API call** | `last_api_usage.output_tokens` |
| Cache Hit Rate | `cache_read` / (`cache_read` + `cache_creation` + `input_tokens`), only counts tokens actually read from cache (see §1.4) | `last_api_usage` |
| Context Used | Current context occupancy = last API call's `context_size` + estimated delta of messages added after it (§1.5) | `engine.current_context_tokens()` |
| Remaining | Context Window − Context Used | computed |
| Cumulative Usage | Session totals across all API calls, accumulated by `CostTracker` (cached = hits + writes) | `engine.total_usage` |

Note that the top three lines (Input Cached / Uncached / Output) and Cache Hit Rate describe the **last API call**, while the bottom line describes the **whole session** — they are different scopes.

Before the first API call, or right after compaction (`last_api_usage` is invalidated), only the estimated lines are shown:

```
Context Window: 1,000,000 tokens
Context Used: 0 tokens (0%)
Remaining: 1,000,000 tokens
Cumulative Usage: cached=0 uncached=0 output=0
```

### 1.2 Data Sources

Two independent measurements are tracked:

- **Last API call usage** (`last_api_usage`): the exact `usage` object returned by the most recent API call, including cache breakdown. This is the basis for the StatusBar and context occupancy display.
- **Cumulative usage** (`total_usage`): the sum of all API calls in the session, accumulated by `CostTracker`. Shown in `/context usage` and the Web RightPanel "Cumulative API Usage" block.

### 1.3 Protocol Differences (Important)

The meaning of usage fields differs between API formats:

**Anthropic Messages API:**

```json
"usage": {
    "input_tokens": 8,                        // uncached input (billed)
    "cache_creation_input_tokens": 5501,      // tokens written to cache
    "cache_read_input_tokens": 0,             // tokens read from cache (hit)
    "output_tokens": 4
}
```

- `input_tokens` does **not** include cached tokens.
- Total input = `input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens`.

**OpenAI Chat Completions / Responses API:**

```json
"usage": {
    "prompt_tokens": 5509,                    // total input (INCLUDES cached)
    "completion_tokens": 4,
    "prompt_tokens_details": { "cached_tokens": 5501 }
}
```

- `prompt_tokens` (or `input_tokens` in Responses) **includes** cached tokens.
- Uncached input = `prompt_tokens` - `cached_tokens` (nested in `prompt_tokens_details` / `input_tokens_details`).

**Unified field mapping:**

| Internal field | Anthropic source | OpenAI source |
|----------------|------------------|---------------|
| `input_tokens` (uncached) | `usage.input_tokens` | `prompt_tokens - cached_tokens` |
| `cache_read_input_tokens` (hit) | `usage.cache_read_input_tokens` | `prompt_tokens_details.cached_tokens` |
| `cache_creation_input_tokens` (write) | `usage.cache_creation_input_tokens` | `0` (not distinguished) |
| `output_tokens` | `usage.output_tokens` | `completion_tokens` |

### 1.4 Cache Hit Rate

- **Hit rate** = `cache_read_input_tokens` / (`cache_read_input_tokens` + `cache_creation_input_tokens` + `input_tokens`)

Only counts tokens actually **read** from cache (`cache_read`), not tokens written to cache for the first time (`cache_creation`). Cache writes will become hits on the next call.

Example (assuming `cache_read=8000`, `cache_creation=4000`, `input=8000`):

```
Hit rate = 8000 / (8000 + 4000 + 8000) = 40%
```

| Frontend | Display |
|----------|---------|
| Web RightPanel | Single row "Cache Hit Rate" |
| `/context usage` | Single row "Cache Hit Rate" |

> **Note: Hit rate is 0% on the first call.** On the first API call, `cache_read=0` (cache is empty) and `cache_creation>0` (writing to cache), so the hit rate is 0%. The hit rate rises from the second call onward.

### 1.5 Context Occupancy Calculation

```
context_tokens = last_api_usage.context_size + estimate(new messages since last API call)
```

where:

```
context_size = input_tokens + cache_read_input_tokens + cache_creation_input_tokens + output_tokens
```

The last API call's real `context_size` is used as the baseline, and any messages added after that call are estimated locally (character-based heuristic with a 4/3 conservative padding). This mirrors Claude Code's `tokenCountWithEstimation` approach — real usage as the baseline, estimation only for the delta — to avoid underestimating the context (which would cause compaction to trigger too late and the API call to fail).

After compaction, `last_api_usage` is invalidated and the context falls back to pure estimation until the next API call provides a new real value.

---

## 2. Compaction

Compaction frees context window space when the conversation grows too large. There are two levels:

### 2.1 Micro-Compaction (Microcompact)

**What it does:** Clears the content of old compactable tool results (from `read_file`, `bash`, `grep`, `glob`, `web_search`, `web_fetch`, `edit_file`, `write_file`), replacing them with the placeholder `[Old tool result content cleared]`. Keeps the most recent 5 compactable tool results. No LLM call is needed — it is cheap and fast.

**When it triggers:** As the first step of auto-compaction (see below). If micro-compaction alone frees enough tokens to drop below the threshold, full compaction is skipped.

### 2.2 Full Compaction (LLM Summary)

**What it does:** Calls the LLM to generate a structured summary of the older messages, which replaces them. Preserves the most recent 6 messages verbatim. The result is `[summary] + [COMPACT_BOUNDARY marker] + recent messages`. This costs one extra LLM call.

**When it triggers:** When micro-compaction is not enough, or when triggered manually via `/compact`.

### 2.3 Thresholds

```
effective_context_window = context_window - min(max_output_tokens, 20,000)   // reserve space for output
auto_compact_threshold    = effective_context_window - 13,000                // buffer
warning_threshold         = auto_compact_threshold - 20,000                  // "approaching" warning
blocking_limit            = context_window - 3,000                           // when auto-compact is disabled
```

| Threshold | Condition | Behavior |
|-----------|-----------|----------|
| Warning | `context_tokens >= warning_threshold` | Shows "context almost full" status |
| Auto-compact | `context_tokens >= auto_compact_threshold` | Triggers micro-compact first, then full compact if needed |
| Blocking | `context_tokens >= blocking_limit` (auto-compact disabled) | Blocks further input until manually compacted |

The check runs at the start of every agentic turn inside `run_query`, before the API call. The context value used is the same as `/context usage` displays (last API call's real `context_size` + estimated delta), keeping the two consistent.

### 2.4 Auto-Compaction Flow

1. At the start of each turn, if `context_tokens >= auto_compact_threshold`, micro-compaction runs first.
2. The freed tokens are subtracted from `context_tokens`; if it now falls below the threshold, only micro-compaction happened.
3. Otherwise, full compaction (LLM summary) runs, preserving the recent 6 messages.
4. After 3 consecutive compaction failures, a circuit breaker stops retrying (the context is irrecoverably over the limit).

### 2.5 Reactive Compaction

If the API returns a `prompt too long` error, reactive compaction is triggered: it first tries micro-compaction, then full compaction, and retries the request. If compaction itself hits the prompt-too-long limit, the oldest messages are truncated in chunks and retried (up to 3 times).

### 2.6 Compaction and Metering

After compaction:

- `last_api_usage` is invalidated — the pre-compaction real usage no longer represents the compacted context.
- `context_tokens` falls back to pure local estimation (with conservative 4/3 padding) until the next API call returns a new real value.
- The compaction warning is suppressed until the next API response, because token counts are not accurate right after compaction (same behavior as Claude Code's `suppressCompactWarning`).
- The compaction API call's own usage is **not** added to the cumulative usage — it is internal bookkeeping, same as Claude Code.

This ensures the context display never shows a stale (over-estimated) value after compaction and self-corrects on the next API call.
