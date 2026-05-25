export const draftVersionLabels = {
  current: '当前策略，订单快照有效',
  policy_stale: '策略已变化，需要重新预排',
  order_stale: '订单已修订，需要重新预排',
  mixed_stale: '策略和订单均已变化',
  cancelled: '草案已废弃',
  confirmed: '已发布为制造队列',
};

export const draftVersionTones = {
  current: 'success',
  policy_stale: 'danger',
  order_stale: 'danger',
  mixed_stale: 'danger',
  cancelled: 'danger',
  confirmed: 'success',
};

export const workbenchStages = [
  { key: 'order_pool', label: '订单池', description: '选择 PENDING 订单' },
  { key: 'draft_review', label: '草案复核', description: '处理阻断、延期和调整' },
  { key: 'validate_publish', label: '校验发布', description: '校验后进入制造队列' },
  { key: 'manufacturing_queue', label: '制造队列', description: '推进开工和完工' },
];

export const workbenchStageLabels = Object.fromEntries(
  workbenchStages.map(stage => [stage.key, stage.label]),
);

export function validationDisplayMeta(item) {
  const rawLevel = item?.level || (item?.severity === 'error' ? 'publish_blocker' : item?.severity);
  const level = ['invalid', 'publish_blocker', 'warning', 'info'].includes(rawLevel)
    ? rawLevel
    : 'warning';
  const meta = {
    invalid: { label: '无效', tone: 'danger', severityClass: 'error' },
    publish_blocker: { label: '阻断', tone: 'danger', severityClass: 'error' },
    warning: { label: '警告', tone: 'warning', severityClass: 'warning' },
    info: { label: '提示', tone: 'neutral', severityClass: 'info' },
  }[level];
  return { level, ...meta };
}

export function validationDisplayCounts(validation) {
  const blockers = Number(validation?.publish_blocker_count ?? validation?.hard_error_count ?? 0);
  const warnings = Number(validation?.warning_count || 0);
  const info = Number(validation?.info_count || 0);
  return { blockers, warnings, info };
}

export function deriveDraftVersionState(activePlan) {
  const lifecycle = activePlan?.run?.lifecycle_status;
  if (!activePlan) return 'none';
  if (lifecycle === 'CANCELLED') return 'cancelled';
  if (lifecycle === 'CONFIRMED') return 'confirmed';

  const items = activePlan?.validation?.items || [];
  const hasPolicyStale = items.some(item => item.code === 'policy_snapshot_stale');
  const hasOrderStale = items.some(item => item.code === 'order_snapshot_stale');
  if (hasPolicyStale && hasOrderStale) return 'mixed_stale';
  if (hasPolicyStale) return 'policy_stale';
  if (hasOrderStale) return 'order_stale';
  return 'current';
}

export function isDraftStale(versionState) {
  return ['policy_stale', 'order_stale', 'mixed_stale'].includes(versionState);
}

export function deriveWorkflowStep({ activePlan, queue = [], draftVersionState = 'none', hasHardErrors = false }) {
  if (!activePlan) return 'order_pool';
  const lifecycle = activePlan.run?.lifecycle_status;
  if (lifecycle === 'CANCELLED') return 'order_pool';
  if (lifecycle === 'CONFIRMED' || queue.some(item => item.run_id === activePlan.run?.run_id)) return 'manufacturing_queue';
  if (lifecycle === 'VALIDATED' && !isDraftStale(draftVersionState) && !hasHardErrors) return 'validate_publish';
  return 'draft_review';
}

