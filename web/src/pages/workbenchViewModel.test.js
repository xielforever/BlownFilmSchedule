import assert from 'node:assert/strict';
import test from 'node:test';

import {
  validationDisplayMeta,
  validationDisplayCounts,
  matchesScreeningFilter,
  screeningOverrideAction,
  screeningOverrideBadge,
  screeningOverrideDraftRisk,
  canCreateScreeningOverride,
  deferredReasonFilterOptions,
  deriveReviewTabs,
  solverQualitySummary,
  deriveWorkflowStep,
  screeningPoolCounts,
  selectableOrderIds,
  staleOrderIds,
} from './workbenchViewModel.js';

test('validationDisplayMeta maps publishable contract levels for UI display', () => {
  assert.deepEqual(
    validationDisplayMeta({ level: 'publish_blocker', severity: 'error' }),
    { level: 'publish_blocker', label: '阻断', tone: 'danger', severityClass: 'error' },
  );
  assert.deepEqual(
    validationDisplayMeta({ level: 'invalid', severity: 'error' }),
    { level: 'invalid', label: '无效', tone: 'danger', severityClass: 'error' },
  );
  assert.deepEqual(
    validationDisplayMeta({ level: 'warning', severity: 'warning' }),
    { level: 'warning', label: '警告', tone: 'warning', severityClass: 'warning' },
  );
  assert.deepEqual(
    validationDisplayMeta({ level: 'info', severity: 'info' }),
    { level: 'info', label: '提示', tone: 'neutral', severityClass: 'info' },
  );
  assert.equal(validationDisplayMeta({ severity: 'error' }).level, 'publish_blocker');
});

test('validationDisplayCounts separates blockers warnings and info without double counting', () => {
  assert.deepEqual(
    validationDisplayCounts({
      publish_blocker_count: 1,
      warning_count: 2,
      info_count: 3,
      hard_error_count: 9,
    }),
    { blockers: 1, warnings: 2, info: 3 },
  );
  assert.deepEqual(
    validationDisplayCounts({
      hard_error_count: 1,
      warning_count: 2,
    }),
    { blockers: 1, warnings: 2, info: 0 },
  );
});

test('selectableOrderIds excludes blocked screening orders', () => {
  const orders = [
    { order_id: 'ORD-READY' },
    { order_id: 'ORD-RISK' },
    { order_id: 'ORD-BLOCKED' },
    { order_id: 'ORD-STALE' },
  ];
  const screeningByOrderId = new Map([
    ['ORD-READY', { screening_status: 'ready' }],
    ['ORD-RISK', { screening_status: 'risk' }],
    ['ORD-BLOCKED', { screening_status: 'blocked' }],
    ['ORD-STALE', { screening_status: 'ready', is_stale: true }],
  ]);

  assert.deepEqual(
    selectableOrderIds(orders, screeningByOrderId),
    ['ORD-READY', 'ORD-RISK'],
  );
});

test('matchesScreeningFilter treats schedulable as ready or risk only', () => {
  assert.equal(matchesScreeningFilter('ready', 'schedulable'), true);
  assert.equal(matchesScreeningFilter('risk', 'schedulable'), true);
  assert.equal(matchesScreeningFilter('blocked', 'schedulable'), false);
  assert.equal(matchesScreeningFilter('blocked', 'blocked'), true);
  assert.equal(matchesScreeningFilter('ready', ''), true);
});

test('matchesScreeningFilter separates stale screening results from schedulable pool', () => {
  assert.equal(matchesScreeningFilter({ screening_status: 'ready', is_stale: true }, 'schedulable'), false);
  assert.equal(matchesScreeningFilter({ screening_status: 'risk', is_stale: false }, 'schedulable'), true);
  assert.equal(matchesScreeningFilter({ screening_status: 'blocked', is_stale: true }, 'stale'), true);
  assert.equal(matchesScreeningFilter({ screening_status: 'ready', is_stale: false }, 'stale'), false);
});

test('staleOrderIds returns only stale visible orders', () => {
  const orders = [
    { order_id: 'ORD-STALE-A' },
    { order_id: 'ORD-FRESH' },
    { order_id: 'ORD-STALE-B' },
  ];
  const screeningByOrderId = new Map([
    ['ORD-STALE-A', { screening_status: 'ready', is_stale: true }],
    ['ORD-FRESH', { screening_status: 'ready', is_stale: false }],
    ['ORD-STALE-B', { screening_status: 'blocked', is_stale: true }],
  ]);

  assert.deepEqual(staleOrderIds(orders, screeningByOrderId), ['ORD-STALE-A', 'ORD-STALE-B']);
});

test('screeningPoolCounts includes stale count without changing status counts', () => {
  const items = [
    { screening_status: 'ready', is_stale: false },
    { screening_status: 'ready', is_stale: true },
    { screening_status: 'risk', is_stale: false },
    { screening_status: 'blocked', is_stale: true },
  ];

  assert.deepEqual(screeningPoolCounts(items), {
    ready_count: 2,
    risk_count: 1,
    blocked_count: 1,
    stale_count: 2,
  });
});

