import assert from 'node:assert/strict';
import test from 'node:test';

import { selectableOrderIds } from './workbenchViewModel.js';

test('selectableOrderIds excludes blocked screening orders', () => {
  const orders = [
    { order_id: 'ORD-READY' },
    { order_id: 'ORD-RISK' },
    { order_id: 'ORD-BLOCKED' },
  ];
  const screeningByOrderId = new Map([
    ['ORD-READY', { screening_status: 'ready' }],
    ['ORD-RISK', { screening_status: 'risk' }],
    ['ORD-BLOCKED', { screening_status: 'blocked' }],
  ]);

  assert.deepEqual(
    selectableOrderIds(orders, screeningByOrderId),
    ['ORD-READY', 'ORD-RISK'],
  );
});
