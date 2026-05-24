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
  screenOrders,
  updateManufacturingQueueItem,
  validatePreplan,
} from '../api/client';
import { Link } from 'react-router-dom';
import {
  deriveDraftVersionState,
  derivePublishChecklist,
  derivePrimaryAction,
  deriveReviewTabs,
  deriveWorkbenchStageStates,
  deriveWorkflowStep,
  draftVersionLabels,
  draftVersionTones,
  isDraftStale,
  isSelectableScreening,
  matchesScreeningFilter,
  selectableOrderIds,
  summarizeQueue,
  workbenchStageLabels,
  workbenchStages,
} from './workbenchViewModel';

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

const validationCodeLabels = {
  order_snapshot_stale: '草案订单快照已过期',
  policy_snapshot_stale: '全局策略已变化',
  'capacity.no_feasible_solution': '产能约束无可行解',
  'validation.schedule_result_invalid': '排程结果校验失败',
};

const policySummaryLabels = {
  review_required: '人工确认',
  manual_adjust_enabled: '人工调整',
  publish_with_warnings_allowed: '带警告发布',
  material_constraint_enabled: '物料齐套',
  maintenance_constraint_enabled: '维护窗口',
  setup_rules_enabled: '换产规则',
  cleanroom_constraint_enabled: '洁净等级',
  machine_capability_constraint_enabled: '机台能力',
  due_date_optimization_enabled: '交期优化',
};

const auditEventLabels = {
  PUBLISH: '发布成功',
  CLEAR_ACTIVE: '撤销正式排程',
  QUEUE_STATUS_CHANGE: '队列状态推进',
};

const adjustmentValidationStatusLabels = {
  PASSED: '校验通过',
  WARNING: '校验警告',
  FAILED: '校验失败',
};

const screeningLabels = {
  ready: '可排',
  risk: '风险',
  blocked: '阻断',
};

const screeningTones = {
  ready: 'success',
  risk: 'warning',
  blocked: 'danger',
};

const sourceLabels = {
  AUTO: '系统预排',
  ADJUSTED: '人工调整',
  MANUAL: '人工派单',
};

const queueStatusLabels = {
  QUEUED: '已排队',
  READY: '可开工',
  IN_PRODUCTION: '生产中',
  COMPLETED: '已完工',
  ON_HOLD: '暂停',
  CANCELLED: '已取消',
};

const queueStatusTones = {
  QUEUED: 'neutral',
  READY: 'success',
  IN_PRODUCTION: 'warning',
  COMPLETED: 'success',
  ON_HOLD: 'warning',
  CANCELLED: 'danger',
};

const queueActionLabels = {
  READY: '备料完成',
  IN_PRODUCTION: '开工',
  COMPLETED: '完工',
  ON_HOLD: '暂停',
  CANCELLED: '取消',
};

const queueActionReasonRequired = new Set(['ON_HOLD', 'CANCELLED']);
const WORKBENCH_PAGE_SIZE = 10;

