export const booleanPolicyGroups = [
  {
    title: '发布与人工复核',
    keys: ['review_required', 'manual_adjust_enabled', 'manual_adjust_reason_required', 'publish_with_warnings_allowed', 'auto_release_enabled'],
  },
  {
    title: '排程约束与优化',
    keys: ['material_constraint_enabled', 'maintenance_constraint_enabled', 'setup_rules_enabled', 'cleanroom_constraint_enabled', 'machine_capability_constraint_enabled', 'due_date_optimization_enabled'],
  },
];

export const numericPolicyFieldGroups = [
  {
    title: '连续运行与求解质量',
    keys: [
      'continuous_run_limit_mins',
      'phase2_feasible_tardiness_tolerance_mins',
      'solver_time_limit_seconds',
      'solver_relative_gap_limit',
      'solver_random_seed',
      'solver_num_workers',
    ],
  },
  {
    title: '计划窗口与候选接受',
    keys: [
      'planning_must_schedule_horizon_days',
      'planning_candidate_horizon_days',
      'candidate_reject_penalty',
      'candidate_max_deferred_count',
      'candidate_min_acceptance_ratio',
    ],
  },
  {
    title: '弧裁剪与订单准入',
    keys: [
      'arc_pruning_max_setup_mins',
      'arc_pruning_top_k_per_order',
      'screening_due_risk_min_slack_mins',
      'screening_due_risk_duration_multiplier',
    ],
  },
  {
    title: '人工调整复核阈值',
    keys: [
      'manual_adjust_review_delay_threshold_mins',
      'manual_adjust_review_setup_threshold_mins',
      'manual_adjust_review_tardiness_threshold_mins',
    ],
  },
];

export const listPolicyFields = [
  {
    key: 'screening_allowed_order_statuses',
    placeholder: 'PENDING, RELEASED',
  },
  {
    key: 'screening_prohibited_override_codes',
    placeholder: 'missing_product, no_eligible_machine',
  },
  {
    key: 'screening_restricted_override_codes',
    placeholder: 'material_not_ready, due_risk',
  },
  {
    key: 'screening_required_positive_order_fields',
    placeholder: 'due_date_mins, target_width, total_quantity_kg',
  },
];

export function normalizePolicyList(value) {
  if (Array.isArray(value)) return value.map(item => String(item).trim()).filter(Boolean);
  return String(value ?? '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean);
}

export function buildSchedulePolicyPayload(draft = {}, changeReason = '') {
  const payload = { change_reason: changeReason.trim() };

  booleanPolicyGroups
    .flatMap(group => group.keys)
    .forEach(key => {
      payload[key] = draft[key] !== false;
    });

  numericPolicyFieldGroups
    .flatMap(group => group.keys)
    .forEach(key => {
      if (draft[key] === '' || draft[key] === undefined) {
        payload[key] = null;
        return;
      }
      payload[key] = Number(draft[key]);
    });

  listPolicyFields.forEach(({ key }) => {
    payload[key] = normalizePolicyList(draft[key]);
  });

  return payload;
}
