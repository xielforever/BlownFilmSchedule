import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildConfigAuditMeta,
  buildSchedulePolicyPayload,
  canTogglePolicyField,
  numericPolicyFieldGroups,
  listPolicyFields,
  policyFieldRuleClass,
  policyAuditRuleClassSummary,
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
    solver_phase1_tardiness_weight: 10000,
    solver_phase1_late_order_penalty: 500,
    solver_phase2_tardiness_weight: 1000,
    solver_max_late_order_count: 83,
    solver_max_weighted_tardiness: 879599,
    solver_time_limit_seconds: 45,
    solver_relative_gap_limit: 0.05,
    solver_random_seed: 11,
    solver_num_workers: 4,
    planning_must_schedule_horizon_days: 2,
    planning_candidate_horizon_days: 10,
    planning_material_ready_horizon_days: 10,
    planning_scarce_machine_threshold: 1,
    planning_force_must_order_classes: 'URGENT,SAMPLE',
    planning_force_must_customer_classes: ['VIP'],
    candidate_reject_penalty: 5000,
    candidate_max_deferred_count: 3,
    candidate_min_acceptance_ratio: 0.75,
    candidate_post_solve_late_defer_count: 7,
    arc_pruning_max_setup_mins: 180,
    arc_pruning_top_k_per_order: 4,
    arc_pruning_same_material_family_top_k: 2,
    arc_pruning_same_cleanroom_top_k: 2,
    arc_pruning_due_window_mins: 1440,
    arc_pruning_due_window_top_k: 3,
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
  assert.equal(payload.solver_phase1_late_order_penalty, 500);
  assert.equal(payload.solver_phase2_tardiness_weight, 1000);
  assert.equal(payload.solver_max_late_order_count, 83);
  assert.equal(payload.solver_max_weighted_tardiness, 879599);
  assert.equal(payload.candidate_max_deferred_count, 3);
  assert.equal(payload.candidate_min_acceptance_ratio, 0.75);
  assert.equal(payload.candidate_post_solve_late_defer_count, 7);
  assert.equal(payload.arc_pruning_same_material_family_top_k, 2);
  assert.equal(payload.arc_pruning_same_cleanroom_top_k, 2);
  assert.equal(payload.arc_pruning_due_window_mins, 1440);
  assert.equal(payload.arc_pruning_due_window_top_k, 3);
  assert.equal(payload.planning_material_ready_horizon_days, 10);
  assert.equal(payload.planning_scarce_machine_threshold, 1);
  assert.deepEqual(payload.planning_force_must_order_classes, ['URGENT', 'SAMPLE']);
  assert.deepEqual(payload.planning_force_must_customer_classes, ['VIP']);
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
  assert.ok(numericPolicyFieldGroups.some(group => group.keys.includes('planning_material_ready_horizon_days')));
  assert.ok(numericPolicyFieldGroups.some(group => group.keys.includes('arc_pruning_top_k_per_order')));
  assert.ok(numericPolicyFieldGroups.some(group => group.keys.includes('arc_pruning_same_material_family_top_k')));
  assert.ok(numericPolicyFieldGroups.some(group => group.keys.includes('arc_pruning_same_cleanroom_top_k')));
  assert.ok(numericPolicyFieldGroups.some(group => group.keys.includes('arc_pruning_due_window_mins')));
  assert.ok(numericPolicyFieldGroups.some(group => group.keys.includes('arc_pruning_due_window_top_k')));
  assert.ok(listPolicyFields.some(field => field.key === 'planning_force_must_order_classes'));
  assert.ok(listPolicyFields.some(field => field.key === 'screening_allowed_order_statuses'));
});

test('policyFieldRuleClass classifies strategy fields for governance', () => {
  assert.equal(policyFieldRuleClass('machine_capability_constraint_enabled'), 'hard');
  assert.equal(policyFieldRuleClass('continuous_run_enforcement_mode'), 'hard');
  assert.equal(policyFieldRuleClass('candidate_reject_penalty'), 'soft');
  assert.equal(policyFieldRuleClass('planning_force_must_order_classes'), 'soft');
  assert.equal(policyFieldRuleClass('due_date_optimization_enabled'), 'soft');
  assert.equal(policyFieldRuleClass('solver_time_limit_seconds'), 'performance');
  assert.equal(policyFieldRuleClass('arc_pruning_top_k_per_order'), 'performance');
  assert.equal(policyFieldRuleClass('arc_pruning_same_material_family_top_k'), 'performance');
  assert.equal(policyFieldRuleClass('auto_release_enabled'), 'experimental');
  assert.equal(policyFieldRuleClass('unknown_policy'), 'soft');
});

test('policyAuditRuleClassSummary summarizes changed strategy classes', () => {
  assert.equal(
    policyAuditRuleClassSummary('machine_capability_constraint_enabled,solver_time_limit_seconds,auto_release_enabled'),
    '硬规则、性能、实验',
  );
  assert.equal(policyAuditRuleClassSummary('candidate_reject_penalty,due_date_optimization_enabled'), '软策略');
  assert.equal(policyAuditRuleClassSummary(''), '软策略');
});

test('canTogglePolicyField prevents non-admin hard rule disablement', () => {
  assert.equal(canTogglePolicyField({ role: 'planner' }, 'machine_capability_constraint_enabled', true), false);
  assert.equal(canTogglePolicyField({ role: 'planner' }, 'machine_capability_constraint_enabled', false), true);
  assert.equal(canTogglePolicyField({ role: 'planner' }, 'due_date_optimization_enabled', true), true);
  assert.equal(canTogglePolicyField({ role: 'admin' }, 'machine_capability_constraint_enabled', true), true);
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
    '求解时间上限、允许入池订单状态 · 性能、硬规则 · 版本 #7 · planner-a · time:2026-05-24T10:30:00Z',
  );
});