export function deriveWorkbenchStageStates({
  activePlan,
  activeStage = 'order_pool',
  recommendedStage = 'order_pool',
  queueCount = 0,
  validation = null,
  canConfirm = false,
  canEditDraft = false,
  reviewValidationPending = false,
  draftVersionState = 'none',
  hasHardErrors = false,
} = {}) {
  const lifecycle = activePlan?.run?.lifecycle_status;
  const hasActiveDraft = Boolean(activePlan && lifecycle !== 'CANCELLED');
  const draftReviewUnlocked = hasActiveDraft;
  const validateUnlocked = hasActiveDraft && (
    canEditDraft
    || Boolean(validation)
    || lifecycle === 'VALIDATED'
    || canConfirm
  );
  const queueUnlocked = lifecycle === 'CONFIRMED' || queueCount > 0;
  const validationComplete = Boolean(validation) || lifecycle === 'VALIDATED' || canConfirm;
  const stale = isDraftStale(draftVersionState);

  const stageMeta = {
    order_pool: {
      unlocked: true,
      done: Boolean(activePlan),
      lockReason: '',
    },
    draft_review: {
      unlocked: draftReviewUnlocked,
      done: validationComplete && !reviewValidationPending && !hasHardErrors && !stale,
      lockReason: '请先从订单池创建预排程草案。',
    },
    validate_publish: {
      unlocked: validateUnlocked,
      done: queueUnlocked,
      lockReason: hasActiveDraft ? '请先完成草案复核后再校验发布。' : '请先创建草案并完成复核。',
    },
    manufacturing_queue: {
      unlocked: queueUnlocked,
      done: false,
      lockReason: '草案尚未发布，不能进入制造队列。',
    },
  };

  return Object.fromEntries(workbenchStages.map(stage => {
    const meta = stageMeta[stage.key] || {};
    const locked = !meta.unlocked;
    let status = locked ? 'locked' : 'available';
    if (!locked && meta.done) status = 'done';
    if (activeStage === stage.key) status = 'current';
    return [
      stage.key,
      {
        status,
        locked,
        recommended: recommendedStage === stage.key,
        lockReason: locked ? meta.lockReason : '',
      },
    ];
  }));
}

export function derivePrimaryAction({
  activePlan,
  selectedCount = 0,
  canConfirm = false,
  canEditDraft = false,
  hasHardErrors = false,
  publishBlockReason = '',
  reviewValidationPending = false,
  draftVersionState = 'none',
}) {
  if (!activePlan) {
    return {
      key: 'create',
      label: selectedCount ? `创建预排程 (${selectedCount})` : '先选择订单',
      disabled: selectedCount === 0,
      target: 'create',
    };
  }

  const lifecycle = activePlan.run?.lifecycle_status;
  if (isDraftStale(draftVersionState)) {
    return { key: 'replan', label: '重新预排', disabled: false, target: 'version' };
  }
  if (lifecycle === 'CONFIRMED') {
    return { key: 'queue', label: '查看制造队列', disabled: false, target: 'queue' };
  }
  if (lifecycle === 'CANCELLED') {
    return { key: 'select_orders', label: '重新选择订单', disabled: false, target: 'orders' };
  }
  if (canConfirm) {
    return { key: 'confirm', label: '确认进入制造队列', disabled: false, target: 'confirm' };
  }
  if (hasHardErrors) {
    return { key: 'blockers', label: '查看阻断', disabled: false, target: 'blockers' };
  }
  if (reviewValidationPending || canEditDraft) {
    return { key: 'validate', label: '校验方案', disabled: !canEditDraft, target: 'validate' };
  }
  return { key: 'blocked', label: publishBlockReason || '当前不可发布', disabled: true, target: 'none' };
}

export function deriveReviewTabs({ counts, needsActionCount = 0 }) {
  const tabs = [
    { key: 'needs_action', label: '需处理', count: needsActionCount, tone: needsActionCount ? 'danger' : 'neutral' },
  ];
  if (Number(counts.deferred || 0) > 0) {
    tabs.push({ key: 'deferred', label: '延后', count: counts.deferred, tone: 'warning' });
  }
  return [
    ...tabs,
    { key: 'scheduled', label: '已排', count: counts.scheduled, tone: 'success' },
    { key: 'input', label: '全部输入', count: counts.input, tone: 'neutral' },
  ];
}

export function lockedTaskSummaryCards(summary) {
  if (!summary || Number(summary.locked_task_count || 0) <= 0) return [];
  const protectedMachines = [...(summary.protected_machine_ids || [])].sort();
  return [
    { key: 'locked', label: '锁定任务', value: Number(summary.locked_task_count || 0), tone: 'warning' },
    { key: 'machine', label: '锁定机台', value: Number(summary.machine_locked_count || 0), tone: 'warning' },
    { key: 'time', label: '锁定时间', value: Number(summary.time_locked_count || 0), tone: 'warning' },
    {
      key: 'machines',
      label: '受保护机台',
      value: protectedMachines.length ? protectedMachines.join(', ') : '-',
      tone: 'neutral',
    },
  ];
}

