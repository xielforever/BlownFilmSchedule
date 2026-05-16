# Plan: Machine Defaults and Gantt Board

**Generated**: 2026-05-16
**Estimated Complexity**: Medium

## Overview

This plan covers two next-step improvements:

- Machine capability data should be available by default from the local backend, before any order file is uploaded.
- Local machine capability data should come from `data/machines.xlsx`.
- The current embedded Gantt should evolve into a production-facing board with a large-screen view and schedule-derived order status.

The MVP boundary remains unchanged: orders are the only planning input. The system can show schedule status, machine status, changeover/setup state, and plan progress, but it should not introduce manual scheduling, worker allocation, or externally edited plan states.

## Prerequisites

- Use `data/machines.xlsx` as the local machine source.
- Keep `backend/app/machines.py` only as the loader/fallback/conversion layer, not the business source of truth.
- Keep `/api/machines` as the machine capability API.
- Use schedule output from `/api/schedule/run` as the single source for order status.
- Derive current order status strictly from plan times: `start_time`, `production_start_time`, `end_time`, and `plan_finish_time`.
- No external UI library is required in this phase; existing React, CSS, and `lucide-react` are enough.

## Sprint 1: Local Machine Source and Default Loading

**Goal**: The backend reads machine capabilities from `data/machines.xlsx`, and the page shows machine count and capability summary immediately after load without requiring order upload.

**Demo/Validation**:

- Open `http://127.0.0.1:5173/`.
- The `内置机台` metric shows the backend machine count.
- `固定机台配置` shows local machines before order upload.
- Uploading orders, previewing, and running schedules all use the same `data/machines.xlsx` source.

### Task 1.1: Add `data/machines.xlsx`

- **Location**: `data/machines.xlsx`, `backend/app/machines.py`
- **Description**: Move the current built-in machine capability table into a local workbook and make the backend loader read from it.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - `data/machines.xlsx` exists and contains all current local machine rows.
  - Workbook columns map cleanly to `Machine` fields.
  - `built_in_machines()` returns the workbook data.
  - A clear validation error is raised if required machine columns are missing.
- **Validation**:
  - `PYTHONPATH=backend .\.venv\Scripts\python -m pytest backend\tests`
  - `GET /api/machines` returns the same machine count as the workbook.

### Task 1.2: Add Frontend Machine API Client

- **Location**: `frontend/src/lib/api.ts`, `frontend/src/types.ts`
- **Description**: Add `getMachines()` that calls `GET /api/machines` and returns machine count plus machine list.
- **Dependencies**: Task 1.1.
- **Acceptance Criteria**:
  - `MachineCapability` type matches backend response.
  - API errors return readable messages through the existing `parseResponse`.
- **Validation**:
  - `npm run build`
  - Browser smoke confirms request succeeds on page load.

### Task 1.3: Load Machines on App Mount

- **Location**: `frontend/src/main.tsx`
- **Description**: Add `machines` state and fetch local machines with `React.useEffect` when the app starts.
- **Dependencies**: Task 1.2.
- **Acceptance Criteria**:
  - Metric uses `preview?.summary.machine_count ?? machines.length`.
  - `MachineSummary` uses `preview?.machines ?? machines`.
  - Upload/preview does not erase default machine display.
- **Validation**:
  - Open page with no uploaded order file.
  - Verify machine list and count are visible.

### Task 1.4: Clarify Local Machine Source in Docs

- **Location**: `README.md`, `docs/architecture.md`
- **Description**: Document that local machine capabilities are loaded from `data/machines.xlsx` by default.
- **Dependencies**: Task 1.3.
- **Acceptance Criteria**:
  - Docs distinguish order input from local machine configuration.
  - Docs do not imply users must upload a machine sheet for MVP scheduling.
- **Validation**:
  - Manual doc review.

## Sprint 2: Schedule Status Model

**Goal**: Every assignment has a clear status derived from schedule time, not manual intervention.

**Demo/Validation**:

- After generating a schedule, each order displays one of: `待生产`, `换型中`, `生产中`, `已完成`, `延期风险`, `已延期`.
- Status is explainable from `start_time`, `production_start_time`, `end_time`, and `plan_finish_time`.

### Task 2.1: Add Status Derivation Helper

- **Location**: `frontend/src/main.tsx` or a new `frontend/src/lib/scheduleStatus.ts`
- **Description**: Add a pure helper that derives order status from an assignment and an `asOf` timestamp.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - Before `start_time`: `待生产`.
  - Between `start_time` and `production_start_time` when changeover exists: `换型中`.
  - Between `production_start_time` and `end_time`: `生产中`.
  - After `end_time`: `已完成`.
  - If current time passes `plan_finish_time` before completion: `已延期`.
  - If planned finish is close to due date, mark `延期风险`.
- **Validation**:
  - Add focused frontend unit coverage if test framework exists; otherwise validate through build and browser smoke.

### Task 2.2: Add Status Metadata to UI Types

- **Location**: `frontend/src/types.ts`, `frontend/src/main.tsx`
- **Description**: Introduce a local `ScheduleStatus` union and map it to label, color, and priority.
- **Dependencies**: Task 2.1.
- **Acceptance Criteria**:
  - Status colors are distinct from fit-level colors.
  - Status labels appear in task inspector and Gantt blocks.
- **Validation**:
  - `npm run build`
  - Browser smoke after sample schedule generation.

### Task 2.3: Add Current-Time Control

