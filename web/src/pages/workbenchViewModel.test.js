import assert from 'node:assert/strict';
import test from 'node:test';

import { matchesScreeningFilter, screeningPoolCounts, selectableOrderIds, staleOrderIds } from './workbenchViewModel.js';

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
