import assert from 'node:assert/strict';
import test from 'node:test';

import { dashboardOrderBucketCards } from './dashboardViewModel.js';

test('dashboardOrderBucketCards exposes deferred and unplaced solver buckets', () => {
  const cards = dashboardOrderBucketCards({
    total_orders: 6,
    input_order_count: 10,
    scheduled_order_count: 6,
    blocked_order_count: 1,
    deferred_order_count: 2,
    unplaced_solver_failed_order_count: 1,
  });

  assert.deepEqual(
    cards.map(card => ({ key: card.key, label: card.label, value: card.value })),
    [
      { key: 'input', label: '输入订单', value: 10 },
      { key: 'scheduled', label: '已排订单', value: 6 },
      { key: 'blocked', label: '无法排程', value: 1 },
      { key: 'deferred', label: '策略延后', value: 2 },
      { key: 'unplaced', label: '求解未落位', value: 1 },
    ],
  );
  assert.equal(cards.find(card => card.key === 'deferred').tone, 'warning');
  assert.equal(cards.find(card => card.key === 'unplaced').tone, 'danger');
});

test('dashboardOrderBucketCards falls back to scheduled count for legacy summaries', () => {
  const cards = dashboardOrderBucketCards({ total_orders: 4 });

  assert.deepEqual(
    cards.map(card => card.value),
    [4, 4, 0, 0, 0],
  );
});