test('deferredReasonFilterOptions exposes backend reason counts for filtering', () => {
  assert.deepEqual(
    deferredReasonFilterOptions({
      candidate_optional_rejected: 2,
      planning_window_deferred: 3,
      unknown_reason: 1,
    }),
    [
      { key: 'all', label: '全部延后', count: 6 },
      { key: 'planning_window_deferred', label: '计划窗口延后', count: 3 },
      { key: 'candidate_optional_rejected', label: '候选策略延后', count: 2 },
      { key: 'unknown_reason', label: 'unknown_reason', count: 1 },
    ],
  );
  assert.deepEqual(deferredReasonFilterOptions({}), []);
});

test('screeningOverrideBadge explains override boundaries and applied overrides', () => {
  assert.deepEqual(
    screeningOverrideBadge({
      override_decision: { allowed: true, policy: 'restricted', requires_reason: true },
    }),
    { label: '可受限豁免', tone: 'warning', detail: '需要权限和原因' },
  );
  assert.deepEqual(
    screeningOverrideBadge({
      override_decision: { allowed: false, policy: 'prohibited' },
    }),
    { label: '禁止豁免', tone: 'danger', detail: '需先修正订单或主数据' },
  );
  assert.deepEqual(
    screeningOverrideBadge({
      applied_override: { audit_id: 7, reason_text: '物料替代方案已确认' },
      override_decision: { allowed: true, policy: 'restricted' },
    }),
    { label: '已豁免', tone: 'warning', detail: '物料替代方案已确认' },
  );
});

test('screeningOverrideAction only enables restricted unapplied overrides with permission', () => {
  assert.deepEqual(
    screeningOverrideAction({
      order_id: 'ORD-RISK',
      override_decision: { allowed: true, policy: 'restricted', requires_reason: true },
    }, { canOverride: true }),
    {
      orderId: 'ORD-RISK',
      label: '申请豁免',
      disabled: false,
      reasonRequired: true,
      reasonCode: 'SCREENING_OVERRIDE',
    },
  );
  assert.equal(
    screeningOverrideAction({
      order_id: 'ORD-WIDE',
      override_decision: { allowed: false, policy: 'prohibited' },
    }, { canOverride: true }),
    null,
  );
  assert.deepEqual(
    screeningOverrideAction({
      order_id: 'ORD-RISK',
      override_decision: { allowed: true, policy: 'restricted', requires_reason: true },
    }, { canOverride: false }),
    {
      orderId: 'ORD-RISK',
      label: '申请豁免',
      disabled: true,
      reasonRequired: true,
      reasonCode: 'SCREENING_OVERRIDE',
      disabledReason: '当前账号无豁免权限',
    },
  );
  assert.equal(
    screeningOverrideAction({
      order_id: 'ORD-DONE',
      applied_override: { audit_id: 9 },
      override_decision: { allowed: true, policy: 'restricted' },
    }, { canOverride: true }),
    null,
  );
});

test('canCreateScreeningOverride follows operator role permissions', () => {
  assert.equal(canCreateScreeningOverride({ role: 'admin' }), true);
  assert.equal(canCreateScreeningOverride({ role: 'planner' }), true);
  assert.equal(canCreateScreeningOverride({ role: 'viewer' }), false);
  assert.equal(canCreateScreeningOverride(null), false);
});

test('deriveWorkflowStep returns cancelled drafts to the order pool', () => {
  assert.equal(
    deriveWorkflowStep({
      activePlan: { run: { lifecycle_status: 'CANCELLED' } },
      queue: [],
    }),
    'order_pool',
  );
});

test('deriveReviewTabs keeps draft review compact for workers', () => {
  assert.deepEqual(
    deriveReviewTabs({
      counts: { scheduled: 4, input: 9, blocked: 2, late: 1, schedulable: 7, deferred: 2 },
      needsActionCount: 3,
    }).map(tab => ({ key: tab.key, label: tab.label, count: tab.count })),
    [
      { key: 'needs_action', label: '需处理', count: 3 },
      { key: 'deferred', label: '延后', count: 2 },
      { key: 'scheduled', label: '已排', count: 4 },
      { key: 'input', label: '全部输入', count: 9 },
    ],
  );
});

test('solverQualitySummary explains solver proof and candidate deferrals for workers', () => {
  assert.deepEqual(
    solverQualitySummary({
      run: {
        status: 'FEASIBLE',
        summary: {
          deferred_order_count: 2,
          deferred_reason_counts: { candidate_optional_rejected: 2 },
        },
        solver_metrics: {
          phase_1: { status: 'FEASIBLE', gap: 0.125, wall_time: 1.4 },
          phase_2: { status: 'UNKNOWN', gap: null, wall_time: 0.8 },
          model_size: { order_count: 12, arc_count: 40, pruned_arc_count: 5 },
        },
      },
    }),
    {
      tone: 'warning',
      label: '可行但未证明最优',
      detail: 'Phase 1 FEASIBLE · gap 12.5% · Phase 2 UNKNOWN · 候选延后 2 单',
      metrics: [
        { key: 'orders', label: '输入', value: 12 },
        { key: 'arcs', label: '弧', value: 40 },
        { key: 'pruned_arcs', label: '裁剪', value: 5 },
        { key: 'wall_time', label: '耗时', value: '2.2s' },
      ],
    },
  );
});

test('screeningOverrideDraftRisk labels applied overrides for draft review', () => {
  assert.equal(
    screeningOverrideDraftRisk({
      applied_override: {
        override_policy: 'restricted',
        reason_text: '物料替代方案已确认',
      },
    }),
    '筛选豁免排入：物料替代方案已确认',
  );
  assert.equal(screeningOverrideDraftRisk({}), '');
});
