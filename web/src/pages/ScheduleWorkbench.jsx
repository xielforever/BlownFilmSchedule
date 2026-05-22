import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  adjustPreplanTask,
  cancelPreplan,
  clearActiveSchedule,
  confirmPreplan,
  createPreplan,
  getManufacturingQueue,
  getMachines,
  getOrders,
  getPreplans,
  getPreplan,
  getScheduleSettings,
  resetOrdersToPending,
  updateScheduleSettings,
  validatePreplan,
} from '../api/client';

const orderClassLabels = {
  URGENT: '加急',
  NORMAL: '普通',
  SAMPLE: '样品',
};

const cleanroomLabels = {
  Class_10K: '万级洁净',
  Class_100K: '十万级洁净',
  NO: '普通环境',
};

const lifecycleLabels = {
  DRAFT: '待复核',
  VALIDATED: '已校验',
  CONFIRMED: '已发布',
  CANCELLED: '已废弃',
  SUPERSEDED: '已替代',
};

const runStatusLabels = {
  OPTIMAL: '最优',
  FEASIBLE: '可行',
  PARTIAL: '部分排程',
  INFEASIBLE: '不可排',
  INVALID: '无效',
};

const validationStatusLabels = {
  PASSED: '可发布',
  WARNING: '有警告',
  FAILED: '不可发布',
};

const sourceLabels = {
  AUTO: '系统预排',
  ADJUSTED: '人工调整',
  MANUAL: '人工派单',
};

const reasonOptions = [
  ['CUSTOMER_REQUEST', '客户临时要求'],
  ['MACHINE_PREFERENCE', '现场机台偏好'],
  ['MATERIAL_REALITY', '物料实际齐套变化'],
  ['MACHINE_STATE_LAG', '设备状态未及时更新'],
  ['QUALITY_JUDGEMENT', '质量/洁净要求人工判断'],
  ['DUE_DATE_NEGOTIATED', '交期协商结果'],
  ['OTHER', '其他'],
];
const ORDER_PAGE_SIZE = 500;

const settingTestIds = {
  review_required: 'workbench-setting-review-required',
  manual_adjust_enabled: 'workbench-setting-manual-adjust',
  manual_adjust_reason_required: 'workbench-setting-adjust-reason-required',
  publish_with_warnings_allowed: 'workbench-setting-publish-warnings',
  auto_release_enabled: 'workbench-setting-auto-release',
};

const planOrderTabTestIds = {
  input: 'workbench-order-tab-input',
  schedulable: 'workbench-order-tab-schedulable',
  scheduled: 'workbench-order-tab-scheduled',
  blocked: 'workbench-order-tab-blocked',
  late: 'workbench-order-tab-late',
  blockers: 'workbench-order-tab-blockers',
};

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-';
}

function toDatetimeLocal(value) {
  if (!value) return '';
  const date = new Date(value);
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatError(err, fallback) {
  const detail = err.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.message) return detail.message;
  return err.message || fallback;
}

