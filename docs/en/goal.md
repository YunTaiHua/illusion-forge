# Goal Feature

> [中文](../zh-CN/goal.md) | English

IllusionForge's goal subsystem provides **persisted same-session completion objectives** with **autonomous continuation rounds**: bind a long-running multi-turn task as a goal on the current session, and the driver automatically injects round messages after each turn until completion, blockage, or the round cap. The goal lifecycle and authority are managed by a unified state machine, and completion claims are verified by a single adversarial verifier.

## Concepts

- **goal**: one durable completion objective bound to the current session. Phases: `active | paused | blocked | complete`; every durable mutation bumps a `revision` (CAS fence, see below).
- **goal round**: one autonomous continuation cycle. When a goal is active, the driver injects a `<goal_round>` user message after each turn ends, until completion, blockage, or the round cap (`max_goal_rounds`, default 256).
- **goal activation**: process-local `armed | disarmed`, **not persisted**. After session restore/new, activation is always `disarmed` — only a human request to continue (model calls `update_goal action=resume`) rearms it.

### Phase Transitions

| Operation | Source Phase | Target Phase | Authority | Notes |
| --- | --- | --- | --- | --- |
| `create` | none | `active` (armed) | human | Created armed; autonomous rounds start immediately |
| `edit` | active / paused / blocked | unchanged | human | Replace objective / round cap; not allowed on complete |
| `pause` | active | `paused` (disarmed) | human | Stops after the current round finishes |
| `resume` | paused / blocked | `active` (armed) | human | **Only rearm path** |
| `complete` | active / paused / blocked | `complete` (disarmed) | human or goal round | Only finalised after adversarial verification |
| `blocked` | active / paused | `blocked` (disarmed) | human, goal round or internal | Blocked with a reason code |

> **Note**: `resume` is the only way to rearm. After `/resume`, `/fork`, or any session restore, activation is always `disarmed` — the goal will not auto-continue until a human explicitly instructs continuation.

### CAS Revision Fence

`revision` is a **compare-and-swap (CAS) fence**: starts at 1, incremented on every durable mutation. All mutation operations must carry the exact `(id, revision)` read by the caller; mismatches are rejected with an error message containing the current values, so the model can retry immediately without an extra `get_goal` round-trip.

## Usage

### Human Command

```
/goal [<objective>|clear|edit <objective>|pause|resume]
```

- `/goal fix the login crash`: create a goal and start autonomous rounds immediately
- `/goal`: show current goal status (objective / phase / activation / rounds / revision)
- `/goal pause`: pause (stops after the current round)
- `/goal resume`: resume and immediately drive continuation
- `/goal edit <new objective>`: edit the objective
- `/goal clear`: clear the goal

`create` and `resume` return `drive_goal=True`, which triggers immediate goal round driving; all other operations are pure state mutations.

### Model Tools

| Tool | Purpose |
| --- | --- |
| `get_goal` | Read the current goal (exact id/revision/phase/rounds/activation/blocked reason); call before updating |
| `create_goal` | Create a goal (requires a direct human turn; intent may be inferred without explicit "create a goal" wording) |
| `update_goal` | `edit / pause / resume / complete / blocked` (edit/pause/resume require human; complete/blocked accept human or goal round) |

All three tools share a unified `GOAL_OUTPUT` compact JSON format: `{ goal: { id, revision, objective, phase, roundsStarted, maxGoalRounds, blockedReason? }, activation }`.

## Round Driving

After each turn, the engine checks `should_continue()` and injects the next `<goal_round>` message only when **active + armed + rounds under cap + no pending wrap-up**:

- `admit_round()` increments `rounds_started` by one; if at the cap, it auto-blocks with `block('round-limit')` and stops.
- Round messages are tagged with source `goal`, which determines tool authority checks (`human` vs `goal`).
- Backend drivers (`ws_host`) immediately drive continuation on `resume` when the session is idle, and guard `active_line_task` uniqueness against rapid double-clicks causing orphan tasks.

## Completion Verification

