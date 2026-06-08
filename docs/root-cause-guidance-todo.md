# Root Cause Guidance TODO

**Updated**: 2026-06-08

## Closure Decision

Phases 1-4 are complete and remain the current production baseline for root-cause guidance. Phase 5 is intentionally deferred as a future what-if capability, not a blocker for closing the current scheduling workbench and solver-governance project.

## Phase 1: Structured Diagnostics Core

- [x] Add `src/diagnostics.py` with stable diagnostic, evidence, and recommendation objects.
- [x] Add explainable machine eligibility checks without breaking `can_produce()`.
- [x] Attach infeasible-order diagnostics to `ScheduleResult`.
- [x] Attach lateness, setup burden, high/low load, unused machine, and changeover-heavy diagnostics after a successful solve.
- [x] Export diagnostics in schedule JSON output.

## Phase 2: HTTP Product Loop

- [x] Persist run diagnostics in existing `schedule_runs.solver_params` JSONB.
- [x] Add `GET /api/schedule/diagnostics`.
- [x] Add structured diagnostics to failed schedule trigger status when the child process reports no eligible machine.
- [x] Attach diagnostic metadata to Gantt idle, maintenance, downtime, and late production events.
- [x] Enrich ordinary Gantt idle gaps with order-pool evidence: hard-fit blockers, material waits, assigned-elsewhere orders, and window length.
- [x] Keep raw logs as fallback detail only.
- [x] Surface phase-2 fallback and missing material-switch rules as structured run diagnostics.

## Phase 3: UI Guidance Surfaces

- [x] Add Dashboard `Root Cause & Next Actions` panel.
- [x] Scope Dashboard root-cause panel to blocked, late, and material-constrained orders only.
- [x] Show structured failed-trigger diagnostics before raw logs.
- [x] Add Gantt event detail panel for clicked events.
- [x] Add order configuration warning panel for `?order=...` diagnostics.
- [x] Add machine-level diagnostic cards to `MachinesPage`.

## Phase 4: Real Data Regression

- [x] Add diagnostic unit tests.
- [x] Extend scheduler validation tests for structured infeasible diagnostics.
- [x] Extend Gantt helper tests for idle diagnostic metadata.
- [x] Add regression coverage for concrete idle-gap root causes.
- [x] Document the real-data scheduling path in `docs/real_data_scheduling.md`.
- [x] Browser-smoke Dashboard and Gantt with current database data.
- [x] Export Markdown schedule report with order exceptions and plant-wide root-cause analysis.

## Phase 5: Deferred What-If Enhancement

- [ ] Add non-persistent what-if API for single-order or single-machine changes.
- [ ] Compare current diagnostics with what-if impact.
- [ ] Keep all what-if actions as recommendations, not automatic edits.

**Status**: deferred. Reopen this as a separate goal when the product needs interactive scenario simulation.
