function numberOrFallback(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

const deferredReasonLabels = {
  planning_window_deferred: '计划窗口延后',
  candidate_optional_rejected: '候选策略延后',
};

export function dashboardOrderBucketCards(summary = {}) {
  const scheduled = numberOrFallback(summary.scheduled_order_count, numberOrFallback(summary.total_orders, 0));
  const input = numberOrFallback(summary.input_order_count, scheduled);
  const blocked = numberOrFallback(summary.blocked_order_count, Math.max(0, input - scheduled));
  const deferred = numberOrFallback(summary.deferred_order_count, 0);
  const unplaced = numberOrFallback(summary.unplaced_solver_failed_order_count, 0);

  return [
    { key: 'input', label: '输入订单', value: input, tone: 'neutral' },
    { key: 'scheduled', label: '已排订单', value: scheduled, tone: 'success' },
    { key: 'blocked', label: '无法排程', value: blocked, tone: blocked ? 'warning' : 'success' },
    { key: 'deferred', label: '策略延后', value: deferred, tone: deferred ? 'warning' : 'success' },
    { key: 'unplaced', label: '求解未落位', value: unplaced, tone: unplaced ? 'danger' : 'success' },
  ];
}

export function dashboardDeferredReasonCards(reasonCounts = {}) {
  return Object.entries(reasonCounts || {})
    .map(([key, value]) => ({ key, value: numberOrFallback(value, 0) }))
    .filter(item => item.key && item.value > 0)
    .sort((a, b) => b.value - a.value || a.key.localeCompare(b.key))
    .map(item => ({
      key: item.key,
      label: deferredReasonLabels[item.key] || item.key,
      value: item.value,
      tone: 'warning',
    }));
}
