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

export const auditKeyLabels = {
  material_constraint_enabled: '物料约束',
  maintenance_constraint_enabled: '维护窗口',
  setup_rules_enabled: '换产规则',
  cleanroom_constraint_enabled: '洁净约束',
  machine_capability_constraint_enabled: '机台能力',
  due_date_optimization_enabled: '交期优化',
  solver_time_limit_seconds: '求解时间上限',
  solver_relative_gap_limit: '求解 gap',
  planning_must_schedule_horizon_days: '必排窗口',
  planning_candidate_horizon_days: '候选窗口',
  candidate_reject_penalty: '候选拒排惩罚',
  candidate_max_deferred_count: '候选最大延后数',
  candidate_min_acceptance_ratio: '候选最低接受率',
  arc_pruning_enabled: '弧裁剪开关',
  arc_pruning_max_setup_mins: '弧裁剪换产阈值',
  arc_pruning_top_k_per_order: '弧裁剪 top-k',
  screening_allowed_order_statuses: '允许入池订单状态',
  screening_prohibited_override_codes: '禁止豁免原因',
  screening_restricted_override_codes: '受限豁免原因',
  screening_required_positive_order_fields: '必填正数字段',
  manual_adjust_review_delay_threshold_mins: '人工调整延误复核阈值',
  manual_adjust_review_setup_threshold_mins: '人工调整换产复核阈值',
  manual_adjust_review_tardiness_threshold_mins: '人工调整迟交复核阈值',
  material_switch: '材料切换',
  gmp_clearance: 'GMP 清场',
  spec_change: '规格变更',
  maintenance: '维护窗口',
};

export const policyFieldRuleClasses = {
  auto_release_enabled: 'experimental',
  material_constraint_enabled: 'hard',
  maintenance_constraint_enabled: 'hard',
  setup_rules_enabled: 'hard',
  cleanroom_constraint_enabled: 'hard',
  machine_capability_constraint_enabled: 'hard',
  continuous_run_limit_mins: 'hard',
  continuous_run_enforcement_mode: 'hard',
  screening_allowed_order_statuses: 'hard',
  screening_prohibited_override_codes: 'hard',
  screening_required_positive_order_fields: 'hard',
  review_required: 'soft',
  manual_adjust_enabled: 'soft',
  manual_adjust_reason_required: 'soft',
  publish_with_warnings_allowed: 'soft',
  due_date_optimization_enabled: 'soft',
  phase2_feasible_tardiness_tolerance_mins: 'soft',
  planning_must_schedule_horizon_days: 'soft',
  planning_candidate_horizon_days: 'soft',
  candidate_reject_penalty: 'soft',
  candidate_max_deferred_count: 'soft',
  candidate_min_acceptance_ratio: 'soft',
  screening_due_risk_min_slack_mins: 'soft',
  screening_due_risk_duration_multiplier: 'soft',
  screening_restricted_override_codes: 'soft',
  manual_adjust_review_delay_threshold_mins: 'soft',
  manual_adjust_review_setup_threshold_mins: 'soft',
  manual_adjust_review_tardiness_threshold_mins: 'soft',
  solver_profile: 'performance',
  solver_time_limit_seconds: 'performance',
  solver_relative_gap_limit: 'performance',
  solver_random_seed: 'performance',
  solver_num_workers: 'performance',
  solver_log_search_progress: 'performance',
  arc_pruning_enabled: 'performance',
  arc_pruning_max_setup_mins: 'performance',
  arc_pruning_top_k_per_order: 'performance',
};

export function policyFieldRuleClass(key = '') {
  return policyFieldRuleClasses[key] || 'soft';
}

const policyRuleClassLabels = {
  hard: '硬规则',
  soft: '软策略',
  performance: '性能',
  experimental: '实验',
};

export function policyAuditRuleClassSummary(configKey = '') {
  const classes = String(configKey || '')
    .split(',')
    .map(item => policyFieldRuleClass(item.trim()));
  const unique = [...new Set(classes.length ? classes : ['soft'])];
  return unique.map(item => policyRuleClassLabels[item] || item).join('、');
}

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

export function formatAuditKey(key = '') {
  if (!key) return '配置项';
  return key
    .split(',')
    .map(item => auditKeyLabels[item] || item)
    .join('、');
}

export function buildConfigAuditMeta(entry = {}, formatTime = value => value || '-') {
  const version = entry.policy_version ? `版本 #${entry.policy_version}` : '未记录版本';
  return [
    formatAuditKey(entry.config_key),
    policyAuditRuleClassSummary(entry.config_key),
    version,
    entry.changed_by || '系统',
    formatTime(entry.created_at),
  ].join(' · ');
}