const primaryActionTestIds = {
  validate: 'workbench-validate-preplan',
  confirm: 'workbench-confirm-preplan',
  queue: 'workbench-view-queue',
  blockers: 'workbench-view-blockers',
  version: 'workbench-view-versions',
  orders: 'workbench-view-orders',
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

const planOrderTabTestIds = {
  needs_action: 'workbench-order-tab-needs-action',
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

function validationCodeLabel(code) {
  return validationCodeLabels[code] || code || '校验项';
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

const setupCategoryLabels = {
  material: '物料换批',
  width: '幅宽调整',
  thickness: '厚度调整',
  corona: '电晕切换',
  core: '卷芯切换',
  gmp: 'GMP清场',
};

function setupComponents(task) {
  return Array.isArray(task?.setup_detail?.components) ? task.setup_detail.components : [];
}

function setupSummary(task) {
  if (!task) return '';
  const setupMins = asNumber(task.setup_time_mins);
  if (setupMins <= 0) return '无启用换产规则产生换产时间';
  const labels = setupComponents(task).map(item => `${setupCategoryLabels[item.category] || item.category} ${item.minutes}分钟`);
  return labels.length ? labels.join('，') : `换产 ${setupMins} 分钟，暂无分项明细`;
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

function nextQueueActions(status) {
  return {
    QUEUED: ['READY', 'CANCELLED'],
    READY: ['IN_PRODUCTION', 'ON_HOLD', 'CANCELLED'],
    ON_HOLD: ['READY', 'CANCELLED'],
    IN_PRODUCTION: ['COMPLETED', 'ON_HOLD'],
  }[status] || [];
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
  if (counts.hardErrors > 0 || counts.blocked > 0 || counts.late > 0) return 'needs_action';
  return 'scheduled';
}

function Badge({ children, tone = 'neutral' }) {
  return <span className={`workbench-badge ${tone}`}>{children}</span>;
}

function pageCount(total, pageSize = WORKBENCH_PAGE_SIZE) {
  return Math.max(1, Math.ceil(total / pageSize));
}

function pageSlice(rows, page, pageSize = WORKBENCH_PAGE_SIZE) {
  const safePage = Math.min(Math.max(1, page), pageCount(rows.length, pageSize));
  const start = (safePage - 1) * pageSize;
  return rows.slice(start, start + pageSize);
}

function PaginationControls({ label, page, total, onPageChange, testIdBase, pageSize = WORKBENCH_PAGE_SIZE }) {
  const totalPages = pageCount(total, pageSize);
  if (total <= pageSize) return null;
  const safePage = Math.min(Math.max(1, page), totalPages);
  const start = (safePage - 1) * pageSize + 1;
  const end = Math.min(total, safePage * pageSize);
  return (
    <div className="workbench-pagination" data-testid={`${testIdBase}-pagination`}>
      <div>
        <strong>{label}</strong>
        <span data-testid={`${testIdBase}-page-info`}>第 {safePage} / {totalPages} 页 · {start}-{end} / {total}</span>
      </div>
      <div className="config-actions">
        <button
          type="button"
          className="btn btn-ghost btn-small"
          disabled={safePage <= 1}
          data-testid={`${testIdBase}-prev`}
          onClick={() => onPageChange(safePage - 1)}
        >
          上一页
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-small"
          disabled={safePage >= totalPages}
          data-testid={`${testIdBase}-next`}
          onClick={() => onPageChange(safePage + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}

function PolicySummary({ settings }) {
  if (!settings) return null;
  const keys = Object.keys(policySummaryLabels);
  return (
    <div className="workbench-policy-summary" data-testid="workbench-policy-summary">
      <div>
        <strong>全局排程策略</strong>
        <span>版本 #{settings.policy_version || 1} · {settings.updated_by || '系统'} · {formatTime(settings.updated_at)}</span>
      </div>
      <div className="workbench-policy-chips">
        {keys.map(key => (
          <Badge key={key} tone={settings[key] === false ? 'danger' : 'success'}>
            {policySummaryLabels[key]}{settings[key] === false ? '关' : '开'}
          </Badge>
        ))}
      </div>
      <Link className="btn btn-ghost btn-small" to="/config?tab=policy">配置策略</Link>
    </div>
  );
}

function WorkflowStepper({ activeStage, recommendedStage, stageStates, onStageChange }) {
  return (
    <div className="workbench-workflow-stepper" data-testid="workbench-workflow-stepper">
      {workbenchStages.map(({ key, label, description }, index) => {
        const state = stageStates?.[key] || { status: activeStage === key ? 'current' : 'available', locked: false, lockReason: '' };
        return (
          <button
            key={key}
            type="button"
            className={`workbench-workflow-step ${state.status} ${activeStage === key ? 'active' : ''} ${recommendedStage === key ? 'recommended' : ''}`.trim()}
            aria-current={activeStage === key ? 'step' : undefined}
            aria-disabled={state.locked ? 'true' : undefined}
            disabled={state.locked}
            title={state.lockReason || description}
            data-testid={`workbench-stage-${key}`}
            onClick={() => onStageChange(key)}
          >
            <span>{index + 1}</span>
            <div>
              <strong>{label}</strong>
              <small data-testid={state.locked ? `workbench-stage-${key}-lock-reason` : undefined}>
                {state.locked ? state.lockReason : description}
              </small>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function ActiveDraftCommandBar({
  activePlan,
  counts,
  versionState,
  publishBlockReason,
  primaryAction,
  workbenchBusy,
  onPrimaryAction,
  onOpenVersions,
  onCancel,
  onRefresh,
}) {
  const lifecycle = activePlan?.run?.lifecycle_status;
  const showPrimaryAction = primaryAction.target !== 'create';
  const primaryActionTestId = primaryActionTestIds[primaryAction.target];
  return (
    <section className={`workbench-command-bar ${publishBlockReason ? 'blocked' : ''}`} data-testid="workbench-command-bar">
      <div className="workbench-command-main">
        <span className="workbench-command-eyebrow">当前草案</span>
        <h3>{activePlan ? `#${activePlan.run.run_id} · ${lifecycleLabels[lifecycle] || lifecycle}` : '尚未创建预排程草案'}</h3>
        <p>
          {activePlan
            ? (publishBlockReason || '当前草案可继续复核，发布前以校验结果为准。')
            : '选择待排订单后创建预排程草案。创建草案不会改变订单状态。'}
        </p>
      </div>
      <div className="workbench-command-metrics">
        <Badge tone="neutral">输入 {counts.input}</Badge>
        <Badge tone="success">已排 {counts.scheduled}</Badge>
        <Badge tone="success">可排 {counts.schedulable}</Badge>
        <Badge tone={counts.blocked ? 'danger' : 'neutral'}>未排 {counts.blocked}</Badge>
        <Badge tone={counts.late ? 'warning' : 'neutral'}>延期 {counts.late}</Badge>
        {activePlan && <Badge tone={draftVersionTones[versionState] || 'neutral'}>{draftVersionLabels[versionState] || '尚无草案'}</Badge>}
      </div>
      <div className="workbench-command-actions">
        {showPrimaryAction && (
          <div className="workbench-primary-action-wrap" data-testid="workbench-primary-action">
            <button
              type="button"
              className="btn btn-primary"
              data-testid={primaryActionTestId}
              disabled={workbenchBusy || primaryAction.disabled}
              onClick={onPrimaryAction}
            >
              {primaryAction.label}
            </button>
          </div>
        )}
        <button type="button" className="btn btn-ghost btn-small" data-testid="workbench-version-drawer-toggle" onClick={onOpenVersions}>
          草案版本
        </button>
        {activePlan && ['DRAFT', 'VALIDATED'].includes(lifecycle) && (
          <button type="button" className="btn btn-danger btn-small" data-testid="workbench-cancel-preplan" onClick={onCancel}>
            废弃草案
          </button>
        )}
        <button type="button" className="btn btn-ghost btn-small" onClick={onRefresh}>
          刷新
        </button>
      </div>
    </section>
  );
}

function DraftVersionDrawer({ open, filter, onFilterChange, activePlan, preplans, onOpenPlan, onClose }) {
  const filters = [
    ['active', '有效草案'],
    ['all', '全部'],
    ['DRAFT', '待复核'],
    ['VALIDATED', '已校验'],
    ['CONFIRMED', '已发布'],
    ['CANCELLED', '已废弃'],
  ];
  const rows = preplans.filter(plan => {
    if (filter === 'all') return true;
    if (filter === 'active') return ['DRAFT', 'VALIDATED'].includes(plan.lifecycle_status);
    return plan.lifecycle_status === filter;
  });
  return (
    <aside className={`workbench-version-drawer ${open ? 'open' : ''}`} data-testid="workbench-version-drawer" hidden={!open}>
      <div className="workbench-version-head">
        <div>
          <h3>草案版本</h3>
          <span>{rows.length} 个版本</span>
        </div>
        <button type="button" className="btn btn-ghost btn-small" data-testid="workbench-version-drawer-close" onClick={onClose}>
          关闭
        </button>
      </div>
      <div className="workbench-version-filters">
        {filters.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={filter === value ? 'active' : ''}
            aria-current={filter === value ? 'true' : undefined}
            data-testid={`workbench-version-filter-${String(value).toLowerCase()}`}
            onClick={() => onFilterChange(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="workbench-version-list">
        {rows.map(plan => {
          const counts = planCounts(plan);
          const isActive = activePlan?.run?.run_id === plan.run_id;
          return (
            <button
              key={plan.run_id}
              type="button"
              className={isActive ? 'active' : ''}
              aria-current={isActive ? 'true' : undefined}
              data-testid={`workbench-version-run-${plan.run_id}`}
              onClick={() => onOpenPlan(plan.run_id)}
            >
              <strong>#{plan.run_id} · {lifecycleLabels[plan.lifecycle_status] || plan.lifecycle_status}</strong>
              <span>输入 {counts.input} · 已排 {counts.scheduled} · 未排 {counts.blocked}</span>
              {plan.cancel_reason && <small>废弃原因：{plan.cancel_reason}</small>}
            </button>
          );
        })}
        {!rows.length && <div className="config-empty">当前筛选下没有草案版本。</div>}
      </div>
    </aside>
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
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [orderQuery, setOrderQuery] = useState('');
  const [orderClassFilter, setOrderClassFilter] = useState('');
  const [cleanroomFilter, setCleanroomFilter] = useState('');
  const [screeningFilter, setScreeningFilter] = useState('schedulable');
  const [orderScreening, setOrderScreening] = useState({ summary: null, items: [], error: '' });
  const [queueExpanded, setQueueExpanded] = useState(false);
  const [queueAction, setQueueAction] = useState({ queueId: null, targetStatus: '', reason: '' });
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false);
  const [versionFilter, setVersionFilter] = useState('active');
  const [stageOverride, setStageOverride] = useState(null);
  const [selectedContext, setSelectedContext] = useState(null);
  const [orderPoolPage, setOrderPoolPage] = useState(1);
  const [draftOrdersPage, setDraftOrdersPage] = useState(1);
  const [queuePage, setQueuePage] = useState(1);

  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const screeningByOrderId = useMemo(
    () => new Map((orderScreening.items || []).map(item => [item.order_id, item])),
    [orderScreening.items],
  );
  const filteredOrders = useMemo(() => {
    const query = orderQuery.trim().toLowerCase();
    return orders.filter(order => {
      if (orderClassFilter && order.order_class !== orderClassFilter) return false;
      if (cleanroomFilter && order.cleanroom_req !== cleanroomFilter) return false;
      if (!matchesScreeningFilter(screeningByOrderId.get(order.order_id), screeningFilter)) return false;
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
  }, [orders, orderQuery, orderClassFilter, cleanroomFilter, screeningByOrderId, screeningFilter]);
  const filteredOrderPageCount = pageCount(filteredOrders.length);
  const pagedFilteredOrders = useMemo(
    () => pageSlice(filteredOrders, orderPoolPage),
    [filteredOrders, orderPoolPage],
  );
  const selectedFilteredCount = useMemo(
    () => filteredOrders.filter(order => selectedSet.has(order.order_id)).length,
    [filteredOrders, selectedSet],
  );
  const selectableSelectedIds = useMemo(
    () => selected.filter(orderId =>
      isSelectableScreening(screeningByOrderId.get(orderId)),
    ),
    [screeningByOrderId, selected],
  );
  const selectableFilteredOrderIds = useMemo(
    () => selectableOrderIds(filteredOrders, screeningByOrderId),
    [filteredOrders, screeningByOrderId],
  );
  const selectedPendingOrder = useMemo(
    () => {
      if (selectedContext?.type === 'pending_order') {
        const contextualOrder = orders.find(order => order.order_id === selectedContext.id);
        if (contextualOrder) return contextualOrder;
      }
      return orders.find(order => selectedSet.has(order.order_id)) || filteredOrders[0] || null;
    },
    [filteredOrders, orders, selectedContext, selectedSet],
  );
  const selectedPendingScreening = selectedPendingOrder ? screeningByOrderId.get(selectedPendingOrder.order_id) : null;
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
  const requiresReview = settings ? settings.review_required !== false : true;
  const reviewValidationPending = Boolean(activePlan) && requiresReview && activePlan.run.lifecycle_status !== 'VALIDATED';
  const hasHardErrors = asNumber(validation?.hard_error_count) > 0;
  const warningPublishBlocked = asNumber(validation?.warning_count) > 0 && settings && !settings.publish_with_warnings_allowed;
  const draftVersionState = useMemo(
    () => deriveDraftVersionState(activePlan),
    [activePlan],
  );
  const canConfirm = canEditDraft && planTasks.length > 0 && !hasHardErrors && !warningPublishBlocked && !reviewValidationPending && !isDraftStale(draftVersionState);
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
    const unplaced = asArray(activePlan?.unplaced_schedulable_orders)
      .map(row => buildRow(row?.order_id ? row : row, { bucket: 'unplaced_schedulable' }))
      .sort((a, b) => orderSortKey(a).localeCompare(orderSortKey(b)));
    const late = (hasBackendBuckets ? asArray(activePlan?.late_orders) : lateTasks)
      .map(row => buildRow(row?.order_id ? row : row, { bucket: 'late' }))
      .sort((a, b) => orderSortKey(a).localeCompare(orderSortKey(b)));
    const blockers = hardValidationItems.map((item, index) => buildRow(item.order_id, {
      validationItem: item,
      bucket: 'blockers',
      key: `${item.code}-${item.order_id}-${index}`,
    }));
    const needsActionMap = new Map();
    [...blockers, ...blocked, ...unplaced, ...late].forEach(row => {
      if (row?.order_id && !needsActionMap.has(row.order_id)) needsActionMap.set(row.order_id, row);
    });
    return {
      needs_action: [...needsActionMap.values()].sort((a, b) => orderSortKey(a).localeCompare(orderSortKey(b))),
      input: (hasBackendBuckets ? asArray(activePlan?.input_orders) : inputOrderIds)
        .map(row => buildRow(row?.order_id ? row : row)),
      schedulable,
      scheduled,
      blocked,
      late,
      blockers,
    };
  }, [activePlan, bucketRows, diagnosticsByOrderId, hardValidationItems, inputOrderIds, lateTasks, orderById, planTasks, taskByOrderId, validationByOrderId]);
  const planOrderCounts = useMemo(() => ({
    input: Array.isArray(activePlan?.input_orders) ? activePlan.input_orders.length : activeCounts.input,
    schedulable: Array.isArray(activePlan?.schedulable_orders) ? activePlan.schedulable_orders.length : activeCounts.schedulable,
    scheduled: Array.isArray(activePlan?.scheduled_orders) ? activePlan.scheduled_orders.length : activeCounts.scheduled,
    blocked: Array.isArray(activePlan?.blocked_orders) ? activePlan.blocked_orders.length : activeCounts.blocked,
    late: Array.isArray(activePlan?.late_orders) ? activePlan.late_orders.length : (activePlan?.run?.late_orders || lateTasks.length),
  }), [activeCounts, activePlan, lateTasks.length]);
  const needsActionCount = planOrderRows.needs_action?.length || 0;
  const planOrderTabs = useMemo(
    () => deriveReviewTabs({
      counts: planOrderCounts,
      hardErrorCount: hardValidationItems.length,
      needsActionCount,
    }),
    [hardValidationItems.length, needsActionCount, planOrderCounts],
  );
  const visiblePlanOrderRows = useMemo(
    () => planOrderRows[planOrderTab] || [],
    [planOrderRows, planOrderTab],
  );
  const draftOrderPageCount = pageCount(visiblePlanOrderRows.length);
  const pagedVisiblePlanOrderRows = useMemo(
    () => pageSlice(visiblePlanOrderRows, draftOrdersPage),
    [draftOrdersPage, visiblePlanOrderRows],
  );
  const activePlanOrderTab = planOrderTabs.find(tab => tab.key === planOrderTab) || planOrderTabs[0];
  const selectedOrderInCurrentTab = Boolean(
    selectedPlanOrderId && visiblePlanOrderRows.some(row => row.order_id === selectedPlanOrderId),
  );
  const publishBlockReason = useMemo(() => {
    if (!activePlan || canConfirm) return '';
    if (!canEditDraft) return '当前草案不是待复核或已校验状态，不能发布。';
    if (!planTasks.length) return '草案没有已排任务，无法进入制造队列。';
    if (isDraftStale(draftVersionState)) return draftVersionLabels[draftVersionState] || '草案快照已过期，需要重新预排。';
    if (reviewValidationPending) return '当前草案需要先校验方案，完成校验后才能确认进入制造队列。';
    if (hasHardErrors) return `存在 ${asNumber(validation?.hard_error_count, hardValidationItems.length)} 个草案阻断，需处理后发布。`;
    if (warningPublishBlocked) return `存在 ${asNumber(validation?.warning_count)} 个警告，当前系统不允许带警告发布。`;
    return '';
  }, [activePlan, canConfirm, canEditDraft, draftVersionState, hardValidationItems.length, hasHardErrors, planTasks.length, reviewValidationPending, validation, warningPublishBlocked]);
  const activeQueueSummary = useMemo(
    () => summarizeQueue(queue, activePlan?.run?.run_id || null),
    [activePlan, queue],
  );
  const activeQueuePageCount = pageCount(activeQueueSummary.rows.length);
  const pagedQueueRows = useMemo(
    () => pageSlice(activeQueueSummary.rows, queuePage),
    [activeQueueSummary.rows, queuePage],
  );
  const latestQueueTransition = useMemo(() => {
    return activeQueueSummary.rows
      .filter(item => item.last_transition)
      .sort((a, b) => new Date(b.last_transition.created_at || 0) - new Date(a.last_transition.created_at || 0))[0] || null;
  }, [activeQueueSummary.rows]);
  const selectedValidationItem = selectedContext?.type === 'validation_item' ? selectedContext.item : null;
  const selectedQueueItem = useMemo(
    () => (selectedContext?.type === 'queue_item'
      ? activeQueueSummary.rows.find(item => String(item.id) === String(selectedContext.id)) || selectedContext.item || null
      : null),
    [activeQueueSummary.rows, selectedContext],
  );
  const workflowStep = useMemo(
    () => deriveWorkflowStep({
      activePlan,
      queue: activeQueueSummary.rows,
      draftVersionState,
      hasHardErrors,
    }),
    [activePlan, activeQueueSummary.rows, draftVersionState, hasHardErrors],
  );
  const recommendedStage = workflowStep;
  const requestedStage = stageOverride || recommendedStage;
  const requestedStageStates = useMemo(
    () => deriveWorkbenchStageStates({
      activePlan,
      activeStage: requestedStage,
      recommendedStage,
      queueCount: activeQueueSummary.total,
      validation,
      canConfirm,
      canEditDraft,
      reviewValidationPending,
      draftVersionState,
      hasHardErrors,
    }),
    [activePlan, activeQueueSummary.total, canConfirm, canEditDraft, draftVersionState, hasHardErrors, recommendedStage, requestedStage, reviewValidationPending, validation],
  );
  const activeStage = requestedStageStates[requestedStage]?.locked ? recommendedStage : requestedStage;
  const stageStates = useMemo(
    () => deriveWorkbenchStageStates({
      activePlan,
      activeStage,
      recommendedStage,
      queueCount: activeQueueSummary.total,
      validation,
      canConfirm,
      canEditDraft,
      reviewValidationPending,
      draftVersionState,
      hasHardErrors,
    }),
    [activePlan, activeQueueSummary.total, activeStage, canConfirm, canEditDraft, draftVersionState, hasHardErrors, recommendedStage, reviewValidationPending, validation],
  );
  const activeStageIndex = workbenchStages.findIndex(stage => stage.key === activeStage);
  const previousStage = activeStageIndex > 0 ? workbenchStages[activeStageIndex - 1] : null;
  const nextStage = activeStageIndex >= 0 && activeStageIndex < workbenchStages.length - 1
    ? workbenchStages[activeStageIndex + 1]
    : null;
  const primaryAction = useMemo(
    () => derivePrimaryAction({
      activePlan,
      selectedCount: selectableSelectedIds.length,
      canConfirm,
      canEditDraft,
      hasHardErrors,
      publishBlockReason,
      reviewValidationPending,
      draftVersionState,
    }),
    [activePlan, canConfirm, canEditDraft, draftVersionState, hasHardErrors, publishBlockReason, reviewValidationPending, selectableSelectedIds.length],
  );
  const publishChecklist = useMemo(
    () => derivePublishChecklist({
      activePlan,
      counts: activePlan ? planOrderCounts : { input: selectableSelectedIds.length, scheduled: 0, schedulable: 0, blocked: 0, late: 0 },
      validation,
      draftVersionLabel: draftVersionLabels[draftVersionState] || '尚无草案',
      publishBlockReason,
      canConfirm,
      queueCount: activeQueueSummary.total,
    }),
    [activePlan, activeQueueSummary.total, canConfirm, draftVersionState, planOrderCounts, publishBlockReason, selectableSelectedIds.length, validation],
  );
  useEffect(() => {
    if (!activePlan || selectedPlanOrderId || workspaceView !== 'orders') return;
    const firstRow = visiblePlanOrderRows[0];
    if (firstRow?.order_id) setSelectedPlanOrderId(firstRow.order_id);
  }, [activePlan, selectedPlanOrderId, visiblePlanOrderRows, workspaceView]);

  useEffect(() => {
    setOrderPoolPage(1);
  }, [cleanroomFilter, orderClassFilter, orderQuery, screeningFilter]);

  useEffect(() => {
    setOrderPoolPage(prev => Math.min(prev, filteredOrderPageCount));
  }, [filteredOrderPageCount]);

  useEffect(() => {
    setDraftOrdersPage(1);
  }, [activePlan?.run?.run_id, planOrderTab]);

  useEffect(() => {
    setDraftOrdersPage(prev => Math.min(prev, draftOrderPageCount));
  }, [draftOrderPageCount]);

  useEffect(() => {
    setQueuePage(1);
  }, [activePlan?.run?.run_id]);

  useEffect(() => {
    setQueuePage(prev => Math.min(prev, activeQueuePageCount));
  }, [activeQueuePageCount]);

  useEffect(() => {
    if (stageOverride && stageStates[stageOverride]?.locked) {
      setStageOverride(null);
    }
  }, [stageOverride, stageStates]);

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
    if (nextOrders.length) {
      try {
        const screeningRes = await screenOrders({
          scope: 'selected',
          order_ids: nextOrders.map(order => order.order_id),
        });
        setOrderScreening({
          summary: screeningRes.data.summary,
          items: screeningRes.data.items || [],
          error: '',
        });
      } catch (err) {
        setOrderScreening({
          summary: null,
          items: [],
          error: formatError(err, '订单初筛失败。'),
        });
      }
    } else {
      setOrderScreening({ summary: null, items: [], error: '' });
    }
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
      setSelectedContext(null);
      setPlanOrderTab(preferredPlanOrderTab(detail.data));
      setWorkspaceView('orders');
      setStageOverride(null);
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
    const screening = screeningByOrderId.get(orderId);
    if (!isSelectableScreening(screening)) {
      setStatus({
        tone: 'error',
        message: screening?.is_stale
          ? '\u8ba2\u5355\u7b5b\u9009\u7ed3\u679c\u5df2\u8fc7\u671f\uff0c\u8bf7\u5148\u91cd\u65b0\u7b5b\u9009\u540e\u518d\u8fdb\u5165\u9884\u6392\u3002'
          : '\u963b\u65ad\u8ba2\u5355\u9700\u8981\u5148\u5904\u7406\u5f02\u5e38\uff0c\u4e0d\u80fd\u76f4\u63a5\u8fdb\u5165\u9884\u6392\u3002',
      });
      return;
    }
    setSelected(prev => prev.includes(orderId) ? prev.filter(id => id !== orderId) : [...prev, orderId]);
    setSelectedContext({ type: 'pending_order', id: orderId, sourceStage: 'order_pool' });
  };

  const selectFilteredOrders = () => {
    const nextIds = selectableFilteredOrderIds;
    setSelected(prev => [...new Set([...prev, ...nextIds])]);
  };

  const clearSelectedOrders = () => {
    setSelected([]);
    if (selectedContext?.type === 'pending_order') setSelectedContext(null);
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
      setSelectedContext(null);
      setStageOverride(null);
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
      const res = await createPreplan({ order_ids: selectableSelectedIds, mode: 'AUTO' });
      setActivePlan(res.data);
      setSelected([]);
      setSelectedPlanOrderId('');
      setAdjustment(null);
      setSelectedContext(null);
      setPlanOrderTab(preferredPlanOrderTab(res.data));
      setWorkspaceView('orders');
      setStageOverride(null);
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
      setSelectedContext(null);
      setPlanOrderTab(preferredPlanOrderTab(res.data));
      setWorkspaceView('orders');
      setStageOverride(null);
      setCancelConfirming(false);
      setCancelReason('');
      setVersionDrawerOpen(false);
      setStatus({ tone: 'ok', message: `已打开草案 #${runId}。` });
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
    setSelectedContext({ type: 'draft_order', id: task.order_id, sourceStage: 'draft_review' });
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
      setSelectedContext({ type: 'draft_order', id: adjustment.order_id, sourceStage: 'draft_review' });
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
      setStageOverride(null);
      setSelectedContext(null);
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
      setSelectedContext(null);
      setQueueExpanded(true);
      setStageOverride(null);
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
    const runId = activePlan.run.run_id;
    const reason = cancelReason.trim() || '人工废弃草案';
    const applyCancelledDetail = async (detailData, preplansData = null) => {
      setActivePlan(detailData);
      setSelectedPlanOrderId('');
      setAdjustment(null);
      setSelectedContext(null);
      setCancelConfirming(false);
      setCancelReason('');
      if (preplansData) setPreplans(preplansData);
      setStageOverride(null);
      setStatus({ tone: 'ok', message: `草案 #${runId} 已废弃，订单状态未改变。` });
    };
    try {
      await cancelPreplan(runId, { reason });
      const [detail, preplansRes] = await Promise.all([
        getPreplan(runId),
        getPreplans(),
      ]);
      await applyCancelledDetail(detail.data, preplansRes.data || []);
    } catch (err) {
      try {
        const detail = await getPreplan(runId);
        if (detail.data?.run?.lifecycle_status === 'CANCELLED') {
          await applyCancelledDetail(detail.data);
          return;
        }
      } catch {
        // Keep the original error below so the user sees the operation that failed.
      }
      setStatus({ tone: 'error', message: formatError(err, '废弃草案失败。') });
    } finally {
      setBusy(false);
    }
  };

  const selectPlanOrder = (orderId) => {
    setSelectedPlanOrderId(orderId);
    setSelectedContext({ type: 'draft_order', id: orderId, sourceStage: 'draft_review' });
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
      const nextOrderId = nextRows[0]?.order_id || '';
      setSelectedPlanOrderId(nextOrderId);
      setSelectedContext(nextOrderId ? { type: 'draft_order', id: nextOrderId, sourceStage: 'draft_review' } : null);
    }
  };

  const selectWorkspaceView = (view) => {
    setWorkspaceView(view);
    setCancelConfirming(false);
    if (view === 'resource' && !selectedTask) {
      setSelectedPlanOrderId(planTasks[0]?.order_id || selectedPlanOrderId);
    }
  };

  const selectStage = (stage) => {
    const stageState = stageStates[stage];
    if (stageState?.locked) {
      setStatus({ tone: 'error', message: stageState.lockReason || '当前阶段尚未解锁。' });
      return;
    }
    setStageOverride(stage);
    setCancelConfirming(false);
    setAdjustment(null);
    setSelectedContext(null);
    if (stage === 'order_pool') {
      return;
    }
    if (stage === 'draft_review') {
      setWorkspaceView('orders');
      setQueueExpanded(false);
      return;
    }
    if (stage === 'validate_publish') {
      setQueueExpanded(false);
      return;
    }
    if (stage === 'manufacturing_queue') {
      setQueueExpanded(activeQueueSummary.total > 0);
    }
  };

  const refreshQueueAndOrders = async () => {
    const [queueRes, ordersRes] = await Promise.all([
      getManufacturingQueue(),
      loadPendingOrders(),
    ]);
    const nextOrders = ordersRes.items || [];
    const availableOrderIds = new Set(nextOrders.map(order => order.order_id));
    setQueue(queueRes.data || []);
    setOrders(nextOrders);
    setPendingOrderTotal(ordersRes.total || nextOrders.length);
    setSelected(prev => prev.filter(orderId => availableOrderIds.has(orderId)));
  };

  const submitQueueTransition = async (item, targetStatus, reason = '') => {
    const cleanReason = reason.trim();
    if (queueActionReasonRequired.has(targetStatus) && !cleanReason) {
      setStatus({ tone: 'error', message: '暂停或取消制造队列项必须填写原因。' });
      return;
    }
    setBusy(true);
    try {
      const res = await updateManufacturingQueueItem(item.id, {
        queue_status: targetStatus,
        reason: cleanReason,
      });
      await refreshQueueAndOrders();
      setQueueAction({ queueId: null, targetStatus: '', reason: '' });
      const label = queueStatusLabels[res.data.queue_status] || res.data.queue_status;
      setStatus({ tone: 'ok', message: `订单 ${item.order_id} 已更新为${label}。` });
    } catch (err) {
      setStatus({ tone: 'error', message: formatError(err, '更新制造队列失败。') });
    } finally {
      setBusy(false);
    }
  };

  const startQueueTransition = (item, targetStatus) => {
    setAdjustment(null);
    setCancelConfirming(false);
    if (queueActionReasonRequired.has(targetStatus)) {
      setQueueAction({ queueId: item.id, targetStatus, reason: '' });
      return;
    }
    submitQueueTransition(item, targetStatus);
  };

  const runPrimaryAction = () => {
    if (primaryAction.target === 'create') return handleCreatePreplan();
    if (primaryAction.target === 'validate') return handleValidate();
    if (primaryAction.target === 'confirm') return handleConfirm();
    if (primaryAction.target === 'queue') {
      setStageOverride('manufacturing_queue');
      setQueueExpanded(true);
      setSelectedContext(null);
      return null;
    }
    if (primaryAction.target === 'blockers') {
      setStageOverride('draft_review');
      setWorkspaceView('orders');
      setPlanOrderTab('needs_action');
      setSelectedContext(null);
      return null;
    }
    if (primaryAction.target === 'version') {
      setVersionDrawerOpen(true);
      return null;
    }
    if (primaryAction.target === 'orders') {
      setStageOverride('order_pool');
      setSelectedContext(null);
      return null;
    }
    return null;
  };

  const renderOrderPoolBrowser = (className = '') => (
    <div className={`workbench-order-pool-browser ${className}`.trim()} data-testid="workbench-order-pool-browser">
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
          <select value={screeningFilter} data-testid="workbench-filter-screening" onChange={event => setScreeningFilter(event.target.value)}>
            <option value="schedulable">可排订单池</option>
            <option value="stale">{'\u9700\u91cd\u65b0\u7b5b\u9009'}</option>
            <option value="blocked">异常/阻断订单</option>
            <option value="">全部初筛</option>
            {Object.entries(screeningLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <div className="workbench-select-actions">
          <button className="btn btn-ghost btn-small" type="button" disabled={!selectableFilteredOrderIds.length} data-testid="workbench-select-filtered" onClick={selectFilteredOrders}>
            全选当前筛选
          </button>
          <button className="btn btn-ghost btn-small" type="button" disabled={!selected.length} data-testid="workbench-clear-selected" onClick={clearSelectedOrders}>
            清空已选
          </button>
          <span>{selectedFilteredCount} 单已在当前筛选中</span>
        </div>
        {orderScreening.summary && (
          <div className="workbench-select-actions">
            <Badge tone="success">可排 {orderScreening.summary.ready_count}</Badge>
            <Badge tone="warning">风险 {orderScreening.summary.risk_count}</Badge>
            <Badge tone="danger">阻断 {orderScreening.summary.blocked_count}</Badge>
          </div>
        )}
        {orderScreening.error && <div className="config-status error">{orderScreening.error}</div>}
      </div>
      <div className="workbench-order-list">
        {pagedFilteredOrders.map(order => {
          const screening = screeningByOrderId.get(order.order_id);
          const selectable = isSelectableScreening(screening);
          return (
            <div
              key={order.order_id}
              role="button"
              tabIndex={0}
              className={`workbench-order ${selectedSet.has(order.order_id) ? 'selected' : ''} ${selectable ? '' : 'disabled'}`}
              data-testid={`workbench-pending-order-${testIdPart(order.order_id)}`}
              onClick={() => toggleOrder(order.order_id)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  toggleOrder(order.order_id);
                }
              }}
            >
              <div>
                <strong>{order.order_id}</strong>
                <span>{order.product_type}</span>
              </div>
              <small>{order.target_width}mm x {order.target_thickness}um · {order.total_quantity_kg}kg</small>
              <div className="workbench-order-meta">
                <Badge tone={order.order_class === 'URGENT' ? 'danger' : 'neutral'}>{orderClassLabels[order.order_class] || order.order_class}</Badge>
                {screening && <Badge tone={screeningTones[screening.screening_status] || 'neutral'}>{screeningLabels[screening.screening_status] || screening.screening_status}</Badge>}
                <span>{formatTime(order.due_date)}</span>
              </div>
              {screening && screening.screening_status !== 'ready' && <small>{screening.root_cause}</small>}
              {!!screening?.recommendations?.length && screening.screening_status !== 'ready' && (
                <div className="workbench-screening-actions">
                  <small className="workbench-screening-guidance">{screening.recommendations[0].guidance}</small>
                  <div>
                    {screening.recommendations.slice(0, 2).map(action => (
                      <a
                        key={action.action}
                        href={action.href}
                        data-testid={`workbench-screening-action-${testIdPart(order.order_id)}-${testIdPart(action.action)}`}
                        onClick={event => event.stopPropagation()}
                      >
                        {action.label}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {!orders.length && <div className="config-empty">当前没有待排订单。</div>}
        {orders.length > 0 && !filteredOrders.length && <div className="config-empty">当前筛选条件下没有待排订单。</div>}
      </div>
      <PaginationControls
        label="待排订单分页"
        page={orderPoolPage}
        total={filteredOrders.length}
        onPageChange={setOrderPoolPage}
        testIdBase="workbench-order-pool"
      />
    </div>
  );

  return (
    <div className={`workbench-page ${activePlan ? 'has-active-plan' : ''}`}>
      <div className="page-header">
        <div>
          <h2>排程工作台</h2>
          <p className="page-subtitle">系统生成预排程，人负责复核和必要调整；所有人工改动都会进入审计记录。</p>
        </div>
        <div className="page-toolbar">
          <button
            className="btn btn-ghost"
            type="button"
            aria-expanded={maintenanceOpen}
            data-testid="workbench-maintenance-toggle"
            onClick={() => setMaintenanceOpen(prev => !prev)}
          >
            高级维护
          </button>
        </div>
      </div>

      <section className="workbench-maintenance-panel" data-testid="workbench-maintenance-panel" hidden={!maintenanceOpen}>
        <div>
          <h3>高级维护</h3>
          <p>这些操作会影响正式排程或订单状态，只用于演示数据恢复和异常清理。</p>
        </div>
        <div className="config-actions">
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
        </div>
      </section>

      {status.message && <div className={`config-status ${status.tone === 'error' ? 'error' : 'ok'}`} data-testid="workbench-status">{status.message}</div>}

      <PolicySummary settings={settings} />

      <WorkflowStepper activeStage={activeStage} recommendedStage={recommendedStage} stageStates={stageStates} onStageChange={selectStage} />
      <ActiveDraftCommandBar
        activePlan={activePlan}
        counts={activePlan ? planOrderCounts : { input: selectableSelectedIds.length, scheduled: 0, schedulable: 0, blocked: 0, late: 0 }}
        versionState={draftVersionState}
        publishBlockReason={publishBlockReason}
        primaryAction={primaryAction}
        workbenchBusy={workbenchBusy}
        onPrimaryAction={runPrimaryAction}
        onOpenVersions={() => setVersionDrawerOpen(true)}
        onCancel={openCancelConfirm}
        onRefresh={() => loadAll(Boolean(activePlan))}
      />
      <DraftVersionDrawer
        open={versionDrawerOpen}
        filter={versionFilter}
        onFilterChange={setVersionFilter}
        activePlan={activePlan}
        preplans={preplans}
        onOpenPlan={openPlan}
        onClose={() => setVersionDrawerOpen(false)}
      />

      <div className="workbench-wizard" data-testid="workbench-wizard-shell">
        <section
          className="workbench-panel plan-board workbench-wizard-main"
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

          <div className="workbench-stage-canvas" data-testid="workbench-stage-canvas">
            {stageOverride && stageOverride !== recommendedStage && (
              <div className="workbench-stage-notice">
                当前查看“{workbenchStageLabels[activeStage]}”，系统推荐处理阶段是“{workbenchStageLabels[recommendedStage]}”。切换阶段只改变查看内容，不会修改草案状态。
              </div>
            )}

            {activeStage === 'order_pool' && (
              <section className="workbench-stage-panel workbench-order-pool-stage" data-testid="workbench-order-pool-stage">
                <div className="workbench-stage-head">
                  <div>
                    <h3>订单池</h3>
                    <p>选择待排订单后创建预排程草案。创建草案不会改变订单状态，只有发布后才进入制造队列。</p>
                  </div>
                  <button
                    className="btn btn-primary"
                    disabled={workbenchBusy || selectableSelectedIds.length === 0}
                    data-testid="workbench-create-preplan"
                    onClick={handleCreatePreplan}
                  >
                    {selectableSelectedIds.length ? `创建预排程 (${selectableSelectedIds.length})` : '先选择订单'}
                  </button>
                </div>
                <div className="workbench-plan-summary">
                  <div className="workbench-summary-item">
                    <span>待排订单</span>
                    <strong>{pendingOrderTotal}</strong>
                  </div>
                  <div className="workbench-summary-item">
                    <span>当前筛选</span>
                    <strong>{filteredOrders.length}</strong>
                  </div>
                  <div className="workbench-summary-item">
                    <span>已选择</span>
                    <strong>{selectableSelectedIds.length}</strong>
                  </div>
                  <div className="workbench-summary-item warning">
                    <span>初筛风险</span>
                    <strong>{orderScreening.summary?.risk_count || 0}</strong>
                  </div>
                  <div className="workbench-summary-item danger">
                    <span>初筛阻断</span>
                    <strong>{orderScreening.summary?.blocked_count || 0}</strong>
                  </div>
                </div>
                <div className="workbench-stage-body">
                  {renderOrderPoolBrowser('main')}
                </div>
              </section>
            )}

            {activeStage === 'draft_review' && (
              <section className="workbench-stage-panel" data-testid="workbench-draft-review-stage">
                <div className="workbench-stage-head">
                  <div>
                    <h3>草案复核</h3>
                    <p>{activePlan ? '优先处理未排、延期、阻断和可排未落位订单；资源视图作为吹膜机维度的辅助复核。' : '创建草案后显示订单复核和资源视图。'}</p>
                  </div>
                  {activePlan && <Badge tone={needsActionCount ? 'danger' : 'success'}>需处理 {needsActionCount}</Badge>}
                </div>
                {activePlan ? (
                  <>
                    <div className="workbench-workspace-head">
                      <div className="workbench-view-tabs">
                        <button type="button" className={workspaceView === 'orders' ? 'active' : ''} data-testid="workbench-draft-view-orders" onClick={() => selectWorkspaceView('orders')}>
                          订单复核
                        </button>
                        <button type="button" className={workspaceView === 'resource' ? 'active' : ''} data-testid="workbench-draft-view-resource" onClick={() => selectWorkspaceView('resource')}>
                          资源视图
                        </button>
                      </div>
                      <span>
                        {workspaceView === 'orders' && `当前分类：${activePlanOrderTab.label}`}
                        {workspaceView === 'resource' && '按吹膜机查看已落位任务'}
                      </span>
                    </div>
                    {workspaceView === 'orders' && (
                      <div className="workbench-order-review">
                  <div className="workbench-plan-tabs compact" aria-label="订单复核筛选">
                    {planOrderTabs.map(tab => (
                      <button
                        key={tab.key}
                        type="button"
                        className={`${planOrderTab === tab.key ? 'active' : ''} ${tab.tone || ''} ${tab.key === 'needs_action' ? 'primary' : ''}`.trim()}
                        data-testid={planOrderTabTestIds[tab.key]}
                        aria-current={planOrderTab === tab.key ? 'true' : undefined}
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
                        {pagedVisiblePlanOrderRows.map(row => (
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
                    <PaginationControls
                      label={`${activePlanOrderTab.label}分页`}
                      page={draftOrdersPage}
                      total={visiblePlanOrderRows.length}
                      onPageChange={setDraftOrdersPage}
                      testIdBase="workbench-draft-orders"
                    />
                  </div>
                </div>
                    )}
                    {workspaceView === 'resource' && (
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
                  <div className="workbench-empty">先从订单池选择订单并创建预排程草案。</div>
                )}
              </section>
            )}

            {activeStage === 'validate_publish' && (
              <section className="workbench-stage-panel" data-testid="workbench-validate-publish-stage">
                <div className="workbench-stage-head">
                  <div>
                    <h3>校验发布</h3>
                    <p>发布前集中查看校验结果、快照状态、发布阻断和进入制造队列的订单数量。</p>
                  </div>
                  {canConfirm ? (
                    <Badge tone="success">可发布</Badge>
                  ) : (
                    <div className="config-actions">
                      <button className="btn btn-primary" disabled data-testid="workbench-confirm-preplan">确认进入制造队列</button>
                    </div>
                  )}
                </div>
                <div className="workbench-publish-checklist" data-testid="workbench-publish-checklist">
                  {publishChecklist.map(item => (
                    <div key={item.key} className={`workbench-check-item ${item.status}`}>
                      <strong>{item.label}</strong>
                      <span>{item.detail}</span>
                    </div>
                  ))}
                </div>
                {activePlan ? (
                  <>
                    {publishBlockReason ? (
                      <div className="workbench-publish-hint">
                        <strong>发布受阻</strong>
                        <span>{publishBlockReason}</span>
                      </div>
                    ) : (
                      <div className="workbench-ok">当前草案满足发布条件，可确认进入制造队列。</div>
                    )}
                    <div className="validation-list stage-validation-list">
                      <h4>校验项</h4>
                      {sortedValidationItems.slice(0, 20).map((item, index) => (
                        <button
                          key={`${item.code}-${item.order_id}-${index}`}
                          type="button"
                          className={`validation-item ${item.severity}`}
                          data-testid={`workbench-validation-item-${index}`}
                          onClick={() => {
                            if (item.order_id) setSelectedPlanOrderId(item.order_id);
                            setSelectedContext({
                              type: 'validation_item',
                              id: `${item.code}-${item.order_id || 'global'}-${index}`,
                              sourceStage: 'validate_publish',
                              item,
                            });
                          }}
                        >
                          <strong>{item.severity === 'error' ? '阻断' : '警告'} · {validationCodeLabel(item.code)}</strong>
                          <span>{item.message}</span>
                        </button>
                      ))}
                      {validation && !validation.items.length && <div className="workbench-ok">当前草案无阻断错误。</div>}
                      {!validation && <div className="config-empty">请先校验方案，完成后才能确认进入制造队列。</div>}
                    </div>
                  </>
                ) : (
                  <div className="config-empty">尚未创建草案，无法校验发布。</div>
                )}
              </section>
            )}

            {activeStage === 'manufacturing_queue' && (
              <section className="workbench-stage-panel" data-testid="workbench-manufacturing-queue-stage">
                <div className="workbench-stage-head">
                  <div>
                    <h3>制造队列</h3>
                    <p>发布后的订单在这里推进备料、开工、完工、暂停或取消；暂停和取消必须记录原因。</p>
                  </div>
                  <Badge tone={activeQueueSummary.total ? 'success' : 'neutral'}>{activeQueueSummary.total} 项</Badge>
                </div>
                {activeQueueSummary.total > 0 ? (
                <section className={`queue-panel ${queueExpanded ? 'expanded' : 'collapsed'}`} data-testid="workbench-queue-panel">
                  <div className="workbench-panel-head">
                    <div>
                      <h3>制造队列</h3>
                      <span>{activeQueueSummary.total} 项{activePlan ? ` · 当前草案 #${activePlan.run.run_id}` : ''}</span>
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
                    <strong>{activeQueueSummary.total}</strong>
                    <span>{activeQueueSummary.total ? '已进入制造队列，按页查看队列项。' : '当前草案尚未进入制造队列。'}</span>
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
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pagedQueueRows.map(item => {
                            const actions = nextQueueActions(item.queue_status);
                            const activeQueueAction = queueAction.queueId === item.id ? queueAction : null;
                            const lastReason = item.last_transition?.details?.reason;
                            return (
                              <tr
                                key={item.id}
                                data-testid={`workbench-queue-row-${item.id}`}
                                onClick={() => setSelectedContext({ type: 'queue_item', id: item.id, sourceStage: 'manufacturing_queue', item })}
                              >
                                <td>{item.order_id}</td>
                                <td>{item.machine_id}</td>
                                <td>{formatTime(item.planned_start_time)} - {formatTime(item.planned_end_time)}</td>
                                <td><Badge tone={queueStatusTones[item.queue_status] || 'neutral'}>{queueStatusLabels[item.queue_status] || item.queue_status}</Badge></td>
                                <td>#{item.run_id}</td>
                                <td>
                                  <div className="queue-actions">
                                    {actions.map(targetStatus => (
                                      <button
                                        key={targetStatus}
                                        type="button"
                                        className={`btn ${targetStatus === 'CANCELLED' ? 'btn-danger' : 'btn-ghost'} btn-small`}
                                        disabled={workbenchBusy}
                                        data-testid={`workbench-queue-action-${item.id}-${targetStatus}`}
                                        onClick={event => {
                                          event.stopPropagation();
                                          startQueueTransition(item, targetStatus);
                                        }}
                                      >
                                        {queueActionLabels[targetStatus] || targetStatus}
                                      </button>
                                    ))}
                                    {!actions.length && <span className="queue-terminal">无需操作</span>}
                                  </div>
                                  {activeQueueAction && (
                                    <div className="queue-reason-editor">
                                      <textarea
                                        rows={2}
                                        value={activeQueueAction.reason}
                                        data-testid={`workbench-queue-reason-${item.id}`}
                                        placeholder={`${queueActionLabels[activeQueueAction.targetStatus]}原因`}
                                        onChange={event => setQueueAction(prev => ({ ...prev, reason: event.target.value }))}
                                      />
                                      <div>
                                        <button
                                          type="button"
                                          className="btn btn-primary btn-small"
                                          disabled={workbenchBusy}
                                          data-testid={`workbench-queue-submit-${item.id}`}
                                          onClick={event => {
                                            event.stopPropagation();
                                            submitQueueTransition(item, activeQueueAction.targetStatus, activeQueueAction.reason);
                                          }}
                                        >
                                          确认
                                        </button>
                                        <button
                                          type="button"
                                          className="btn btn-ghost btn-small"
                                          disabled={workbenchBusy}
                                          onClick={event => {
                                            event.stopPropagation();
                                            setQueueAction({ queueId: null, targetStatus: '', reason: '' });
                                          }}
                                        >
                                          取消
                                        </button>
                                      </div>
                                    </div>
                                  )}
                                  {lastReason && <small className="queue-last-reason">最近原因：{lastReason}</small>}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      {!activeQueueSummary.rows.length && <div className="config-empty">当前草案尚未进入制造队列。</div>}
                      <PaginationControls
                        label="制造队列分页"
                        page={queuePage}
                        total={activeQueueSummary.rows.length}
                        onPageChange={setQueuePage}
                        testIdBase="workbench-queue"
                      />
                    </div>
                  )}
                </section>
                ) : (
                  <div className="workbench-empty-state" data-testid="workbench-queue-empty-state">
                    <h4>当前草案尚未进入制造队列</h4>
                    <p>{activePlan ? '需要先完成草案校验，并确认进入制造队列后，才会生成可推进的队列项。' : '请先选择订单并创建预排程草案。'}</p>
                    <div className="config-actions">
                      <button type="button" className="btn btn-primary" data-testid="workbench-queue-empty-validate" onClick={() => setStageOverride(activePlan ? 'validate_publish' : 'order_pool')}>
                        {activePlan ? '返回校验发布' : '返回订单池'}
                      </button>
                      {publishBlockReason && <span>{publishBlockReason}</span>}
                    </div>
                  </div>
                )}
              </section>
            )}
          </div>
          <div className="workbench-stage-footer" data-testid="workbench-stage-footer">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={!previousStage || stageStates[previousStage.key]?.locked}
              data-testid="workbench-stage-previous"
              onClick={() => previousStage && selectStage(previousStage.key)}
            >
              上一步{previousStage ? `：${previousStage.label}` : ''}
            </button>
            <span>
              当前阶段：{workbenchStageLabels[activeStage]}
              {nextStage && stageStates[nextStage.key]?.locked ? ` · 下一步锁定：${stageStates[nextStage.key].lockReason}` : ''}
            </span>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={!nextStage || stageStates[nextStage.key]?.locked}
              title={nextStage ? stageStates[nextStage.key]?.lockReason || nextStage.description : ''}
              data-testid="workbench-stage-next"
              onClick={() => nextStage && selectStage(nextStage.key)}
            >
              下一步{nextStage ? `：${nextStage.label}` : ''}
            </button>
          </div>
        </section>
      </div>

      {selectedContext && (
        <>
        <button
          type="button"
          className="workbench-inspector-backdrop"
          aria-label="关闭复核抽屉"
          data-testid="workbench-inspector-backdrop"
          onClick={() => setSelectedContext(null)}
        />
        <aside className="workbench-panel review-panel workbench-inspector-drawer" data-testid="workbench-inspector-drawer">
          <div className="workbench-panel-head">
            <h3>{workbenchStageLabels[activeStage] || '草案校验与复核'}</h3>
            <div className="config-actions">
              {validation && (
                <Badge tone={validation.hard_error_count ? 'danger' : validation.warning_count ? 'warning' : 'success'}>
                  {validationStatusLabels[validation.status] || validation.status}
                </Badge>
              )}
              <button type="button" className="btn btn-ghost btn-small" data-testid="workbench-inspector-close" onClick={() => setSelectedContext(null)}>
                关闭
              </button>
            </div>
          </div>

          {selectedValidationItem && (
            <div className="selected-order-review" data-testid="workbench-validation-inspector">
              <h4>校验项证据</h4>
              <div className={`validation-item ${selectedValidationItem.severity}`}>
                <strong>{selectedValidationItem.severity === 'error' ? '阻断' : '警告'} · {validationCodeLabel(selectedValidationItem.code)}</strong>
                <span>{selectedValidationItem.message}</span>
                {selectedValidationItem.order_id && <small>关联订单：{selectedValidationItem.order_id}</small>}
              </div>
            </div>
          )}

          {selectedQueueItem && (
            <div className="selected-order-review" data-testid="workbench-queue-item-inspector">
              <h4>队列项详情</h4>
              <div className="selected-order-card">
                <div>
                  <strong>{selectedQueueItem.order_id}</strong>
                  <Badge tone={queueStatusTones[selectedQueueItem.queue_status] || 'neutral'}>
                    {queueStatusLabels[selectedQueueItem.queue_status] || selectedQueueItem.queue_status}
                  </Badge>
                </div>
                <span>{selectedQueueItem.machine_id} · #{selectedQueueItem.run_id}</span>
                <small>{formatTime(selectedQueueItem.planned_start_time)} - {formatTime(selectedQueueItem.planned_end_time)}</small>
                {selectedQueueItem.last_transition?.details?.reason && <small>最近原因：{selectedQueueItem.last_transition.details.reason}</small>}
              </div>
            </div>
          )}

          {activeStage === 'order_pool' && (
            <div className="selected-order-review" data-testid="workbench-order-pool-inspector">
              <h4>待排订单初筛</h4>
              {selectedPendingOrder ? (
                <div className="selected-order-card">
                  <div>
                    <strong>{selectedPendingOrder.order_id}</strong>
                    <Badge tone={screeningTones[selectedPendingScreening?.screening_status] || 'neutral'}>
                      {screeningLabels[selectedPendingScreening?.screening_status] || '未初筛'}
                    </Badge>
                  </div>
                  <span>{selectedPendingOrder.product_type || '-'}</span>
                  <small>{formatSpec(selectedPendingOrder)} · 交期 {formatTime(selectedPendingOrder.due_date)}</small>
                  {selectedPendingScreening?.root_cause && <small>{selectedPendingScreening.root_cause}</small>}
                  {!!selectedPendingScreening?.recommendations?.length && <small>{selectedPendingScreening.recommendations[0].guidance || selectedPendingScreening.recommendations[0].label}</small>}
                </div>
              ) : (
                <div className="config-empty">当前没有可复核的待排订单。</div>
              )}
            </div>
          )}

          {activeStage === 'validate_publish' && (
            <div className="selected-order-review" data-testid="workbench-publish-inspector">
              <h4>发布判断</h4>
              {activePlan ? (
                <div className="selected-order-card">
                  <div>
                    <strong>{canConfirm ? '可发布' : '不可发布'}</strong>
                    <Badge tone={canConfirm ? 'success' : 'warning'}>{validation ? validationStatusLabels[validation.status] || validation.status : '待校验'}</Badge>
                  </div>
                  <span>{publishBlockReason || '校验通过后可确认进入制造队列。'}</span>
                  <small>阻断 {validation?.hard_error_count || 0} · 警告 {validation?.warning_count || 0} · 队列 {activeQueueSummary.total}</small>
                </div>
              ) : (
                <div className="config-empty">创建草案后显示发布判断。</div>
              )}
            </div>
          )}

          {activeStage === 'manufacturing_queue' && (
            <div className="selected-order-review" data-testid="workbench-queue-inspector">
              <h4>队列状态</h4>
              <div className="selected-order-card">
                <div>
                  <strong>{activeQueueSummary.total} 项</strong>
                  <Badge tone={activeQueueSummary.total ? 'success' : 'neutral'}>当前草案</Badge>
                </div>
                <span>
                  已排队 {activeQueueSummary.counts.QUEUED || 0} ·
                  可开工 {activeQueueSummary.counts.READY || 0} ·
                  生产中 {activeQueueSummary.counts.IN_PRODUCTION || 0}
                </span>
                <small>
                  暂停 {activeQueueSummary.counts.ON_HOLD || 0} ·
                  完工 {activeQueueSummary.counts.COMPLETED || 0} ·
                  取消 {activeQueueSummary.counts.CANCELLED || 0}
                </small>
                {latestQueueTransition ? (
                  <small>
                    最近变更 {latestQueueTransition.order_id} ·
                    {formatTime(latestQueueTransition.last_transition.created_at)} ·
                    {latestQueueTransition.last_transition.details?.reason || '未填写原因'}
                  </small>
                ) : (
                  <small>发布后显示最近队列状态变更和原因。</small>
                )}
              </div>
            </div>
          )}

          {activeStage !== 'order_pool' && (
          <div className="selected-order-review" data-testid="workbench-draft-state-card">
            <h4>当前草案状态</h4>
            {activePlan ? (
              <div className="selected-order-card">
                <div>
                  <strong>#{activePlan.run.run_id}</strong>
                  <Badge tone={publishBlockReason ? 'warning' : 'success'}>
                    {publishBlockReason ? '发布受阻' : lifecycleLabels[activePlan.run.lifecycle_status] || activePlan.run.lifecycle_status}
                  </Badge>
                </div>
                <span>{draftVersionLabels[draftVersionState] || '尚无版本状态'}</span>
                <small>{publishBlockReason || '发布前仍以最近一次校验结果为准。'}</small>
              </div>
            ) : (
              <div className="config-empty">选择订单并创建草案后显示复核状态。</div>
            )}
          </div>
          )}

          {activeStage !== 'order_pool' && activePlan?.latest_publish_audit && (
            <div className="selected-order-review">
              <h4>发布审计</h4>
              <div className="selected-order-card">
                <div>
                  <strong>{auditEventLabels[activePlan.latest_publish_audit.event_type] || activePlan.latest_publish_audit.event_type}</strong>
                  <Badge tone="success">已记录</Badge>
                </div>
                <span>{activePlan.latest_publish_audit.actor || '-'} · {formatTime(activePlan.latest_publish_audit.created_at)}</span>
                <small>
                  订单 {activePlan.latest_publish_audit.selected_order_count} ·
                  队列 {activePlan.latest_publish_audit.queue_row_count} ·
                  警告 {activePlan.latest_publish_audit.warning_count}
                </small>
              </div>
            </div>
          )}

          {activeStage === 'draft_review' && (
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
                {selectedTask && (
                  <div className="setup-detail-card" data-testid="workbench-selected-setup-detail">
                    <strong>换产说明</strong>
                    <span>
                      前序 {selectedTask.prev_order_id || '机台初始状态'} ·
                      换产 {formatTime(selectedTask.setup_start_time)} - {formatTime(selectedTask.start_time)}
                    </span>
                    <small>{setupSummary(selectedTask)}</small>
                    {setupComponents(selectedTask).map((item, index) => (
                      <small key={`${item.category}-${index}`}>
                        {setupCategoryLabels[item.category] || item.category}：{item.minutes}分钟
                      </small>
                    ))}
                  </div>
                )}
                {selectedOrderValidation.map((item, index) => (
                  <div key={`${item.code}-${index}`} className={`validation-item ${item.severity}`}>
                    <strong>{item.severity === 'error' ? '阻断' : '警告'} · {validationCodeLabel(item.code)}</strong>
                    <span>{item.message}</span>
                  </div>
                ))}
                {selectedOrderGuidance && (
                  <div className="blocked-item">
                    <strong>处理建议：{selectedDiagnostic?.display_title || selectedDiagnostic?.entity_id || selectedPlanOrderId}</strong>
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
          )}

          {activeStage === 'draft_review' && adjustment && canAdjust && (
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
              <div className="workbench-context-note">
                人工调整提交后，草案需要重新校验后才能发布。
              </div>
              <div className="config-actions">
                <button className="btn btn-primary" data-testid="workbench-submit-adjustment" onClick={submitAdjustment} disabled={!canAdjust || workbenchBusy}>记录调整</button>
                <button className="btn btn-ghost" onClick={() => setAdjustment(null)}>取消</button>
              </div>
            </div>
          )}

          {['draft_review', 'validate_publish'].includes(activeStage) && (
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
                <strong>{item.severity === 'error' ? '阻断' : '警告'} · {validationCodeLabel(item.code)}</strong>
                <span>{item.message}</span>
              </div>
            ))}
            {validation && !validation.items.length && <div className="workbench-ok">当前草案无阻断错误。</div>}
            {!validation && <div className="config-empty">选择草案后显示校验结果。</div>}
          </div>
          )}

          {activeStage === 'draft_review' && activePlan && planOrderCounts.blocked > 0 && (
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

          {activeStage === 'draft_review' && (
          <div className="audit-list">
            <h4>调整记录</h4>
            {(activePlan?.adjustments || []).slice(0, 8).map(item => (
              <div key={item.id} className="audit-item">
                <strong>{item.order_id} · {adjustmentValidationStatusLabels[item.validation_status] || item.validation_status}</strong>
                <span>{item.reason_text || reasonOptions.find(([value]) => value === item.reason_code)?.[1] || item.reason_code}</span>
                <small>{item.changed_by} · {formatTime(item.changed_at)}</small>
              </div>
            ))}
            {activePlan && !activePlan.adjustments.length && <div className="config-empty">暂无人工调整。</div>}
          </div>
          )}
        </aside>
        </>
      )}

    </div>
  );
}
