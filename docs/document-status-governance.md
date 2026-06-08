# Document Status Governance

**Generated**: 2026-05-26
**Status**: active
**Owner**: scheduling planning workspace

## Purpose

This file is the repository-level register for root documentation status. It prevents plan documents from drifting into ambiguous states such as "probably done", "partially done", or "done in chat only".

The register is intentionally separate from each plan. Individual plans can keep detailed task history; this file answers the operational question: can a later worker trust the document as current, completed, superseded, or only a draft?

## Status Model

| Status | Meaning |
| --- | --- |
| `draft` | The document is a proposal or rough plan and must not drive implementation without review. |
| `active` | The document is current and can drive follow-up work, but not all scope is complete. |
| `implemented` | The planned work has been implemented, but evidence may be limited to local notes or partial verification. |
| `verified` | The planned work has implementation evidence and explicit verification commands, reports, commits, or browser checks. |
| `superseded` | The document is preserved for context, but a newer document or implemented flow is authoritative. |
| `archived` | The document is historical and should not drive new work unless explicitly reopened. |

## Governance Rules

- Every root-level file under `docs/*.md` must appear in the register below.
- `implemented` and `verified` rows must include evidence. Evidence can be a commit, test command, benchmark artifact, browser smoke, or another tracked document that records verification.
- A document with open future scope should remain `active`, even if several earlier sprints are complete.
- Generated benchmark reports under `output/*.md` are not governed here; they are evidence artifacts, not planning documents.
- Files under `docs/superpowers/` are execution traces/specs and are not part of this root register.
- Do not mark a document `verified` based only on chat memory. Add a command, artifact, commit, or explicit verification note.

## Document Register

| Path | Status | Evidence |
| --- | --- | --- |
| docs/config-policy-setup-rules-closed-loop-goal-plan.md | verified | commit `ee320cc`; policy tests and config e2e noted in document |
| docs/deployment_guide.md | active | operational deployment and runbook guide; not an implementation backlog |
| docs/git-status-cleanup-goal-plan.md | archived | historical cleanup plan; execution results list commits `6371180`, `ee320cc`, `2b88ab0`, `118dab5` |
| docs/order-flow-closed-loop-goal-plan.md | verified | document lists P0/P1 acceptance cases completed and verification commands |
| docs/real_data_scheduling.md | active | operational guide for current database scheduling checks |
| docs/root-cause-guidance-plan.md | superseded | root-cause implementation tracked by `docs/root-cause-guidance-todo.md` |
| docs/root-cause-guidance-todo.md | verified | phases 1-5 complete; what-if evidence in `POST /api/schedule/what-if/order`, `tests/test_policy_settings.py`, and `tests/test_api.py` |
| docs/solver-optimization-business-plan.md | verified | Sprint 6 evidence in `output/sprint6-quality-300-postsolve-gated.md`; locked-task, policy, screening, benchmark, and workbench evidence listed in the document |
| docs/workbench-interaction-cleanup-goal-plan.md | verified | document execution status says P0/P1/P2 verified on 2026-05-23 |
| docs/workbench-p1-p2-todo-validation-plan.md | verified | final verification section lists pytest, lint, build, e2e, and browser smoke |
| docs/workbench-wizard-flow-goal-plan.md | verified | document status says implementation completed and regression verified |
| docs/workbench-worker-qa-hardening-goal-plan.md | verified | completion evidence section lists backend/UI fixes, pytest, lint, build, e2e, browser checks, and lock-wait check |

## Closure Audit 2026-06-08

- Project-plan documents that previously looked open have been reclassified based on tracked evidence, not chat memory.
- `docs/root-cause-guidance-todo.md` is verified because the remaining what-if work has been implemented for single-order screening diagnostics.
- `docs/solver-optimization-business-plan.md` is verified for the current goal scope through Sprint 6. Further solver research should start as a new goal with a new benchmark target.
- `docs/workbench-worker-qa-hardening-goal-plan.md` is verified because its Definition of Done and completion evidence are already recorded.
- `docs/real_data_scheduling.md` remains active as an operational guide, not an unfinished implementation plan.

## Validation

Run this before claiming the documentation register is current:

```powershell
python scripts/validate_doc_status.py
```

The script checks root `docs/*.md` coverage, known status values, existing paths, and evidence for `implemented` or `verified` rows.
