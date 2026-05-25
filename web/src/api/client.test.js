import assert from 'node:assert/strict';
import test from 'node:test';

import api, {
  createOrderScreeningAction,
  createOrderScreeningOverride,
  getOrderScreeningActions,
  getOrderScreeningOverrides,
} from './client.js';

test('screening override api helpers target order-specific audit endpoints', async () => {
  const originalPost = api.post;
  const originalGet = api.get;
  const calls = [];
  api.post = (url, payload) => {
    calls.push({ method: 'post', url, payload });
    return Promise.resolve({ data: { ok: true } });
  };
  api.get = (url) => {
    calls.push({ method: 'get', url });
    return Promise.resolve({ data: { items: [] } });
  };

  try {
    await createOrderScreeningOverride('ORD-OVERRIDE', {
      reason_text: '物料替代方案已确认',
      reason_code: 'SCREENING_OVERRIDE',
    });
    await getOrderScreeningOverrides('ORD-OVERRIDE');
  } finally {
    api.post = originalPost;
    api.get = originalGet;
  }

  assert.deepEqual(calls, [
    {
      method: 'post',
      url: '/orders/ORD-OVERRIDE/screening-override',
      payload: {
        reason_text: '物料替代方案已确认',
        reason_code: 'SCREENING_OVERRIDE',
      },
    },
    {
      method: 'get',
      url: '/orders/ORD-OVERRIDE/screening-overrides',
    },
  ]);
});

test('screening action api helpers target order-specific handling endpoints', async () => {
  const originalPost = api.post;
  const originalGet = api.get;
  const calls = [];
  api.post = (url, payload) => {
    calls.push({ method: 'post', url, payload });
    return Promise.resolve({ data: { ok: true } });
  };
  api.get = (url) => {
    calls.push({ method: 'get', url });
    return Promise.resolve({ data: { items: [] } });
  };

  try {
    await createOrderScreeningAction('ORD-ACTION', {
      action_type: 'update_master_data',
      handling_status: 'in_progress',
      reason_text: '机台能力信息已退回维护',
      assignee: '工艺主管',
    });
    await getOrderScreeningActions('ORD-ACTION');
  } finally {
    api.post = originalPost;
    api.get = originalGet;
  }

  assert.deepEqual(calls, [
    {
      method: 'post',
      url: '/orders/ORD-ACTION/screening-action',
      payload: {
        action_type: 'update_master_data',
        handling_status: 'in_progress',
        reason_text: '机台能力信息已退回维护',
        assignee: '工艺主管',
      },
    },
    {
      method: 'get',
      url: '/orders/ORD-ACTION/screening-actions',
    },
  ]);
});
