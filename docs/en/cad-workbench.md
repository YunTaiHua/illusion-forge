# CAD Workbench

> [中文](../zh-CN/cad-workbench.md) | English

By combining the headless geometry and SolidWorks COM automation capabilities of [solidworks-automation-skill](https://github.com/wzyn20051216/solidworks-automation-skill) (MIT License), IllusionForge ships with a storyboard-style engineering workbench: **discuss design variants on a shared canvas → generate headless 3D previews → live-visualized SolidWorks modeling → bidirectional selection sync → variant↔model lineage audit**.

## Table of Contents

- [Overview](#overview)
- [Enabling & Layout Switching](#enabling--layout-switching)
- [Two-Phase Workflow: Discuss → Model](#two-phase-workflow-discuss--model)
- [Architecture](#architecture)
- [Tool Reference (51 tools)](#tool-reference-51-tools)
- [Modeling Visualization](#modeling-visualization)
- [Selection Sync (Bidirectional Collaboration)](#selection-sync-bidirectional-collaboration)
- [Variant ↔ Model Lineage](#variant--model-lineage)
- [Configuration Reference](#configuration-reference)
- [Permissions & Security](#permissions--security)
- [Testing & Verification](#testing--verification)
- [Upstream Attribution and Sync](#upstream-attribution-and-sync)
- [Appendix: Implementation & Review History](#appendix-implementation--review-history)

---

## Overview

The CAD workbench is an **optional feature**: when `workbench.enabled` is off, no CAD tools are registered and heavy dependencies (pywin32/OCP) are never imported — platform behavior is unchanged. The canvas view itself is not gated by the switch and can be used manually at any time.

Four capability layers:

| Milestone | Capability | Description |
|-----------|------------|-------------|
| M1 Discussion loop | Shared canvas + headless 3D preview | React Flow canvas with variant/requirement/preview cards; 3D previews without launching SolidWorks |
| M2 Modeling loop | SolidWorks modeling + live visualization | STA COM session host + 24 modeling tools; snapshot stream, mirrored feature tree, storyboard cards |
| M3 Collaboration loop | Selection sync + escape hatch + wave-2 tools | User selections in SolidWorks flow into agent context automatically; `cad_python` covers unwrapped APIs |
| M4 Deepening | Variant↔model lineage + multi-document + sheet metal/weldment | Dimension-level design-intent diff; document-level state invalidated on switch |

---

## Enabling & Layout Switching

The bottom of the sidebar hosts a **two-key segmented switch** (`Chat` | `Workbench`):

- Click **Workbench**: switches to the canvas layout (canvas column + conversation panel) and **automatically creates a new workbench session**; `workbench.enabled` and `default_view` are written to settings for new sessions.
- Click **Chat**: switches to the chat layout and **automatically creates a new chat session**; the two session types are kept separate.

Setting semantics: `workbench.enabled` and `default_view` are written only by the segmented switch and take effect for **new sessions** — already-running sessions are unaffected. The sidebar session list is split by type: chat sessions never include workbench sessions and vice versa, and the two kinds can run side by side without interfering.

The Web settings "CAD Workbench" tab shows the enabled state **read-only** and lets you configure the other options (`default_view`, `artifacts_dir`, `headless_occt`, `visualization`). There is no "enable CAD workbench" toggle in the settings form.

Workbench layout:

```
┌──────────────────────────────┬────────────┐
│   React Flow shared canvas    │ Conversation│
│  [Requirement][Variant][3D]   │   Panel     │
│  [Snapshot/storyboard][Spec]  │ (title bar,│
│                              │  messages,  │
│                              │  composer)  │
└──────────────────────────────┴────────────┘
```

The conversation panel on the right contains a title bar, message area, and composer at the bottom.

The live modeling card is **collapsed by default** into a small pill in the canvas top-right. When the `cad_connect` tool runs it auto-expands into a floating card (~300px wide, not taking canvas width nor squeezing the composer) with three tabs in its header: **Viewport** / **Feature Tree** / **Snapshots**.

The workbench welcome screen shows only the app icon plus **"Start your design"**.

---

## Two-Phase Workflow: Discuss → Model

**Discussion phase (no SolidWorks required)**: the agent creates a variant card per design direction on the canvas, generates GLB preview cards with the headless geometry kernel (box/cylinder compositions) and pins them for side-by-side comparison. GLBs come from a pure-Python mesh writer (zero native dependencies); with the OCP runtime installed, STEP/IGES exchange formats are produced as well.

**Modeling phase (SolidWorks required)**: once a variant is chosen, the agent attaches to (or launches) SolidWorks via `cad_connect` and translates the agreed design into a feature-operation sequence. Every operation streams to the workbench live; keyframes are pinned onto the canvas as storyboard cards.

---

## Architecture

```
illusion-forge/
├── src/illusion/cad/
│   ├── vendor/             # 20 upstream modules, vendored verbatim (MIT, diff-syncable)
│   ├── host.py             # ★ STA COM session host: dedicated thread + serial job queue
│   ├── events.py           # cad_update event broadcast
│   ├── canvas_store.py     # Canvas document source of truth (CRUD + persistence + broadcast)
│   ├── glb_writer.py       # Triangle soup → binary GLB (zero native deps)
│   ├── preview.py          # Friendly params → NeutralCadDocument → headless export
│   ├── health.py           # Environment health check (winreg probe, no pywin32 needed)
│   ├── context.py          # Session context injection (system-prompt section)
│   └── tools/              # Tool registration: M1 base + M2 modeling + M3 collab + M4 production
├── src/illusion/ui/web/cad_routes.py   # Artifact file serving (restricted paths + auth)
└── frontend/web/src/components/canvas/ # React Flow canvas + card rendering
```

**STA host thread model** (`host.py`): SolidWorks COM objects must be used on the apartment that created them. The host converges all COM operations onto one dedicated thread (`pythoncom.CoInitialize()`) with a serial job queue; tools only exchange plain data. Key semantics:

- **Timeouts**: COM calls cannot be killed; a timeout returns the `cad_busy` error code while the task keeps running in the background — busy state is reported honestly via events;
- **Restart contract**: when the thread dies and restarts, all COM pointers (`_sw`/motion slot) are cleared — subsequent tasks get a clear `cad_not_connected` instead of dangling pointers;
- **Document identity**: the `(GetTitle, GetPathName)` tuple — switching documents automatically invalidates document-level state such as Motion Studies;
- **Thread-death hardening**: failures in post-task payload building/broadcast can never kill the thread (a dead thread would stall every queued task).

---

## Tool Reference (51 tools)

Registered when `workbench.enabled` is on (79 total tools → 51 in the CAD domain). Lengths are millimeters, angles are degrees (converted via `mm()/deg()` internally).

### Canvas & headless preview (M1, no SolidWorks)

| Tool | Description |
|------|-------------|
| `cad_health_check` | Environment health report (platform / SolidWorks registry probe / dependencies) |
| `cad_preview_build` | Headless 3D preview (box/cylinder composition → GLB/STEP), pins a card to the canvas by default |
| `canvas_add_node` / `canvas_update_node` / `canvas_remove_node` | Canvas card operations (requirement/variant/preview/snapshot/spec/note) |

### SolidWorks modeling (M2)

| Domain | Tools |
|--------|-------|
| Session | `cad_connect` `cad_session_status` `cad_new_document` `cad_open_document` `cad_save_document` `cad_close_documents` |
| Part | `cad_sketch_add` (8 primitives in one) `cad_feature_extrude` (boss/cut/midplane) `cad_feature_revolve` `cad_feature_fillet` `cad_feature_chamfer` `cad_feature_pattern` (linear/circular) `cad_feature_shell` `cad_feature_mirror` `cad_feature_rib` `cad_hole_create` (4 hole types) `cad_dimension_update` |
| Assembly | `cad_component_add` `cad_mate_add` (coincident/distance) `cad_assembly_inspect` (components+mates+interference) |
| Visualization/Review/Export | `cad_camera_direct` (10 views) `cad_snapshot` `cad_review_run` `cad_export` (step/stl/iges/pdf/dxf) |

### Collaboration loop (M3)

| Domain | Tools |
|--------|-------|
| Escape hatch | `cad_python` (run arbitrary Python inside the host thread with a pre-bound namespace) |
| Config/Properties | `cad_config_inspect` `cad_config_activate` `cad_config_create` `cad_properties_set` |
| Delivery | `cad_bom_export` (UTF-8 CSV + SHA-256) `cad_pack_and_go` |
| Motion | `cad_motion_create` `cad_motion_add_motor` `cad_motion_calculate` `cad_motion_summary` |
| Appearance/Drawings | `cad_appearance_set` `cad_drawing_generate` (GB/ISO frames) `cad_drawing_export_pdf` `cad_drawing_inspect` |

### Production (M4)

| Domain | Tools |
|--------|-------|
| Lineage | `cad_document_link` `cad_dimension_diff` |
| Multi-document | `cad_documents_list` `cad_document_activate` |
| Sheet metal/Weldment | `cad_sheet_metal_base_flange` `cad_sheet_metal_evidence` `cad_weldment_cut_list` |

---

## Modeling Visualization

After every CAD operation the host builds an `{state, active document, feature tree, latest snapshot frame, user selection}` payload and broadcasts it as a `cad_update` WebSocket event through a thread-safe hop back to the event loop:

- **Live viewport**: snapshot frames are 960×600 BMPs (`SaveBMP` pipeline) stored under `<workspace>/.illusion/cad_artifacts/snapshots/`, served same-origin via `/api/cad/artifact` and refreshed live;
- **Mirrored feature tree**: the panel renders the FeatureManager structure in real time;
- **Storyboard cards**: feature-type operations (extrude/revolve/hole/pattern…) automatically pin their snapshot onto the canvas, building the operation narrative;
- **Camera choreography**: `cad_camera_direct` switches standard views between operations so the part "grows under the camera".

---

## Selection Sync (Bidirectional Collaboration)

While the job queue is idle, the host thread polls the active document and `ISelectionMgr` selections every 2 seconds and **broadcasts only on change**. Three consumers:

1. The web live panel shows a "Selected" badge;
2. The `cad_update` event carries a `selection` field;
3. **System-prompt injection**: every turn, prompt building appends a `# SolidWorks Session` section (state/document/selection) — the user selects a face in SolidWorks and the agent knows next turn, without calling any tool. Injection reads only host cross-thread caches: zero COM calls, zero blocking.

---

## Variant ↔ Model Lineage

- `cad_document_link(node_id)`: binds the active document to a canvas variant card as its realized model (writes `model_path/model_title/linked_at`) and snapshots `data.params` as the design-intent baseline; variant cards render a "Linked model" badge;
- `cad_dimension_diff(node_id)`: reads actual named dimensions from the model and compares them against the baseline row by row (match / mismatch+delta / missing) — the audit loop between evolving intent and the realized model.

---

## Configuration Reference

```jsonc
// ~/.illusion/settings.json
"workbench": {
  "enabled": false,        // register the CAD tool domain for new sessions; canvas view is not gated
  "default_view": "chat",  // default web layout (chat | canvas)
  "artifacts_dir": null,   // artifacts root; defaults to <workspace>/.illusion/cad_artifacts
  "headless_occt": true,   // also emit STEP/IGES when OCP is available
  "visualization": {
    "live_stream": true,
    "interval_ms": 800,
    "jpeg_quality": 75,
    "camera_choreography": true
  }
}
```

---

## Permissions & Security

- **Risk tiers**: read-only tools (status/inspect/snapshot/review/camera) are LOW and auto-allowed; mutating tools (modeling/save/close/cad_python) are MEDIUM and prompt by default. Pre-allow frequent tools via `settings.permission.allowed_tools`; do not pre-allow save/quit; `cad_python` can be disabled entirely via `denied_tools`;
- **`cad_python` capability boundary**: full Python builtins, matching the platform's bash/powershell tools (same permission gating) — builtins are deliberately not restricted; see the tool docstring;
- **Artifact serving**: `GET /api/cad/artifact` serves only files inside the artifacts tree (`Path.resolve()` + `relative_to` validation — symlinks pointing outside are rejected), behind the global auth middleware;
- **Canvas data**: the document source of truth lives locally in the workspace (`.illusion/cad_artifacts/canvas/<session-id>.json`), **isolated per session** — each session gets its own canvas and switching sessions loads the matching one; extension fields belong in each node's `data` dict.

---

## Testing & Verification

- **Automated regression**: `tests/cad/test_cad_workbench.py` (11 tests: canvas contracts, host-thread mechanics, restart contract, selection polling, lineage flow, route path validation);
- **Real-machine smoke**: `python scripts/cad_smoke_test.py [--keep]` — connect → new part → sketch+extrude+hole → multi-view snapshots → cad_python escape hatch → export STEP → cleanup. Cold start takes 1-3 minutes.

---

## Upstream Attribution and Sync

The 20 modules under `src/illusion/cad/vendor/` are vendored verbatim from [wzyn20051216/solidworks-automation-skill](https://github.com/wzyn20051216/solidworks-automation-skill) (MIT License):

- **Headless geometry (4)**: headless_cad_writer / headless_occt_service / dxf_preview_scene / cad_core_contracts
- **COM basics (9)**: sw_preflight / cad_installation / sw_connect / sw_part / sw_assembly / sw_hole_features / sw_document_data / sw_review / sw_export
- **Delivery/Motion/Appearance/Drawings (5)**: sw_delivery / sw_motion / sw_appearance / sw_drawing / drawing_workflow
- **Sheet metal/Weldment (2)**: sw_sheet_metal / sw_weldment

Vendored files carry minimal changes: header attribution, imports rewired to this package, and a few repository-path references. They stay byte-diffable against upstream so updates can be synced by direct copy.

---

## Appendix: Implementation & Review History

Delivered in four milestones (M1 discussion loop → M2 modeling loop → M3 collaboration loop → M4 production), then independently reviewed (0 Critical / 5 Important / 2 Minor). Disposition:

| Finding | Disposition |
|---------|-------------|
| Motion slot invalidated by title only | Fixed: document identity is now the title+path tuple |
| Stale COM pointers after thread death | Fixed: `_ensure_thread` restart contract |
| Full builtins in `cad_python` | Accepted by design, documented (parity with bash, same permission gating) |
| Symlink traversal of artifact serving | Not an issue: `resolve()` + `relative_to` mitigates correctly; test added |
| Full-board replace drops unknown top-level fields | Accepted as a strict contract, documented (extensions go in `data`) |
| Missing automated regression tests | Added `tests/cad/` (11 tests) |
| Cross-thread `_snapshots` access | Locked |