- **Location**: `frontend/src/main.tsx`, `frontend/src/styles.css`
- **Description**: Add a compact `asOf` control with default current time and optional plan-time slider for demo/simulation.
- **Dependencies**: Task 2.1.
- **Acceptance Criteria**:
  - User can view current state at actual time.
  - User can move a time cursor to see status evolution across the schedule.
  - The control is schedule-derived and not an editable production confirmation.
- **Validation**:
  - Move cursor across a generated schedule and verify status changes.

## Sprint 3: Large-Screen Gantt Board

**Goal**: Add a dedicated board view suitable for production meetings or shop-floor display.

**Demo/Validation**:

- Click a `大屏` action from the current workbench.
- Board view fills the viewport, minimizes input/export controls, and emphasizes active orders, machine lanes, due dates, and exceptions.
- Current workbench remains usable for upload, audit, and export.

### Task 3.1: Split Gantt into Reusable Components

- **Location**: `frontend/src/main.tsx`, new `frontend/src/components/GanttBoard.tsx` if the file becomes large
- **Description**: Extract Gantt rendering into a reusable component that accepts assignments, selected task, status metadata, and display mode.
- **Dependencies**: Sprint 2 status helper.
- **Acceptance Criteria**:
  - Existing embedded Gantt still works.
  - Large-screen mode reuses the same scheduling data and status logic.
- **Validation**:
  - `npm run build`
  - Existing browser flow still works.

### Task 3.2: Add Board Mode

- **Location**: `frontend/src/main.tsx`, `frontend/src/styles.css`
- **Description**: Add a route-like local mode or query param such as `?view=board` for the large-screen board.
- **Dependencies**: Task 3.1.
- **Acceptance Criteria**:
  - `大屏` button opens board mode.
  - Board mode has a clear return action.
  - Board mode can run full screen without nested panels or visual clutter.
- **Validation**:
  - Browser smoke at desktop width.
  - Verify no text overlap at common large-screen sizes.

### Task 3.3: Upgrade Gantt Visual Detail

- **Location**: `frontend/src/styles.css`, Gantt component file
- **Description**: Add a stronger time scale, current-time line, due-date markers, status-colored blocks, changeover segment indication, and lane load labels.
- **Dependencies**: Task 3.1, Task 3.2.
- **Acceptance Criteria**:
  - Blocks show order id and status without overflowing.
  - Changeover time is visually distinguishable from production time.
  - Late/risk orders are visible without opening inspector.
  - Machine lanes remain scan-friendly with 20 local machines.
- **Validation**:
  - Browser screenshot checks at desktop and large-screen viewport.
  - Sample schedule visually inspected for overlap and readability.

### Task 3.4: Add Board Summary Strip

- **Location**: Gantt board component, `frontend/src/styles.css`
- **Description**: Add top summary for scheduled jobs, active jobs, changeover jobs, completed jobs, late/risk jobs, average load, and next due order.
- **Dependencies**: Sprint 2.
- **Acceptance Criteria**:
  - Summary updates when `asOf` changes.
  - Summary uses schedule-derived status only.
- **Validation**:
  - Move time cursor and verify summary changes with order states.

## Sprint 4: Browser and Regression Verification

**Goal**: Prove the UI works as a production dashboard and does not regress the schedule core.

**Demo/Validation**:

- Upload `examples/blownfilm_mvp_mock_v2.xlsx`.
- Generate schedule.
- Verify workbench and board mode both show the same assignment count and status logic.

### Task 4.1: Backend Regression

- **Location**: `backend/tests/test_scheduler.py`
- **Description**: Keep backend focused on scheduling data and machine-load output; no manual status persistence.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - Existing scheduler tests pass.
  - No new manual-plan field appears in backend models.
- **Validation**:
  - `PYTHONPATH=backend .\.venv\Scripts\python -m pytest backend\tests`

### Task 4.2: Frontend Build and Browser Smoke

- **Location**: `frontend`
- **Description**: Validate page load, default machines, upload flow, schedule generation, board mode, and status display.
- **Dependencies**: Sprints 1-3.
- **Acceptance Criteria**:
  - `npm run build` passes.
  - In-app browser shows default machines before upload.
  - Board mode has no console errors.
  - Board mode renders non-empty Gantt with status colors.
- **Validation**:
  - `npm run build`
  - In-app browser smoke on `http://127.0.0.1:5173/`

## Testing Strategy

- Backend: keep current scheduler tests and add checks only if backend model fields change.
- Frontend: use TypeScript build as the baseline gate.
- Browser: verify default machine loading before upload, sample upload/run, and board mode after schedule generation.
- Visual QA: inspect desktop and large-screen board for text overflow, lane density, status color contrast, and current-time marker placement.

## Potential Risks & Gotchas

- `当前订单状态` means schedule-plan-derived status in this phase. It is not an MES/shop-floor execution confirmation.
- `data/machines.xlsx` becomes the editable local machine source. The loader must validate columns and preserve the current `Machine` model contract.
- A large-screen Gantt can become unreadable with many tiny jobs. The board needs stable minimum block widths, hover/selection detail, and possibly zoom presets.
- Current date can be outside the mock schedule range. The board should support both real current time and a schedule time cursor so mock/demo schedules remain meaningful.

## Rollback Plan

- Revert frontend machine auto-load and fall back to `preview?.machines`.
- Keep original embedded Gantt while disabling board mode behind a simple conditional.
- Since status is derived client-side, rollback should not require deleting schedule result data.