function formatMinutes(value) {
  return `${Number(value || 0)} 分钟`;
}

export function adjustmentImpactSummaryCards(summary) {
  if (!summary || Number(summary.adjustment_count || 0) <= 0) return [];
  const hasNegativeImpact = Boolean(summary.has_negative_impact);
  return [
    { key: 'adjustments', label: '调整次数', value: Number(summary.adjustment_count || 0), tone: 'warning' },
    { key: 'machine_changes', label: '换机', value: Number(summary.machine_change_count || 0), tone: 'warning' },
    { key: 'time_changes', label: '时间变化', value: Number(summary.time_changed_count || 0), tone: 'warning' },
    { key: 'locked_after', label: '调整后锁定', value: Number(summary.locked_after_adjustment_count || 0), tone: 'warning' },
    { key: 'setup_delta', label: '换产增加', value: formatMinutes(summary.total_setup_time_delta_mins), tone: 'warning' },
    { key: 'tardiness_delta', label: '延期增加', value: formatMinutes(summary.total_tardiness_delta_mins), tone: hasNegativeImpact ? 'danger' : 'warning' },
    { key: 'max_delay', label: '最大完工延后', value: formatMinutes(summary.max_delay_delta_mins), tone: hasNegativeImpact ? 'danger' : 'warning' },
    { key: 'review_required', label: '需复核', value: Number(summary.review_required_count || 0), tone: hasNegativeImpact ? 'danger' : 'warning' },
  ];
}

export function adjustmentReviewReasonRows(summary) {
  if (!summary || typeof summary !== 'object') return [];
  return Object.values(summary)
    .filter(item => item && item.code)
    .sort((a, b) => {
      const countDelta = Number(b.count || 0) - Number(a.count || 0);
      if (countDelta) return countDelta;
      return Number(b.max_excess_mins || 0) - Number(a.max_excess_mins || 0);
    })
    .map(item => ({
      key: item.code,
      title: `${item.label || item.code} · ${Number(item.count || 0)} 次`,
      detail: `影响 ${Number(item.affected_order_count || 0)} 单 · 最大 ${Number(item.max_actual_delta_mins || 0)} 分钟 · 超阈值 ${Number(item.max_excess_mins || 0)} 分钟`,
      orders: (item.order_ids || []).join(', '),
    }));
}

export function adjustmentReasonSummaryRows(summary) {
  if (!summary || typeof summary !== 'object') return [];
  const rows = (summary.reason_items || []).map(item => ({
    key: `reason-${item.reason_code}`,
    title: `${item.reason_code} · ${Number(item.count || 0)} 次`,
    detail: item.sample_reason_text || '未填写原因说明',
    tone: 'neutral',
  }));
  const failedCount = Number(summary.failed_adjustment_count || 0);
  if (failedCount > 0) {
    rows.push({
      key: 'failed-adjustments',
      title: `失败调整 · ${failedCount} 次`,
      detail: '需要复核未生效的人工调整记录',
      tone: 'danger',
    });
  }
  const actorEntries = Object.entries(summary.actor_counts || {})
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0));
  if (actorEntries.length) {
    rows.push({
      key: 'actors',
      title: '执行人',
      detail: actorEntries.map(([actor, count]) => `${actor} ${Number(count || 0)} 次`).join(', '),
      tone: 'neutral',
    });
  }
  return rows;
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatSeconds(value) {
  const number = Number(value || 0);
  return `${number.toFixed(1)}s`;
}