When the model claims completion via `update_goal(action: "complete")`, the harness (not the model) synchronously spawns **one** adversarial verifier subagent — reusing IllusionForge's own `verification` agent definition (`coordinator/agent_definitions.py`, whose system prompt requires a trailing `VERDICT: PASS|FAIL|PARTIAL` line).

- Evidence packet layout: `OBJECTIVE / CHANGES_FILE / CHANGED_FILES / PLAN_CHANGES / FINAL_RESPONSE / PRIOR_GAPS` (prefers git porcelain + `git diff HEAD`, falls back to file-history; patch file truncated at 256 KiB).
- **Fail-closed**: an unparseable verifier output synthesises a FAIL, rejecting the completion claim.
- **Infra fail-open**: if the verifier cannot be spawned (infrastructure failure), completion is accepted so harness bugs never wedge the user.
- FAIL/PARTIAL → gaps are fed back to the implementer; the goal stays active.
- Consecutive rejections reaching `verification_max_attempts` (default 10) → auto-blocked (`verification-cap`).
- Identical gap fingerprints (normalised report hash) across consecutive attempts → auto-blocked (`verification-stall`).
- Under goal-round source, `blocked` before `blocked_after_consecutive_rounds` (default 3) rounds is mechanically rejected (`GOAL_TOOL_BLOCK_THRESHOLD`).

### Blocked Reason Codes

| code | Trigger |
| --- | --- |
| `round-limit` | Autonomous rounds reached `max_goal_rounds` |
| `model-reported` | Model reports a blocker via `update_goal(action="blocked")` |
| `verification-cap` | Verification rejections reached `verification_max_attempts` |
| `verification-stall` | Same gap fingerprint repeated across consecutive attempts |

## Frontends

- **Web**: GoalBar above the composer — phase label + objective + round counter (`roundsStarted/maxGoalRounds`) + action icons (pause when active, resume when paused, always edit and clear). Edit switches to an inline form (Enter to save, Esc to cancel, blank disables save). Blocked state shows the blocker reason. Editing is available during active state and takes effect on subsequent rounds without interrupting the current one; pause means "stops after the current round finishes".

## Configuration (`settings.json`)

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

| Field | Default | Description |
| --- | --- | --- |
| `enabled` | `true` | Enable the goal subsystem |
| `default_max_goal_rounds` | `256` | Default automatic continuation round limit |
| `blocked_after_consecutive_rounds` | `3` | Minimum consecutive rounds before `blocked` is allowed under goal-round source |
| `verification_enabled` | `true` | Enable adversarial verification |
| `verification_max_attempts` | `10` | Verification rejections before auto-blocking |

## Persistence

Goal state is persisted as `_goal` rows (last-wins snapshots) in the session's `context.jsonl`; `/resume` and `/fork` restore it automatically, but activation is always `disarmed` afterwards (a human `resume` is required to rearm). `/new` and full_reset clear the goal state entirely.

## Error Codes

| code | Semantics |
| --- | --- |
| `GOAL_TOOL_INVALID_UPDATE` | Parameter or CAS validation failed (empty objective, id/revision mismatch, etc.) |
| `GOAL_TOOL_AUTHORITY_REQUIRED` | Insufficient authority: mutation requires human or current goal round |
| `GOAL_TOOL_BLOCK_THRESHOLD` | `blocked` before the minimum consecutive round count under goal-round source |
| `GOAL_TOOL_CONFLICT` | State conflict (e.g. creating a goal when one already exists) |

## Typical Workflow

1. User proposes a long-running task → model calls `create_goal` (or the human types `/goal <task>`), the goal enters `active` and is armed.
2. After each turn, a `<goal_round>` is automatically injected to continue execution until completion or blockage.
3. Model claims `complete` → adversarial verification: PASS finalises the terminal state; FAIL/PARTIAL feeds gaps back for continued fixing.
4. The human can interrupt at any time with `/goal pause` (stops after the current round), `/goal edit` (rewrites the objective, takes effect on subsequent rounds), `/goal resume` (resumes and continues), or `/goal clear` (removes the goal).