function asNumber(value, fallback = 0) {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

async function loadPendingOrders() {
  const first = await getOrders({ status: 'PENDING', page: 1, size: ORDER_PAGE_SIZE });
  const firstItems = first.data.items || [];
  const total = asNumber(first.data.total, firstItems.length);
  const pageCount = Math.ceil(total / ORDER_PAGE_SIZE);
  if (pageCount <= 1) {
    return { items: firstItems, total };
  }

  const rest = await Promise.all(
    Array.from({ length: pageCount - 1 }, (_, index) =>
      getOrders({ status: 'PENDING', page: index + 2, size: ORDER_PAGE_SIZE }),
    ),
  );
  return {
    items: [
      ...firstItems,
      ...rest.flatMap(response => response.data.items || []),
    ],
    total,
  };
}

function planCounts(plan, taskCount = null) {
  const summary = plan?.summary || {};
  const scheduled = asNumber(plan?.total_orders, taskCount ?? 0);
  const selected = Array.isArray(plan?.selected_order_ids) ? plan.selected_order_ids.length : 0;
  const input = asNumber(summary.input_order_count, selected || scheduled);
  const schedulable = asNumber(summary.schedulable_order_count, scheduled);
  const blocked = asNumber(summary.blocked_order_count, Math.max(0, input - scheduled));
  return { input, scheduled, schedulable, blocked };
}

function diagnosticEvidence(diagnostic) {
  const item = diagnostic?.evidence?.find(entry => entry.metric === 'machine_blocker')
    || diagnostic?.evidence?.find(entry => String(entry.metric || '').startsWith('blocker_count:'));
  return item ? String(item.actual ?? '') : '';
}

function formatSpec(source) {
  if (!source) return '-';
  const width = source.target_width ?? '-';
  const thickness = source.target_thickness ?? '-';
  const quantity = source.total_quantity_kg ?? source.net_weight_kg ?? '-';
  return `${width}mm x ${thickness}um · ${quantity}kg`;
}

function orderSortKey(row) {
  return row.due_date || row.start_time || row.order_id || '';
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function testIdPart(value) {
  return String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

function planDetailCounts(detail) {
  const fallback = planCounts(detail?.run, detail?.tasks?.length || 0);
  return {
    input: Array.isArray(detail?.input_orders) ? detail.input_orders.length : fallback.input,
    schedulable: Array.isArray(detail?.schedulable_orders) ? detail.schedulable_orders.length : fallback.schedulable,
    scheduled: Array.isArray(detail?.scheduled_orders) ? detail.scheduled_orders.length : fallback.scheduled,
    blocked: Array.isArray(detail?.blocked_orders) ? detail.blocked_orders.length : fallback.blocked,
    late: Array.isArray(detail?.late_orders) ? detail.late_orders.length : (detail?.run?.late_orders || 0),
    hardErrors: asNumber(detail?.validation?.hard_error_count),
  };
}

function preferredPlanOrderTab(detail) {
  const counts = planDetailCounts(detail);
  if (counts.hardErrors > 0) return 'blockers';
  if (counts.blocked > 0) return 'blocked';
  if (counts.late > 0) return 'late';
  return 'input';
}

function Badge({ children, tone = 'neutral' }) {
  return <span className={`workbench-badge ${tone}`}>{children}</span>;
}

function SettingsSwitch({ label, checked, onChange, disabled = false, saving = false, testId }) {
  return (
    <label className="workbench-setting">
      <span>{label}{saving && <small>保存中...</small>}</span>
      <button
        type="button"
        className={`switch ${checked ? 'on' : ''}`}
        aria-pressed={checked}
        aria-busy={saving}
        disabled={disabled}
        data-testid={testId}
        onClick={() => onChange(!checked)}
      >
        <span />
      </button>
    </label>
  );
}

export default function ScheduleWorkbench() {
  const [orders, setOrders] = useState([]);
  const [pendingOrderTotal, setPendingOrderTotal] = useState(0);
  const [machines, setMachines] = useState([]);
  const [preplans, setPreplans] = useState([]);
  const [activePlan, setActivePlan] = useState(null);
  const [queue, setQueue] = useState([]);
  const [settings, setSettings] = useState(null);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loadingWorkbench, setLoadingWorkbench] = useState(true);
  const [status, setStatus] = useState({ tone: 'ok', message: '' });
  const [adjustment, setAdjustment] = useState(null);
  const [selectedPlanOrderId, setSelectedPlanOrderId] = useState('');
  const [planOrderTab, setPlanOrderTab] = useState('input');
  const [workspaceView, setWorkspaceView] = useState('orders');
  const [cancelConfirming, setCancelConfirming] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [resetConfirming, setResetConfirming] = useState(false);
  const [clearConfirming, setClearConfirming] = useState(false);
  const [orderQuery, setOrderQuery] = useState('');
  const [orderClassFilter, setOrderClassFilter] = useState('');
  const [cleanroomFilter, setCleanroomFilter] = useState('');
  const [savingSettingKey, setSavingSettingKey] = useState('');
  const [orderPoolCollapsed, setOrderPoolCollapsed] = useState(false);
  const [queueExpanded, setQueueExpanded] = useState(false);

  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const filteredOrders = useMemo(() => {
    const query = orderQuery.trim().toLowerCase();
    return orders.filter(order => {
      if (orderClassFilter && order.order_class !== orderClassFilter) return false;
      if (cleanroomFilter && order.cleanroom_req !== cleanroomFilter) return false;
      if (!query) return true;
      return [
        order.order_id,
        order.product_type,
        order.customer_class,
        order.order_class,
        order.cleanroom_req,
        order.target_width,
        order.target_thickness,
      ].some(value => String(value ?? '').toLowerCase().includes(query));
    });
  }, [orders, orderQuery, orderClassFilter, cleanroomFilter]);
  const selectedFilteredCount = useMemo(
    () => filteredOrders.filter(order => selectedSet.has(order.order_id)).length,
    [filteredOrders, selectedSet],
  );
  const planTasks = useMemo(() => activePlan?.tasks || [], [activePlan]);
  const validation = activePlan?.validation;
  const sortedValidationItems = useMemo(() => {
    const severityRank = { error: 0, warning: 1 };
    return [...(validation?.items || [])].sort((a, b) => {
      const severityDelta = (severityRank[a.severity] ?? 9) - (severityRank[b.severity] ?? 9);
      if (severityDelta) return severityDelta;
      return String(a.order_id || '').localeCompare(String(b.order_id || ''));
    });
  }, [validation]);
  const hardValidationItems = useMemo(
    () => sortedValidationItems.filter(item => item.severity === 'error'),
    [sortedValidationItems],
  );
  const activeCounts = useMemo(
    () => planCounts(activePlan?.run, planTasks.length),
    [activePlan, planTasks.length],
  );
  const orderById = useMemo(() => {
    const map = new Map();
    for (const order of orders) map.set(order.order_id, order);
    return map;
  }, [orders]);
  const taskByOrderId = useMemo(() => {
    const map = new Map();
    for (const task of planTasks) map.set(task.order_id, task);
    return map;
  }, [planTasks]);
  const diagnosticsByOrderId = useMemo(() => {
    const map = new Map();
    const source = activePlan?.blocked_orders?.length
      ? activePlan.blocked_orders
      : (activePlan?.diagnostics || []).filter(item => item.entity_type === 'order');
    for (const diagnostic of source) {
      const orderId = diagnostic.entity_id || diagnostic.order_id;
      if (orderId && !map.has(orderId)) map.set(orderId, diagnostic);
    }
    return map;
  }, [activePlan]);
  const validationByOrderId = useMemo(() => {
    const map = new Map();
    for (const item of sortedValidationItems) {
      if (!item.order_id) continue;
      if (!map.has(item.order_id)) map.set(item.order_id, []);
      map.get(item.order_id).push(item);
    }
    return map;
  }, [sortedValidationItems]);
  const inputOrderIds = useMemo(() => {
    const selectedIds = activePlan?.run?.selected_order_ids;
    if (Array.isArray(selectedIds) && selectedIds.length) return selectedIds;
    return [...new Set([
      ...planTasks.map(task => task.order_id),
      ...diagnosticsByOrderId.keys(),
    ])];
  }, [activePlan, diagnosticsByOrderId, planTasks]);
  const lateTasks = useMemo(
    () => planTasks.filter(task => task.is_late || asNumber(task.tardiness_mins) > 0),
    [planTasks],
  );
  const bucketRows = useMemo(() => {
    const allRows = [
      ...asArray(activePlan?.input_orders),
      ...asArray(activePlan?.schedulable_orders),
      ...asArray(activePlan?.scheduled_orders),
      ...asArray(activePlan?.unplaced_schedulable_orders),
      ...asArray(activePlan?.blocked_orders),
      ...asArray(activePlan?.late_orders),
    ];
    const map = new Map();
    for (const row of allRows) {
      if (row?.order_id && !map.has(row.order_id)) map.set(row.order_id, row);
    }
    return map;
  }, [activePlan]);
  const blockedDiagnostics = useMemo(() => {
    const source = activePlan?.blocked_orders?.length
      ? activePlan.blocked_orders
      : (activePlan?.diagnostics || []).filter(item => item.entity_type === 'order' && item.category === 'eligibility');
    return source.slice(0, 8);
  }, [activePlan]);
  const tasksByMachine = useMemo(() => {
    const groups = {};
    for (const task of planTasks) {
      groups[task.machine_id] ||= [];
      groups[task.machine_id].push(task);
    }
    return groups;
  }, [planTasks]);
  const machineIds = useMemo(() => {
    const ids = new Set(machines.map(machine => machine.machine_id));
    for (const task of planTasks) ids.add(task.machine_id);
    return [...ids].sort();
  }, [machines, planTasks]);
  const canEditDraft = activePlan && ['DRAFT', 'VALIDATED'].includes(activePlan.run.lifecycle_status);
  const hasHardErrors = asNumber(validation?.hard_error_count) > 0;
  const warningPublishBlocked = asNumber(validation?.warning_count) > 0 && settings && !settings.publish_with_warnings_allowed;
  const canConfirm = canEditDraft && planTasks.length > 0 && !hasHardErrors && !warningPublishBlocked;
  const canCancel = canEditDraft;
  const canAdjust = canEditDraft && Boolean(settings?.manual_adjust_enabled);
  const workbenchBusy = busy || loadingWorkbench;
  const isCancelledPlan = activePlan?.run?.lifecycle_status === 'CANCELLED';
  const cancellationReason = activePlan?.run?.cancel_reason?.trim() || '未填写废弃原因';
  const selectedTask = selectedPlanOrderId ? taskByOrderId.get(selectedPlanOrderId) : null;
  const selectedOrder = selectedPlanOrderId ? (bucketRows.get(selectedPlanOrderId) || orderById.get(selectedPlanOrderId) || selectedTask) : null;
  const selectedDiagnostic = selectedPlanOrderId ? diagnosticsByOrderId.get(selectedPlanOrderId) : null;
  const selectedOrderValidation = selectedPlanOrderId ? (validationByOrderId.get(selectedPlanOrderId) || []) : [];
  const selectedOrderHasError = selectedOrderValidation.some(item => item.severity === 'error');
  const selectedOrderIsUnplaced = selectedOrder?.bucket === 'unplaced_schedulable';
  const selectedOrderStatusTone = selectedOrderHasError
    ? 'danger'
    : selectedOrderValidation.length
      ? 'warning'
      : selectedOrderIsUnplaced
        ? 'warning'
        : selectedTask
          ? 'success'
          : 'danger';
  const selectedOrderStatusLabel = selectedOrderHasError
    ? '存在阻断'
    : selectedOrderValidation.length
      ? '有警告'
      : selectedOrderIsUnplaced
        ? '可排未落位'
        : selectedTask
          ? '已排正常'
          : '未排';
  const selectedOrderGuidance = selectedDiagnostic?.root_cause
    || selectedDiagnostic?.bucket_reason
    || selectedOrder?.root_cause
    || selectedOrder?.bucket_reason;
  const planOrderRows = useMemo(() => {
    const buildRow = (sourceOrOrderId, override = {}) => {
      const sourceRow = typeof sourceOrOrderId === 'string' ? null : sourceOrOrderId;
      const orderId = typeof sourceOrOrderId === 'string' ? sourceOrOrderId : sourceOrOrderId?.order_id;
      const task = taskByOrderId.get(orderId);
      const order = sourceRow || bucketRows.get(orderId) || orderById.get(orderId);
      const diagnostic = diagnosticsByOrderId.get(orderId);
      const relatedValidation = override.validationItem ? [override.validationItem] : (validationByOrderId.get(orderId) || []);
      const errorItem = relatedValidation.find(item => item.severity === 'error');
      const warningItem = relatedValidation.find(item => item.severity === 'warning');
      const source = order || task || {};
      const rowBucket = override.bucket || source.bucket;
      const isLate = Boolean(source.is_late || task?.is_late || asNumber(source.tardiness_mins ?? task?.tardiness_mins) > 0);
      const hasTask = Boolean(task || source.scheduled_task_id || source.start_time);
      let statusLabel;
      let statusTone;
      if (errorItem) {
        statusLabel = '阻断';
        statusTone = 'danger';
      } else if (rowBucket === 'blocked') {
        statusLabel = '未排';
        statusTone = 'danger';
      } else if (rowBucket === 'unplaced_schedulable') {
        statusLabel = '可排未落位';
        statusTone = 'warning';
      } else if (isLate) {
        statusLabel = '延期';
        statusTone = 'warning';
      } else if (hasTask) {
        statusLabel = '已排';
        statusTone = 'success';
      } else {
        statusLabel = '未排';
        statusTone = 'danger';
      }
      return {
        key: override.key || orderId,
        order_id: orderId,
        product_type: source.product_type || '-',
        spec: formatSpec(source),
        order_class: source.order_class,
        cleanroom_req: source.cleanroom_req,
        due_date: source.due_date,
        machine_id: source.machine_id || task?.machine_id || '-',
        start_time: source.start_time || task?.start_time,
        end_time: source.end_time || task?.end_time,
        statusLabel,
        statusTone,
        risk: errorItem?.message
          || source.root_cause
          || source.bucket_reason
          || diagnostic?.root_cause
          || diagnostic?.bucket_reason
          || warningItem?.message
          || (hasTask ? '已落位' : '缺少排程明细'),
      };
    };
    const hasBackendBuckets = [
      activePlan?.input_orders,
      activePlan?.schedulable_orders,
      activePlan?.scheduled_orders,
      activePlan?.unplaced_schedulable_orders,
      activePlan?.blocked_orders,
      activePlan?.late_orders,
    ].some(Array.isArray);
    const scheduled = (hasBackendBuckets ? asArray(activePlan?.scheduled_orders) : planTasks)
      .map(row => buildRow(row?.order_id ? row : row, { bucket: 'scheduled' }))
      .sort((a, b) => orderSortKey(a).localeCompare(orderSortKey(b)));
    const blocked = (hasBackendBuckets ? asArray(activePlan?.blocked_orders) : [...diagnosticsByOrderId.keys()])
      .map(row => buildRow(row?.order_id ? row : row, { bucket: 'blocked' }))
      .sort((a, b) => orderSortKey(a).localeCompare(orderSortKey(b)));
    const schedulable = (hasBackendBuckets ? asArray(activePlan?.schedulable_orders) : scheduled)
      .map(row => buildRow(row?.order_id ? row : row, { bucket: row?.bucket || 'scheduled' }))
      .sort((a, b) => orderSortKey(a).localeCompare(orderSortKey(b)));
    const late = (hasBackendBuckets ? asArray(activePlan?.late_orders) : lateTasks)
      .map(row => buildRow(row?.order_id ? row : row, { bucket: 'late' }))
      .sort((a, b) => orderSortKey(a).localeCompare(orderSortKey(b)));
    return {
      input: (hasBackendBuckets ? asArray(activePlan?.input_orders) : inputOrderIds)
        .map(row => buildRow(row?.order_id ? row : row)),
      schedulable,
      scheduled,
      blocked,
      late,
      blockers: hardValidationItems.map((item, index) => buildRow(item.order_id, {
        validationItem: item,
        key: `${item.code}-${item.order_id}-${index}`,
      })),
    };
  }, [activePlan, bucketRows, diagnosticsByOrderId, hardValidationItems, inputOrderIds, lateTasks, orderById, planTasks, taskByOrderId, validationByOrderId]);
  const planOrderCounts = useMemo(() => ({
    input: Array.isArray(activePlan?.input_orders) ? activePlan.input_orders.length : activeCounts.input,
    schedulable: Array.isArray(activePlan?.schedulable_orders) ? activePlan.schedulable_orders.length : activeCounts.schedulable,
    scheduled: Array.isArray(activePlan?.scheduled_orders) ? activePlan.scheduled_orders.length : activeCounts.scheduled,
    blocked: Array.isArray(activePlan?.blocked_orders) ? activePlan.blocked_orders.length : activeCounts.blocked,
    late: Array.isArray(activePlan?.late_orders) ? activePlan.late_orders.length : (activePlan?.run?.late_orders || lateTasks.length),
  }), [activeCounts, activePlan, lateTasks.length]);
  const planOrderTabs = useMemo(() => ([
    { key: 'blockers', label: '草案阻断', count: hardValidationItems.length, tone: 'danger' },
    { key: 'blocked', label: '未排订单', count: planOrderCounts.blocked, tone: 'danger' },
    { key: 'late', label: '延期订单', count: planOrderCounts.late, tone: 'warning' },
    { key: 'input', label: '输入订单', count: planOrderCounts.input, tone: 'neutral' },
    { key: 'schedulable', label: '可排订单', count: planOrderCounts.schedulable, tone: 'success' },
    { key: 'scheduled', label: '已排订单', count: planOrderCounts.scheduled, tone: 'success' },
  ]), [hardValidationItems.length, planOrderCounts]);
  const visiblePlanOrderRows = useMemo(
    () => planOrderRows[planOrderTab] || [],
    [planOrderRows, planOrderTab],
  );
  const activePlanOrderTab = planOrderTabs.find(tab => tab.key === planOrderTab) || planOrderTabs[0];
  const selectedOrderInCurrentTab = Boolean(
    selectedPlanOrderId && visiblePlanOrderRows.some(row => row.order_id === selectedPlanOrderId),
  );
  const publishBlockReason = useMemo(() => {
    if (!activePlan || canConfirm) return '';
    if (!canEditDraft) return '当前草案不是待复核或已校验状态，不能发布。';
    if (!planTasks.length) return '草案没有已排任务，无法进入制造队列。';
    if (hasHardErrors) return `存在 ${asNumber(validation?.hard_error_count, hardValidationItems.length)} 个草案阻断，需处理后发布。`;
    if (warningPublishBlocked) return `存在 ${asNumber(validation?.warning_count)} 个警告，当前系统不允许带警告发布。`;
    return '';
  }, [activePlan, canConfirm, canEditDraft, hardValidationItems.length, hasHardErrors, planTasks.length, validation, warningPublishBlocked]);
  const visiblePreplans = useMemo(() => {
    const rank = (plan) => {
      if (activePlan?.run.run_id === plan.run_id) return 0;
      if (['DRAFT', 'VALIDATED'].includes(plan.lifecycle_status)) return 1;
      if (plan.lifecycle_status === 'CONFIRMED') return 2;
      return 3;
    };
    return [...preplans].sort((a, b) => {
      const rankDelta = rank(a) - rank(b);
      if (rankDelta) return rankDelta;
      return b.run_id - a.run_id;
    }).slice(0, 8);
  }, [activePlan, preplans]);
  const queueRunIds = useMemo(
    () => [...new Set(queue.map(item => item.run_id).filter(Boolean))],
    [queue],
  );

  useEffect(() => {
    if (!activePlan || selectedPlanOrderId || workspaceView !== 'orders') return;
    const firstRow = visiblePlanOrderRows[0];
    if (firstRow?.order_id) setSelectedPlanOrderId(firstRow.order_id);
  }, [activePlan, selectedPlanOrderId, visiblePlanOrderRows, workspaceView]);

  useEffect(() => {
    if (!activePlan) setOrderPoolCollapsed(false);
  }, [activePlan]);

  const loadAll = useCallback(async (openDraft = false) => {
    const [ordersRes, machinesRes, settingsRes, preplansRes, queueRes] = await Promise.all([
      loadPendingOrders(),
      getMachines(),
      getScheduleSettings(),
      getPreplans(),
      getManufacturingQueue(),
    ]);
    const nextOrders = ordersRes.items || [];
    const availableOrderIds = new Set(nextOrders.map(order => order.order_id));
    setOrders(nextOrders);
    setPendingOrderTotal(ordersRes.total || nextOrders.length);
    setSelected(prev => prev.filter(orderId => availableOrderIds.has(orderId)));
    setMachines(machinesRes.data || []);
    setSettings(settingsRes.data);
    setPreplans(preplansRes.data || []);
    setQueue(queueRes.data || []);
    const draft = (preplansRes.data || []).find(plan => ['DRAFT', 'VALIDATED'].includes(plan.lifecycle_status));
    if (openDraft && draft) {
      const detail = await getPreplan(draft.run_id);
      setActivePlan(detail.data);
      setSelectedPlanOrderId('');
      setAdjustment(null);
      setPlanOrderTab(preferredPlanOrderTab(detail.data));
      setWorkspaceView('orders');
      setOrderPoolCollapsed(true);
      setCancelConfirming(false);
      setCancelReason('');
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoadingWorkbench(true);
    Promise.resolve().then(async () => {
      try {
        await loadAll(true);
      } catch (err) {
        if (!cancelled) setStatus({ tone: 'error', message: formatError(err, '排程工作台加载失败。') });
      } finally {
        if (!cancelled) setLoadingWorkbench(false);
      }
    });
    return () => { cancelled = true; };
  }, [loadAll]);

  const toggleOrder = (orderId) => {
    setSelected(prev => prev.includes(orderId) ? prev.filter(id => id !== orderId) : [...prev, orderId]);
  };

  const selectFilteredOrders = () => {
    const nextIds = filteredOrders.map(order => order.order_id);
    setSelected(prev => [...new Set([...prev, ...nextIds])]);
  };

  const clearSelectedOrders = () => {
    setSelected([]);
  };

  const handleResetOrders = async () => {
    if (!resetConfirming) {
      setResetConfirming(true);
      return;
    }
    setBusy(true);
    try {
      const res = await resetOrdersToPending();
      await loadAll();
      setSelected([]);
      setResetConfirming(false);
      setStatus({ tone: 'ok', message: `已清理 ${res.data.updated_count} 条孤立已排订单，共 ${res.data.total_orders} 条订单。` });
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '清理孤立已排订单失败。') });
    } finally {
      setBusy(false);
    }
  };

  const handleClearActiveSchedule = async () => {
    if (!clearConfirming) {
      setClearConfirming(true);
      return;
    }
    setBusy(true);
    try {
      const res = await clearActiveSchedule();
      await loadAll();
      setActivePlan(null);
      setSelectedPlanOrderId('');
      setClearConfirming(false);
      setStatus({
        tone: 'ok',
        message: res.data.cleared
          ? `已撤销当前正式排程 #${res.data.run_id}，恢复 ${res.data.restored_order_count || 0} 条未开工订单，取消 ${res.data.cancelled_queue_count || 0} 条队列项。`
          : '当前没有正式排程需要撤销。',
      });
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '撤销当前正式排程失败。') });
    } finally {
      setBusy(false);
    }
  };

  const handleCreatePreplan = async () => {
    setBusy(true);
    setStatus({ tone: 'ok', message: '' });
    try {
      const res = await createPreplan({ order_ids: selected, mode: 'AUTO' });
      setActivePlan(res.data);
      setSelected([]);
      setSelectedPlanOrderId('');
      setAdjustment(null);
      setPlanOrderTab(preferredPlanOrderTab(res.data));
      setWorkspaceView('orders');
      setOrderPoolCollapsed(true);
      setCancelConfirming(false);
      setCancelReason('');
      const preplansRes = await getPreplans();
      setPreplans(preplansRes.data || []);
      const counts = planCounts(res.data.run, res.data.tasks?.length || 0);
      setStatus({
        tone: counts.blocked ? 'error' : 'ok',
        message: `已创建预排程草案 #${res.data.run.run_id}：输入 ${counts.input} 单，已排 ${counts.scheduled} 单，未排 ${counts.blocked} 单。`,
      });
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '创建预排程失败。') });
    } finally {
      setBusy(false);
    }
  };

  const openPlan = async (runId) => {
    setBusy(true);
    try {
      const res = await getPreplan(runId);
      setActivePlan(res.data);
      setAdjustment(null);
      setSelectedPlanOrderId('');
      setPlanOrderTab(preferredPlanOrderTab(res.data));
      setWorkspaceView('orders');
      setOrderPoolCollapsed(true);
      setCancelConfirming(false);
      setCancelReason('');
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '读取草案失败。') });
    } finally {
      setBusy(false);
    }
  };

  const openAdjustment = (task, nextMachineId = task.machine_id) => {
    if (!canAdjust) {
      setStatus({ tone: 'error', message: '只有待复核或已校验草案且开启人工调整时，才能记录人工调整。' });
      return;
    }
    setSelectedPlanOrderId(task.order_id);
    setCancelConfirming(false);
    setAdjustment({
      order_id: task.order_id,
      machine_id: nextMachineId,
      start_time: toDatetimeLocal(task.start_time),
      end_time: toDatetimeLocal(task.end_time),
      sequence_index: task.sequence_index,
      reason_code: 'OTHER',
      reason_text: '',
    });
  };

  const submitAdjustment = async () => {
    if (!activePlan || !adjustment) return;
    setBusy(true);
    try {
      const res = await adjustPreplanTask(activePlan.run.run_id, adjustment);
      setActivePlan(res.data);
      setSelectedPlanOrderId(adjustment.order_id);
      setAdjustment(null);
      setStatus({ tone: 'ok', message: '人工调整已记录，并已重新校验草案。' });
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '人工调整失败。') });
      if (err.response?.data?.detail?.items) {
        setActivePlan(prev => prev ? { ...prev, validation: { ...prev.validation, items: err.response.data.detail.items } } : prev);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleValidate = async () => {
    if (!activePlan) return;
    setBusy(true);
    try {
      const res = await validatePreplan(activePlan.run.run_id);
      const detail = await getPreplan(activePlan.run.run_id);
      setActivePlan(detail.data);
      setPlanOrderTab(preferredPlanOrderTab(detail.data));
      setWorkspaceView('orders');
      setStatus({ tone: res.data.hard_error_count ? 'error' : 'ok', message: res.data.hard_error_count ? '草案存在阻断错误。' : '草案校验完成。' });
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '校验草案失败。') });
    } finally {
      setBusy(false);
    }
  };

  const handleConfirm = async () => {
    if (!activePlan) return;
    setBusy(true);
    try {
      await confirmPreplan(activePlan.run.run_id);
      const [ordersRes, preplansRes, queueRes] = await Promise.all([
        loadPendingOrders(),
        getPreplans(),
        getManufacturingQueue(),
      ]);
      const nextOrders = ordersRes.items || [];
      const availableOrderIds = new Set(nextOrders.map(order => order.order_id));
      setOrders(nextOrders);
      setPendingOrderTotal(ordersRes.total || nextOrders.length);
      setSelected(prev => prev.filter(orderId => availableOrderIds.has(orderId)));
      setPreplans(preplansRes.data || []);
      setQueue(queueRes.data || []);
      const detail = await getPreplan(activePlan.run.run_id);
      setActivePlan(detail.data);
      setQueueExpanded(true);
      setCancelConfirming(false);
      setCancelReason('');
      setStatus({ tone: 'ok', message: `草案 #${activePlan.run.run_id} 已确认进入制造队列。` });
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '确认发布失败。') });
    } finally {
      setBusy(false);
    }
  };

  const openCancelConfirm = () => {
    if (!activePlan) return;
    setAdjustment(null);
    setCancelReason(activePlan.run.cancel_reason || '');
    setCancelConfirming(true);
  };

  const closeCancelConfirm = () => {
    setCancelConfirming(false);
    setCancelReason('');
  };

  const handleCancel = async () => {
    if (!activePlan || !canCancel) return;
    setBusy(true);
    try {
      const reason = cancelReason.trim() || '人工废弃草案';
      await cancelPreplan(activePlan.run.run_id, { reason });
      const [detail, preplansRes] = await Promise.all([
        getPreplan(activePlan.run.run_id),
        getPreplans(),
      ]);
      setActivePlan(detail.data);
      setSelectedPlanOrderId('');
      setAdjustment(null);
      setCancelConfirming(false);
      setCancelReason('');
      setPreplans(preplansRes.data || []);
      setStatus({ tone: 'ok', message: `草案 #${activePlan.run.run_id} 已废弃，订单状态未改变。` });
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '废弃草案失败。') });
    } finally {
      setBusy(false);
    }
  };

  const updateSetting = async (key, value) => {
    if (!settings || savingSettingKey) return;
    const previous = settings;
    const next = { ...settings, [key]: value };
    setSavingSettingKey(key);
    setSettings(next);
    setStatus({ tone: 'ok', message: '保存中...' });
    try {
      const res = await updateScheduleSettings({ [key]: value });
      setSettings(res.data);
      setStatus({ tone: 'ok', message: '系统开关已保存。' });
    } catch (err) {
      setSettings(previous);
      setStatus({ tone: 'error', message: formatError(err, '更新系统开关失败。') });
    } finally {
      setSavingSettingKey('');
    }
  };

  const selectPlanOrder = (orderId) => {
    setSelectedPlanOrderId(orderId);
    setAdjustment(null);
    setCancelConfirming(false);
  };

  const selectPlanOrderTab = (tabKey) => {
    const nextRows = planOrderRows[tabKey] || [];
    setPlanOrderTab(tabKey);
    setWorkspaceView('orders');
    setCancelConfirming(false);
    setAdjustment(null);
    if (!nextRows.some(row => row.order_id === selectedPlanOrderId)) {
      setSelectedPlanOrderId(nextRows[0]?.order_id || '');
    }
  };

  const selectWorkspaceView = (view) => {
    setWorkspaceView(view);
    setCancelConfirming(false);
    if (view === 'resource' && !selectedTask) {
      setSelectedPlanOrderId(planTasks[0]?.order_id || selectedPlanOrderId);
    }
  };

  return (
    <div className={`workbench-page ${activePlan ? 'has-active-plan' : ''}`}>
      <div className="page-header">
        <div>
          <h2>排程工作台</h2>
          <p className="page-subtitle">系统生成预排程，人负责复核和必要调整；所有人工改动都会进入审计记录。</p>
        </div>
        <div className="page-toolbar">
          <button className="btn btn-ghost" onClick={() => loadAll()} disabled={workbenchBusy} data-testid="workbench-refresh">刷新</button>
          <button className="btn btn-danger" onClick={handleResetOrders} disabled={workbenchBusy}>
            {resetConfirming ? '确认清理孤立订单' : '清理孤立已排订单'}
          </button>
          {resetConfirming && (
            <button className="btn btn-ghost" onClick={() => setResetConfirming(false)} disabled={workbenchBusy}>取消</button>
          )}
          <button className="btn btn-danger" onClick={handleClearActiveSchedule} disabled={workbenchBusy}>
            {clearConfirming ? '确认撤销正式排程' : '撤销当前排程'}
          </button>
          {clearConfirming && (
            <button className="btn btn-ghost" onClick={() => setClearConfirming(false)} disabled={workbenchBusy}>取消</button>
          )}
          <button className="btn btn-primary" disabled={workbenchBusy || selected.length === 0} onClick={handleCreatePreplan} data-testid="workbench-create-preplan">
            {workbenchBusy ? '处理中...' : `创建预排程 (${selected.length})`}
          </button>
        </div>
      </div>

      {status.message && <div className={`config-status ${status.tone === 'error' ? 'error' : 'ok'}`} data-testid="workbench-status">{status.message}</div>}

      <div className="workbench-settings">
        {settings && (
          <>
            <SettingsSwitch label="必须人工确认" checked={settings.review_required} disabled={savingSettingKey === 'review_required'} saving={savingSettingKey === 'review_required'} testId={settingTestIds.review_required} onChange={value => updateSetting('review_required', value)} />
            <SettingsSwitch label="允许人工调整" checked={settings.manual_adjust_enabled} disabled={savingSettingKey === 'manual_adjust_enabled'} saving={savingSettingKey === 'manual_adjust_enabled'} testId={settingTestIds.manual_adjust_enabled} onChange={value => updateSetting('manual_adjust_enabled', value)} />
            <SettingsSwitch label="调整原因必填" checked={settings.manual_adjust_reason_required} disabled={savingSettingKey === 'manual_adjust_reason_required'} saving={savingSettingKey === 'manual_adjust_reason_required'} testId={settingTestIds.manual_adjust_reason_required} onChange={value => updateSetting('manual_adjust_reason_required', value)} />
            <SettingsSwitch label="允许带警告发布" checked={settings.publish_with_warnings_allowed} disabled={savingSettingKey === 'publish_with_warnings_allowed'} saving={savingSettingKey === 'publish_with_warnings_allowed'} testId={settingTestIds.publish_with_warnings_allowed} onChange={value => updateSetting('publish_with_warnings_allowed', value)} />
            <SettingsSwitch label="免复核时自动发布" checked={settings.auto_release_enabled} disabled={savingSettingKey === 'auto_release_enabled'} saving={savingSettingKey === 'auto_release_enabled'} testId={settingTestIds.auto_release_enabled} onChange={value => updateSetting('auto_release_enabled', value)} />
          </>
        )}
      </div>

      <div className={`workbench-grid ${activePlan && orderPoolCollapsed ? 'order-pool-collapsed' : ''}`}>
        <section className={`workbench-panel order-pool ${activePlan && orderPoolCollapsed ? 'collapsed' : ''}`} data-testid="workbench-order-pool">
          <div className="workbench-panel-head">
            <div className="workbench-order-pool-title">
              <h3>{activePlan && orderPoolCollapsed ? '订单池' : '待排订单池'}</h3>
              <span>{activePlan && orderPoolCollapsed ? `${pendingOrderTotal} 单` : `已选 ${selected.length} / 当前 ${filteredOrders.length} / 共 ${pendingOrderTotal} 单`}</span>
            </div>
            {activePlan && (
              <button
                className="btn btn-ghost btn-small"
                type="button"
                aria-expanded={!orderPoolCollapsed}
                data-testid="workbench-order-pool-toggle"
                onClick={() => setOrderPoolCollapsed(prev => !prev)}
              >
                {orderPoolCollapsed ? '展开' : '收起'}
              </button>
            )}
          </div>
          {activePlan && orderPoolCollapsed ? (
            <div className="workbench-order-pool-rail">
              <strong>{pendingOrderTotal}</strong>
              <span>待排订单</span>
              <small>已选 {selected.length}</small>
            </div>
          ) : (
            <>
              <div className="workbench-order-tools">
                <input
                  className="search-input workbench-order-search"
                  value={orderQuery}
                  placeholder="搜索订单、产品、客户、规格"
                  data-testid="workbench-search"
                  onChange={event => setOrderQuery(event.target.value)}
                />
                <div className="workbench-filter-row">
                  <select value={orderClassFilter} data-testid="workbench-filter-order-class" onChange={event => setOrderClassFilter(event.target.value)}>
                    <option value="">全部类型</option>
                    {Object.entries(orderClassLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                  <select value={cleanroomFilter} data-testid="workbench-filter-cleanroom" onChange={event => setCleanroomFilter(event.target.value)}>
                    <option value="">全部洁净等级</option>
                    {Object.entries(cleanroomLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
                <div className="workbench-select-actions">
                  <button className="btn btn-ghost btn-small" type="button" disabled={!filteredOrders.length} data-testid="workbench-select-filtered" onClick={selectFilteredOrders}>
                    全选当前筛选
                  </button>
                  <button className="btn btn-ghost btn-small" type="button" disabled={!selected.length} data-testid="workbench-clear-selected" onClick={clearSelectedOrders}>
                    清空已选
                  </button>
                  <span>{selectedFilteredCount} 单已在当前筛选中</span>
                </div>
              </div>
              <div className="workbench-order-list">
                {filteredOrders.map(order => (
                  <button
                    key={order.order_id}
                    type="button"
                    className={`workbench-order ${selectedSet.has(order.order_id) ? 'selected' : ''}`}
                    data-testid={`workbench-pending-order-${testIdPart(order.order_id)}`}
                    onClick={() => toggleOrder(order.order_id)}
                  >
                    <div>
                      <strong>{order.order_id}</strong>
                      <span>{order.product_type}</span>
                    </div>
                    <small>{order.target_width}mm x {order.target_thickness}um · {order.total_quantity_kg}kg</small>
                    <div className="workbench-order-meta">
                      <Badge tone={order.order_class === 'URGENT' ? 'danger' : 'neutral'}>{orderClassLabels[order.order_class] || order.order_class}</Badge>
                      <span>{formatTime(order.due_date)}</span>
                    </div>
                  </button>
                ))}
                {!orders.length && <div className="config-empty">当前没有待排订单。</div>}
                {orders.length > 0 && !filteredOrders.length && <div className="config-empty">当前筛选条件下没有待排订单。</div>}
              </div>
            </>
          )}
        </section>

        <section
          className="workbench-panel plan-board"
          data-testid="workbench-main-workspace"
          data-loading={loadingWorkbench ? 'true' : 'false'}
          aria-busy={loadingWorkbench}
        >
          <div className="workbench-panel-head">
            <div>
              <h3>预排程草案</h3>
              <span data-testid="workbench-active-preplan-summary">
                {activePlan
                  ? `#${activePlan.run.run_id} · ${lifecycleLabels[activePlan.run.lifecycle_status] || activePlan.run.lifecycle_status} · ${runStatusLabels[activePlan.run.status] || activePlan.run.status}`
                  : '尚未选择草案'}
              </span>
            </div>
            <div className="config-actions">
              <button className="btn btn-ghost" disabled={!canEditDraft || workbenchBusy} data-testid="workbench-validate-preplan" onClick={handleValidate}>校验方案</button>
              <button className="btn btn-primary" disabled={!canConfirm || workbenchBusy} data-testid="workbench-confirm-preplan" onClick={handleConfirm}>确认进入制造队列</button>
              <button className="btn btn-danger" disabled={!canCancel || workbenchBusy} data-testid="workbench-cancel-preplan" onClick={openCancelConfirm}>废弃草案</button>
            </div>
          </div>

          {activePlan && publishBlockReason && (
            <div className="workbench-publish-hint">
              <strong>发布受阻</strong>
              <span>{publishBlockReason}</span>
            </div>
          )}

          {cancelConfirming && activePlan && (
            <div className="workbench-cancel-confirm" data-testid="workbench-cancel-confirm-panel">
              <div>
                <strong>确认废弃草案 #{activePlan.run.run_id}</strong>
                <span>已排 {planOrderCounts.scheduled} 单，未排 {planOrderCounts.blocked} 单。废弃后不会创建制造队列，订单仍留在待排池。</span>
              </div>
              <label>
                废弃原因（可选）
                <textarea
                  value={cancelReason}
                  placeholder="例如：输入订单选择错误、现场暂缓排产、需要重新调整约束后再排"
                  data-testid="workbench-cancel-reason"
                  onChange={event => setCancelReason(event.target.value)}
                />
              </label>
              <div className="config-actions">
                <button className="btn btn-danger" type="button" disabled={workbenchBusy} data-testid="workbench-cancel-confirm" onClick={handleCancel}>
                  确认废弃
                </button>
                <button className="btn btn-ghost" type="button" disabled={workbenchBusy} onClick={closeCancelConfirm}>
                  取消
                </button>
              </div>
            </div>
          )}

          <div className="workbench-plan-history">
            {visiblePreplans.map(plan => {
              const counts = planCounts(plan);
              const planCancelled = plan.lifecycle_status === 'CANCELLED';
              return (
                <button
                  key={plan.run_id}
                  type="button"
                  className={`${activePlan?.run.run_id === plan.run_id ? 'active' : ''} ${planCancelled ? 'cancelled' : ''}`.trim()}
                  data-testid={`workbench-preplan-${plan.run_id}`}
                  onClick={() => openPlan(plan.run_id)}
                >
                  <span>#{plan.run_id} · {lifecycleLabels[plan.lifecycle_status] || plan.lifecycle_status} · 已排 {counts.scheduled}/{counts.input} · 未排 {counts.blocked}</span>
                  {planCancelled && <small>原因：{plan.cancel_reason?.trim() || '未填写'}</small>}
                </button>
              );
            })}
          </div>

          {isCancelledPlan && (
            <div className="workbench-cancelled-notice">
              <strong>草案已废弃</strong>
              <span>原因：{cancellationReason}</span>
              <small>{activePlan.run.cancelled_by || '-'} · {formatTime(activePlan.run.cancelled_at)}</small>
            </div>
          )}

          {activePlan && (
            <div className={`workbench-plan-summary ${planOrderCounts.blocked ? 'warning' : ''}`}>
              <div className="workbench-summary-item">
                <span>输入订单</span>
                <strong>{planOrderCounts.input}</strong>
              </div>
              <div className="workbench-summary-item">
                <span>已排订单</span>
                <strong>{planOrderCounts.scheduled}</strong>
              </div>
              <div className="workbench-summary-item">
                <span>可排订单</span>
                <strong>{planOrderCounts.schedulable}</strong>
              </div>
              <div className="workbench-summary-item danger">
                <span>未排订单</span>
                <strong>{planOrderCounts.blocked}</strong>
              </div>
              <div className="workbench-summary-item warning">
                <span>延期订单</span>
                <strong>{planOrderCounts.late}</strong>
              </div>
            </div>
          )}

          {activePlan ? (
            <>
              <div className="workbench-workspace-head">
                <div className="workbench-view-tabs">
                  <button type="button" className={workspaceView === 'orders' ? 'active' : ''} data-testid="workbench-view-order-review" onClick={() => selectWorkspaceView('orders')}>
                    订单复核
                  </button>
                  <button type="button" className={workspaceView === 'resource' ? 'active' : ''} data-testid="workbench-view-resource" onClick={() => selectWorkspaceView('resource')}>
                    资源视图
                  </button>
                </div>
                <span>{workspaceView === 'orders' ? `当前分类：${activePlanOrderTab.label}` : '按吹膜机查看已落位任务'}</span>
              </div>

              {workspaceView === 'orders' ? (
                <div className="workbench-order-review">
                  <div className="workbench-plan-tabs">
                    {planOrderTabs.map(tab => (
                      <button
                        key={tab.key}
                        type="button"
                        className={`${planOrderTab === tab.key ? 'active' : ''} ${tab.tone || ''}`.trim()}
                        data-testid={planOrderTabTestIds[tab.key]}
                        disabled={loadingWorkbench}
                        onClick={() => selectPlanOrderTab(tab.key)}
                      >
                        <span>{tab.label}</span>
                        <strong>{tab.count}</strong>
                      </button>
                    ))}
                  </div>
                  {selectedPlanOrderId && !selectedOrderInCurrentTab && (
                    <div className="workbench-context-note">
                      当前选中订单不在“{activePlanOrderTab.label}”分类中，已保留右侧复核上下文。
                    </div>
                  )}
                  <div className="workbench-order-table" data-testid="workbench-order-table">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>订单</th>
                          <th className="plan-col-spec">产品/规格</th>
                          <th className="plan-col-due">交期</th>
                          <th>状态</th>
                          <th className="plan-col-machine">机台</th>
                          <th className="plan-col-time">计划时间</th>
                          <th className="plan-col-risk">根因/提示</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visiblePlanOrderRows.map(row => (
                          <tr
                            key={row.key}
                            className={selectedPlanOrderId === row.order_id ? 'selected' : ''}
                            onClick={() => selectPlanOrder(row.order_id)}
                          >
                            <td>
                              <button
                                type="button"
                                className="workbench-row-action"
                                data-testid={`workbench-plan-order-${testIdPart(row.order_id)}`}
                                aria-pressed={selectedPlanOrderId === row.order_id}
                                disabled={loadingWorkbench}
                                onClick={event => {
                                  event.stopPropagation();
                                  selectPlanOrder(row.order_id);
                                }}
                              >
                                {row.order_id}
                              </button>
                            </td>
                            <td className="plan-col-spec">
                              <div className="workbench-table-primary">{row.product_type}</div>
                              <small>{row.spec}</small>
                            </td>
                            <td className="plan-col-due">{formatTime(row.due_date)}</td>
                            <td><Badge tone={row.statusTone}>{row.statusLabel}</Badge></td>
                            <td className="plan-col-machine">{row.machine_id}</td>
                            <td className="plan-col-time">{row.start_time ? `${formatTime(row.start_time)} - ${formatTime(row.end_time)}` : '-'}</td>
                            <td className="plan-col-risk">{row.risk}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!visiblePlanOrderRows.length && <div className="config-empty">当前分类没有订单。</div>}
                  </div>
                </div>
              ) : (
                <div className="workbench-machines" data-testid="workbench-resource-view">
                  {machineIds.map(machineId => (
                    <div
                      key={machineId}
                      className="workbench-lane"
                      onDragOver={event => { if (canAdjust) event.preventDefault(); }}
                      onDrop={event => {
                        if (!canAdjust) return;
                        event.preventDefault();
                        const orderId = event.dataTransfer.getData('text/plain');
                        const task = planTasks.find(item => item.order_id === orderId);
                        if (task) openAdjustment(task, machineId);
                      }}
                    >
                      <div className="workbench-lane-head">
                        <strong>{machineId}</strong>
                        <span>{tasksByMachine[machineId]?.length || 0} 单</span>
                      </div>
                      {(tasksByMachine[machineId] || []).map(task => (
                        <div
                          key={`${task.id}-${task.order_id}`}
                          className={`workbench-task ${task.task_source !== 'AUTO' ? 'adjusted' : ''} ${selectedPlanOrderId === task.order_id ? 'selected' : ''}`}
                          data-testid={`workbench-resource-task-${testIdPart(task.order_id)}`}
                          draggable={canAdjust}
                          onDragStart={event => {
                            if (canAdjust) event.dataTransfer.setData('text/plain', task.order_id);
                          }}
                          onClick={() => selectPlanOrder(task.order_id)}
                        >
                          <div>
                            <strong>{task.order_id}</strong>
                            <Badge tone={task.task_source === 'AUTO' ? 'neutral' : 'warning'}>{sourceLabels[task.task_source] || task.task_source}</Badge>
                          </div>
                          <span>{task.product_type}</span>
                          <small>{formatTime(task.start_time)} - {formatTime(task.end_time)}</small>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="workbench-empty">先从左侧选择订单并创建预排程，或从上方历史草案打开。</div>
          )}
        </section>

        <aside className="workbench-panel review-panel" data-testid="workbench-inspector">
          <div className="workbench-panel-head">
            <h3>草案校验与复核</h3>
            {validation && (
              <Badge tone={validation.hard_error_count ? 'danger' : validation.warning_count ? 'warning' : 'success'}>
                {validationStatusLabels[validation.status] || validation.status}
              </Badge>
            )}
          </div>

          <div className="selected-order-review" data-testid="workbench-selected-order-review">
            <h4>当前订单复核</h4>
            {selectedPlanOrderId ? (
              <>
                {workspaceView === 'orders' && !selectedOrderInCurrentTab && (
                  <div className="workbench-context-warning">
                    当前订单不在“{activePlanOrderTab.label}”分类中，右侧保留的是跨视图选中的复核对象。
                  </div>
                )}
                <div className="selected-order-card">
                  <div>
                    <strong>{selectedPlanOrderId}</strong>
                    <Badge tone={selectedOrderStatusTone}>{selectedOrderStatusLabel}</Badge>
                  </div>
                  <span>{selectedOrder?.product_type || '-'}</span>
                  <small>{formatSpec(selectedOrder)} · 交期 {formatTime(selectedOrder?.due_date)}</small>
                  {selectedTask && <small>{selectedTask.machine_id} · {formatTime(selectedTask.start_time)} - {formatTime(selectedTask.end_time)}</small>}
                </div>
                {selectedOrderValidation.map((item, index) => (
                  <div key={`${item.code}-${index}`} className={`validation-item ${item.severity}`}>
                    <strong>{item.severity === 'error' ? '阻断' : '警告'} · {item.code}</strong>
                    <span>{item.message}</span>
                  </div>
                ))}
                {selectedOrderGuidance && (
                  <div className="blocked-item">
                    <strong>{selectedDiagnostic?.display_title || selectedDiagnostic?.entity_id || selectedPlanOrderId}</strong>
                    <span>{selectedOrderGuidance}</span>
                    {diagnosticEvidence(selectedDiagnostic) && <small>{diagnosticEvidence(selectedDiagnostic)}</small>}
                  </div>
                )}
                {!selectedOrderValidation.length && !selectedOrderGuidance && <div className="workbench-ok">当前订单无阻断或警告。</div>}
                {selectedTask && canAdjust && !adjustment && (
                  <button className="btn btn-ghost" type="button" data-testid="workbench-start-adjustment" disabled={loadingWorkbench} onClick={() => openAdjustment(selectedTask)}>
                    发起人工调整
                  </button>
                )}
              </>
            ) : (
              <div className="config-empty">从订单表或资源视图选择订单。</div>
            )}
          </div>

          {adjustment && canAdjust && (
            <div className="adjustment-form">
              <h4>记录一次人工调整</h4>
              <label>订单<input value={adjustment.order_id} disabled /></label>
              <label>机台
                <select value={adjustment.machine_id} data-testid="workbench-adjustment-machine" onChange={e => setAdjustment(prev => ({ ...prev, machine_id: e.target.value }))}>
                  {machineIds.map(machineId => <option key={machineId} value={machineId}>{machineId}</option>)}
                </select>
              </label>
              <label>开始时间<input type="datetime-local" value={adjustment.start_time} data-testid="workbench-adjustment-start" onChange={e => setAdjustment(prev => ({ ...prev, start_time: e.target.value }))} /></label>
              <label>结束时间<input type="datetime-local" value={adjustment.end_time} data-testid="workbench-adjustment-end" onChange={e => setAdjustment(prev => ({ ...prev, end_time: e.target.value }))} /></label>
              <label>调整原因
                <select value={adjustment.reason_code} data-testid="workbench-adjustment-reason-code" onChange={e => setAdjustment(prev => ({ ...prev, reason_code: e.target.value }))}>
                  {reasonOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label>原因说明<textarea value={adjustment.reason_text} data-testid="workbench-adjustment-reason-text" onChange={e => setAdjustment(prev => ({ ...prev, reason_text: e.target.value }))} /></label>
              <div className="config-actions">
                <button className="btn btn-primary" data-testid="workbench-submit-adjustment" onClick={submitAdjustment} disabled={!canAdjust || workbenchBusy}>记录调整</button>
                <button className="btn btn-ghost" onClick={() => setAdjustment(null)}>取消</button>
              </div>
            </div>
          )}

          <div className="validation-list">
            <h4>草案校验</h4>
            {validation && (
              <div className="workbench-validation-summary">
                <span>阻断 {validation.hard_error_count || 0}</span>
                <span>警告 {validation.warning_count || 0}</span>
              </div>
            )}
            {sortedValidationItems.slice(0, 12).map((item, index) => (
              <div key={`${item.code}-${item.order_id}-${index}`} className={`validation-item ${item.severity}`}>
                <strong>{item.severity === 'error' ? '阻断' : '警告'} · {item.code}</strong>
                <span>{item.message}</span>
              </div>
            ))}
            {validation && !validation.items.length && <div className="workbench-ok">当前草案无阻断错误。</div>}
            {!validation && <div className="config-empty">选择草案后显示校验结果。</div>}
          </div>

          {activePlan && planOrderCounts.blocked > 0 && (
            <div className="blocked-list">
              <h4>未排订单根因摘要</h4>
              <div className="workbench-risk-summary">
                本草案还有 {planOrderCounts.blocked} 单未进入排程，确认发布只会释放已排的 {planOrderCounts.scheduled} 单。
              </div>
              {blockedDiagnostics.map(diagnostic => (
                <div key={diagnostic.id || `${diagnostic.entity_id}-${diagnostic.code}`} className="blocked-item">
                  <strong>{diagnostic.entity_id || diagnostic.order_id || diagnostic.display_title}</strong>
                  <span>{diagnostic.root_cause || diagnostic.bucket_reason}</span>
                  {diagnosticEvidence(diagnostic) && <small>{diagnosticEvidence(diagnostic)}</small>}
                </div>
              ))}
              {!blockedDiagnostics.length && <div className="config-empty">后端未返回未排订单明细，请查看当前排程报告。</div>}
            </div>
          )}

          <div className="audit-list">
            <h4>调整记录</h4>
            {(activePlan?.adjustments || []).slice(0, 8).map(item => (
              <div key={item.id} className="audit-item">
                <strong>{item.order_id} · {item.validation_status}</strong>
                <span>{item.reason_text || reasonOptions.find(([value]) => value === item.reason_code)?.[1] || item.reason_code}</span>
                <small>{item.changed_by} · {formatTime(item.changed_at)}</small>
              </div>
            ))}
            {activePlan && !activePlan.adjustments.length && <div className="config-empty">暂无人工调整。</div>}
          </div>
        </aside>
      </div>

      <section className={`workbench-panel queue-panel ${queueExpanded ? 'expanded' : 'collapsed'}`} data-testid="workbench-queue-panel">
        <div className="workbench-panel-head">
          <div>
            <h3>制造队列</h3>
            <span>{queue.length} 项{queueRunIds.length ? ` · 运行 #${queueRunIds.slice(0, 3).join(', #')}` : ''}</span>
          </div>
          <button
            className="btn btn-ghost btn-small"
            type="button"
            aria-expanded={queueExpanded}
            data-testid="workbench-queue-toggle"
            onClick={() => setQueueExpanded(prev => !prev)}
          >
            {queueExpanded ? '收起' : '展开'}
          </button>
        </div>
        <div className="workbench-queue-summary">
          <strong>{queue.length}</strong>
          <span>{queue.length ? '已进入制造队列，展开查看前 20 项。' : '尚无已确认的制造队列。'}</span>
        </div>
        {queueExpanded && (
          <div className="queue-table" data-testid="workbench-queue-table">
            <table className="data-table">
              <thead>
                <tr>
                  <th>订单</th>
                  <th>机台</th>
                  <th>计划时间</th>
                  <th>状态</th>
                  <th>来源运行</th>
                </tr>
              </thead>
              <tbody>
                {queue.slice(0, 20).map(item => (
                  <tr key={item.id}>
                    <td>{item.order_id}</td>
                    <td>{item.machine_id}</td>
                    <td>{formatTime(item.planned_start_time)} - {formatTime(item.planned_end_time)}</td>
                    <td><Badge tone="success">{item.queue_status}</Badge></td>
                    <td>#{item.run_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!queue.length && <div className="config-empty">尚无已确认的制造队列。</div>}
          </div>
        )}
      </section>
    </div>
  );
}
