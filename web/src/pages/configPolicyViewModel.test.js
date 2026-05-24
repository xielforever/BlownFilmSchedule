import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildConfigAuditMeta,
  buildSchedulePolicyPayload,
  numericPolicyFieldGroups,
  listPolicyFields,
} from './configPolicyViewModel.js';

test('buildSchedulePolicyPayload includes solver, bucket, screening and review strategies', () => {
  const draft = {
    review_required: true,
    manual_adjust_enabled: true,
    manual_adjust_reason_required: true,
    publish_with_warnings_allowed: false,
    auto_release_enabled: false,
    material_constraint_enabled: true,
    maintenance_constraint_enabled: true,
    setup_rules_enabled: true,
    cleanroom_constraint_enabled: true,
    machine_capability_constraint_enabled: true,
    due_date_optimization_enabled: true,
    continuous_run_limit_mins: 4320,
    phase2_feasible_tardiness_tolerance_mins: 30,
    solver_time_limit_seconds: 45,
    solver_relative_gap_limit: 0.05,
    solver_random_seed: 11,
    solver_num_workers: 4,
    planning_must_schedule_horizon_days: 2,
    planning_candidate_horizon_days: 10,
    candidate_reject_penalty: 5000,
    candidate_max_deferred_count: 3,
    candidate_min_acceptance_ratio: 0.75,
    arc_pruning_max_setup_mins: 180,
    arc_pruning_top_k_per_order: 4,
    screening_due_risk_min_slack_mins: 360,
    screening_due_risk_duration_multiplier: 2,
    manual_adjust_review_delay_threshold_mins: 20,
    manual_adjust_review_setup_threshold_mins: 15,
    manual_adjust_review_tardiness_threshold_mins: 10,
    screening_allowed_order_statuses: 'PENDING, RELEASED',
    screening_prohibited_override_codes: 'no_eligible_machine,status_not_pending',
    screening_restricted_override_codes: ['material_not_ready', 'due_risk'],
    screening_required_positive_order_fields: 'due_date_mins,target_width,total_quantity_kg',
  };

  const payload = buildSchedulePolicyPayload(draft, '业务策略调优');

  assert.equal(payload.change_reason, '业务策略调优');
  assert.equal(payload.solver_time_limit_seconds, 45);
  assert.equal(payload.candidate_max_deferred_count, 3);
  assert.equal(payload.candidate_min_acceptance_ratio, 0.75);
  assert.deepEqual(payload.screening_allowed_order_statuses, ['PENDING', 'RELEASED']);
  assert.deepEqual(payload.screening_restricted_override_codes, ['material_not_ready', 'due_risk']);
  assert.deepEqual(payload.screening_required_positive_order_fields, [
    'due_date_mins',
    'target_width',
    'total_quantity_kg',
  ]);
});

test('policy field metadata exposes configurable non-boolean strategy groups', () => {
  assert.ok(numericPolicyFieldGroups.some(group => group.keys.includes('candidate_min_acceptance_ratio')));
  assert.ok(numericPolicyFieldGroups.some(group => group.keys.includes('arc_pruning_top_k_per_order')));
  assert.ok(listPolicyFields.some(field => field.key === 'screening_allowed_order_statuses'));
});

test('buildConfigAuditMeta includes policy version for traceability', () => {
  const meta = buildConfigAuditMeta(
    {
      config_key: 'solver_time_limit_seconds,screening_allowed_order_statuses',
      changed_by: 'planner-a',
      policy_version: 7,
      created_at: '2026-05-24T10:30:00Z',
    },
    value => `time:${value}`,
  );

  assert.equal(
    meta,
    '求解时间上限、允许入池订单状态 · 版本 #7 · planner-a · time:2026-05-24T10:30:00Z',
  );
});
