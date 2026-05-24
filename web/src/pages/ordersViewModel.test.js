import assert from 'node:assert/strict';
import test from 'node:test';

import { screeningDetailLines } from './ordersViewModel.js';

test('screeningDetailLines exposes exception root cause and recommendation', () => {
  const lines = screeningDetailLines({
    screening_status: 'blocked',
    root_cause: '目标幅宽 9999 超出全部 active 机台能力',
    recommendations: [
      { guidance: '核对订单规格或补充机台能力主数据' },
    ],
  });

  assert.deepEqual(lines, [
    '目标幅宽 9999 超出全部 active 机台能力',
    '核对订单规格或补充机台能力主数据',
  ]);
});

test('screeningDetailLines keeps ready orders compact', () => {
  assert.deepEqual(screeningDetailLines({ screening_status: 'ready', root_cause: '可生产' }), []);
});