export function solverQualitySummary(activePlan) {
  const run = activePlan?.run || {};
  const metrics = run.solver_metrics || {};
  const phase1 = metrics.phase_1 || {};
  const phase2 = metrics.phase_2 || {};
  const modelSize = metrics.model_size || {};
  const summary = run.summary || {};
  const runStatus = run.status || phase1.status || 'UNKNOWN';
  const phase1Status = phase1.status || runStatus;
  const phase2Status = phase2.status || '-';
  const deferredCount = Number(summary.deferred_order_count || 0);
  const totalWallTime = Number(phase1.wall_time || 0) + Number(phase2.wall_time || 0);
  const provenOptimal = runStatus === 'OPTIMAL' && phase1Status === 'OPTIMAL' && (!phase2.status || phase2.status === 'OPTIMAL');
  const blocked = ['INFEASIBLE', 'INVALID', 'MODEL_INVALID'].includes(runStatus);
  const label = blocked
    ? '求解不可用'
    : provenOptimal
      ? '已证明最优'
      : '可行但未证明最优';
  const tone = blocked ? 'danger' : provenOptimal ? 'success' : 'warning';
  const detailParts = [
    `Phase 1 ${phase1Status}`,
    `gap ${formatPercent(phase1.gap)}`,
    `Phase 2 ${phase2Status}`,
  ];
  if (deferredCount) detailParts.push(`候选延后 ${deferredCount} 单`);

  return {
    tone,
    label,
    detail: detailParts.join(' · '),
    metrics: [
      { key: 'orders', label: '输入', value: Number(modelSize.order_count || summary.input_order_count || 0) },
      { key: 'arcs', label: '弧', value: Number(modelSize.arc_count || 0) },
      { key: 'pruned_arcs', label: '裁剪', value: Number(modelSize.pruned_arc_count || 0) },
      { key: 'wall_time', label: '耗时', value: formatSeconds(totalWallTime) },
    ],
  };
}

export function summarizeQueue(queue = [], activeRunId = null) {
  const rows = activeRunId ? queue.filter(item => item.run_id === activeRunId) : queue;
  const counts = rows.reduce((acc, item) => {
    acc[item.queue_status] = (acc[item.queue_status] || 0) + 1;
    return acc;
  }, {});
  return {
    rows,
    total: rows.length,
    counts,
  };
}

export function derivePublishChecklist({
  activePlan,
  counts,
  validation,
  draftVersionLabel = '尚无草案',
  publishBlockReason = '',
  canConfirm = false,
  queueCount = 0,
}) {
  if (!activePlan) {
    return [
      { key: 'draft', label: '预排程草案', status: 'waiting', detail: '尚未创建草案' },
      { key: 'orders', label: '订单选择', status: 'waiting', detail: '请选择待排订单' },
    ];
  }

  const hardErrors = Number(validation?.hard_error_count || 0);
  const warnings = Number(validation?.warning_count || 0);
  const deferred = Number(counts.deferred || 0);
  const snapshotBlocked = publishBlockReason.includes('快照') || publishBlockReason.includes('变化');
  const checklist = [
    { key: 'draft', label: '草案生命周期', status: 'ready', detail: activePlan.run?.lifecycle_status || '-' },
    { key: 'snapshot', label: '快照状态', status: snapshotBlocked ? 'blocked' : 'ready', detail: draftVersionLabel },
    { key: 'validation', label: '校验状态', status: hardErrors ? 'blocked' : validation ? 'ready' : 'waiting', detail: validation ? `阻断 ${hardErrors} · 警告 ${warnings}` : '尚未校验' },
    { key: 'scheduled', label: '已排订单', status: counts.scheduled > 0 ? 'ready' : 'blocked', detail: `${counts.scheduled} 单` },
    { key: 'blocked', label: '未排订单', status: counts.blocked > 0 ? 'warning' : 'ready', detail: `${counts.blocked} 单` },
  ];
  if (deferred > 0) {
    checklist.push({ key: 'deferred', label: '延后订单', status: 'warning', detail: `${deferred} 单` });
  }
  checklist.push({ key: 'queue', label: '发布后队列', status: canConfirm || queueCount > 0 ? 'ready' : 'waiting', detail: queueCount > 0 ? `${queueCount} 项` : `${counts.scheduled} 单将进入队列` });
  return checklist;
}

export function isSelectableScreeningStatus(screeningStatus) {
  return screeningStatus !== 'blocked';
}

