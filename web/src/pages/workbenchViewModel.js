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
  if (lifecycle === 'CONFIRMED' || queue.some(item => item.run_id === activePlan.run?.run_id)) return 'manufacturing_queue';
  if (lifecycle === 'VALIDATED' && !isDraftStale(draftVersionState) && !hasHardErrors) return 'validate_publish';
  return 'draft_review';
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
      label: selectedCount ? `创建预排程 (${selectedCount})` : '选择订单后创建',
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

export function deriveReviewTabs({ counts, hardErrorCount = 0, needsActionCount = 0 }) {
  return [
    { key: 'needs_action', label: '需处理', count: needsActionCount, tone: needsActionCount ? 'danger' : 'neutral' },
    { key: 'blockers', label: '草案阻断', count: hardErrorCount, tone: hardErrorCount ? 'danger' : 'neutral' },
    { key: 'blocked', label: '未排订单', count: counts.blocked, tone: counts.blocked ? 'danger' : 'neutral' },
    { key: 'late', label: '延期订单', count: counts.late, tone: counts.late ? 'warning' : 'neutral' },
    { key: 'schedulable', label: '可排订单', count: counts.schedulable, tone: 'success' },
    { key: 'scheduled', label: '已排订单', count: counts.scheduled, tone: 'success' },
    { key: 'input', label: '输入订单', count: counts.input, tone: 'neutral' },
  ];
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