export function isSelectableScreening(screening) {
  if (!screening) return true;
  if (screening.is_stale) return false;
  return isSelectableScreeningStatus(screening.screening_status);
}

export function screeningOverrideBadge(screening) {
  if (!screening) return null;
  if (screening.applied_override) {
    return {
      label: '已豁免',
      tone: 'warning',
      detail: screening.applied_override.reason_text || '已记录豁免审计',
    };
  }
  const decision = screening.override_decision;
  if (!decision) return null;
  if (decision.policy === 'restricted' && decision.allowed) {
    return {
      label: '可受限豁免',
      tone: 'warning',
      detail: decision.requires_reason ? '需要权限和原因' : '需要权限确认',
    };
  }
  if (decision.policy === 'prohibited') {
    return {
      label: '禁止豁免',
      tone: 'danger',
      detail: '需先修正订单或主数据',
    };
  }
  if (decision.policy === 'not_required') {
    return {
      label: '无需豁免',
      tone: 'success',
      detail: '订单可直接进入排程池',
    };
  }
  return null;
}

export function screeningOverrideDraftRisk(row) {
  const override = row?.applied_override;
  if (!override) return '';
  return `筛选豁免排入：${override.reason_text || override.reason_code || '已记录豁免审计'}`;
}

export function screeningOverrideAction(screening, { canOverride = false } = {}) {
  if (!screening || screening.applied_override) return null;
  const decision = screening.override_decision;
  if (!decision?.allowed || decision.policy !== 'restricted') return null;
  const action = {
    orderId: screening.order_id,
    label: '申请豁免',
    disabled: !canOverride,
    reasonRequired: Boolean(decision.requires_reason),
    reasonCode: 'SCREENING_OVERRIDE',
  };
  if (!canOverride) {
    action.disabledReason = '当前账号无豁免权限';
  }
  return action;
}

export function canCreateScreeningOverride(user) {
  return user?.role === 'admin' || user?.role === 'planner';
}

export function matchesScreeningFilter(screeningOrStatus, filter) {
  const screening = typeof screeningOrStatus === 'object' && screeningOrStatus !== null
    ? screeningOrStatus
    : { screening_status: screeningOrStatus, is_stale: false };
  const screeningStatus = screening.screening_status;
  if (!filter) return true;
  if (filter === 'stale') return Boolean(screening.is_stale);
  if (screening.is_stale) return false;
  if (filter === 'schedulable') return screeningStatus === 'ready' || screeningStatus === 'risk';
  return screeningStatus === filter;
}

export function selectableOrderIds(orders = [], screeningByOrderId = new Map()) {
  return orders
    .filter(order => isSelectableScreening(screeningByOrderId.get(order.order_id)))
    .map(order => order.order_id);
}

export function staleOrderIds(orders = [], screeningByOrderId = new Map()) {
  return orders
    .filter(order => Boolean(screeningByOrderId.get(order.order_id)?.is_stale))
    .map(order => order.order_id);
}

export function screeningPoolCounts(items = []) {
  return items.reduce((acc, item) => {
    if (item?.screening_status === 'ready') acc.ready_count += 1;
    if (item?.screening_status === 'risk') acc.risk_count += 1;
    if (item?.screening_status === 'blocked') acc.blocked_count += 1;
    if (item?.is_stale) acc.stale_count += 1;
    return acc;
  }, {
    ready_count: 0,
    risk_count: 0,
    blocked_count: 0,
    stale_count: 0,
  });
}

const deferredReasonLabels = {
  planning_window_deferred: '计划窗口延后',
  candidate_optional_rejected: '候选策略延后',
};

export function deferredReasonFilterOptions(reasonCounts = {}) {
  const entries = Object.entries(reasonCounts || {})
    .map(([key, count]) => ({ key, count: Number(count || 0) }))
    .filter(item => item.key && item.count > 0)
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
  const total = entries.reduce((sum, item) => sum + item.count, 0);
  if (!total) return [];
  return [
    { key: 'all', label: '全部延后', count: total },
    ...entries.map(item => ({
      key: item.key,
      label: deferredReasonLabels[item.key] || item.key,
      count: item.count,
    })),
  ];
}
