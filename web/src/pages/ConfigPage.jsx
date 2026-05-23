import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  applyScheduleEndState,
  commitOrderImport,
  createOrder,
  createGmpRule,
  createMaintenanceWindow,
  createMaterialSwitchRule,
  createSpecRule,
  dedupeMaintenanceWindows,
  deleteGmpRule,
  deleteMaintenanceWindow,
  deleteMaterialSwitchRule,
  deleteSpecRule,
  getConfigAudit,
  getMachines,
  getOrderScreening,
  getOrders,
  getScheduleSettings,
  getRulesSummary,
  previewOrderImport,
  updateGmpRule,
  updateMachine,
  updateMaintenanceWindow,
  updateMaterialSwitchRule,
  updateOrder,
  updateScheduleSettings,
  updateSpecRule,
} from '../api/client';
import { Link, useSearchParams } from 'react-router-dom';

const tabs = [
  { id: 'policy', label: '策略' },
  { id: 'orders', label: '订单' },
  { id: 'machines', label: '机台' },
  { id: 'rules', label: '规则' },
];

const orderStatusOptions = ['PENDING', 'SCHEDULED', 'IN_PRODUCTION', 'COMPLETED', 'CANCELLED'];
const orderStatusLabels = {
  PENDING: '待排',
  SCHEDULED: '已排',
  IN_PRODUCTION: '生产中',
  COMPLETED: '已完成',
  CANCELLED: '已取消',
};
const machineStatusOptions = ['ACTIVE', 'MAINTENANCE', 'OFFLINE'];
const machineStatusLabels = {
  ACTIVE: '运行中',
  MAINTENANCE: '维护中',
  OFFLINE: '离线',
};
const cleanroomOptions = ['Class_10K', 'Class_100K'];
const cleanroomLabels = {
  Class_10K: '万级洁净',
  Class_100K: '十万级洁净',
};
const customerClassOptions = ['STANDARD', 'VIP'];
const customerClassLabels = {
  STANDARD: '标准客户',
  VIP: '重点客户',
};
const orderClassOptions = ['URGENT', 'NORMAL', 'SAMPLE'];
const orderClassLabels = {
  URGENT: '加急',
  NORMAL: '普通',
  SAMPLE: '样品',
  ANY: '任意',
  CONTINUOUS_RUN: '连续运行',
};
const orderRevisionReasonOptions = [
  ['CUSTOMER_CHANGE', '客户变更'],
  ['MATERIAL_UPDATE', '物料信息更新'],
  ['PLANNING_REVIEW', '计划复核修订'],
  ['DATA_CORRECTION', '数据修正'],
  ['E2E_CLEANUP', '测试清理'],
  ['OTHER', '其他'],
];
const maintenanceTypeOptions = ['ROUTINE', 'EMERGENCY', 'GMP_CLEANING', 'OVERHAUL'];
const maintenanceTypeLabels = {
  ROUTINE: '常规维护',
  EMERGENCY: '紧急维护',
  GMP_CLEANING: 'GMP 清洁',
  OVERHAUL: '大修',
};
const specAttributeOptions = ['Width_Up', 'Width_Down', 'Thickness', 'Die_Change', 'Corona', 'Core_Size'];
const specAttributeLabels = {
  Width_Up: '幅宽增加',
  Width_Down: '幅宽降低',
  Thickness: '厚度变化',
  Die_Change: '模头切换',
  Corona: '电晕',
  Core_Size: '纸芯尺寸',
};
const ruleSectionLabels = {
  material: '材料切换',
  gmp: 'GMP 清场',
  spec: '规格变更',
  maintenance: '维护窗口',
};
const ruleSectionIds = Object.keys(ruleSectionLabels);
const ruleSectionCountKeys = {
  material: 'material_switch',
  gmp: 'gmp_clearance',
  spec: 'spec_change',
  maintenance: 'maintenance',
};
const ruleColumnLabels = {
  from_material: '原材料',
  to_material: '目标材料',
  switch_time_mins: '切换时间(分钟)',
  scrap_weight_kg: '废料(kg)',
  description: '说明',
  from_order_class: '原订单类型',
  to_order_class: '目标订单类型',
  clearance_time_mins: '清场时间(分钟)',
  attribute: '属性',
  condition_desc: '条件',
  threshold_lower: '下限',
  threshold_upper: '上限',
  change_time_mins: '变更时间(分钟)',
  machine_id: '机台',
  start_time: '开始时间',
  end_time: '结束时间',
  maintenance_type: '维护类型',
  reason: '原因',
  is_recurring: '周期性',
  recurrence_rule: '周期规则',
  is_enabled: '状态',
  disabled_reason: '禁用原因',
};
const policySettingLabels = {
  review_required: '预排必须人工确认',
  manual_adjust_enabled: '允许人工调整',
  manual_adjust_reason_required: '人工调整原因必填',
  publish_with_warnings_allowed: '允许带警告发布',
  auto_release_enabled: '免复核时自动发布',
  material_constraint_enabled: '物料齐套约束',
  maintenance_constraint_enabled: '维护窗口约束',
  setup_rules_enabled: '换产规则约束',
  cleanroom_constraint_enabled: '洁净等级约束',
  machine_capability_constraint_enabled: '机台规格能力约束',
  due_date_optimization_enabled: '交期优化目标',
};
const policySettingDescriptions = {
  review_required: '开启后草案必须先校验，再发布到制造队列。',
  manual_adjust_enabled: '开启后复核员可以在草案中改机台或时间，并留下审计记录。',
  manual_adjust_reason_required: '开启后人工调整必须填写原因说明。',
  publish_with_warnings_allowed: '关闭后延期、人工调整等警告也会阻止发布。',
  auto_release_enabled: '仅在关闭人工确认时生效，适合稳定期自动入队。',
  material_constraint_enabled: '关闭后排程不等待物料齐套，仅用于临时模拟。',
  maintenance_constraint_enabled: '关闭后排程和校验不避让维护窗口。',
  setup_rules_enabled: '关闭后使用空换产矩阵，适合定位规则本身的影响。',
  cleanroom_constraint_enabled: '关闭后不按洁净等级筛选候选机台。',
  machine_capability_constraint_enabled: '关闭后放宽幅宽、厚度和层数边界，仅用于诊断。',
  due_date_optimization_enabled: '关闭后不以交期权重作为优先优化目标。',
};
const policyGroups = [
  {
    title: '发布与人工复核',
    keys: ['review_required', 'manual_adjust_enabled', 'manual_adjust_reason_required', 'publish_with_warnings_allowed', 'auto_release_enabled'],
  },
  {
    title: '排程约束与优化',
    keys: ['material_constraint_enabled', 'maintenance_constraint_enabled', 'setup_rules_enabled', 'cleanroom_constraint_enabled', 'machine_capability_constraint_enabled', 'due_date_optimization_enabled'],
  },
];
const highRiskPolicyKeys = [
  'maintenance_constraint_enabled',
  'cleanroom_constraint_enabled',
  'machine_capability_constraint_enabled',
];
const ruleStateFilterLabels = {
  all: '全部规则',
  enabled: '仅启用',
  disabled: '仅禁用',
};
const auditScopeLabels = {
  schedule_policy: '全局策略',
  rule: '规则',
};
const auditKeyLabels = {
  ...policySettingLabels,
  material_switch: '材料切换',
  gmp_clearance: 'GMP 清场',
  spec_change: '规格变更',
  maintenance: '维护窗口',
};
const diagnosticSeverityLabels = {
  critical: '关键',
  warning: '警告',
  info: '提示',
};
const screeningStatusLabels = {
  ready: '可排',
  risk: '风险',
  blocked: '阻断',
};
const screeningCodeLabels = {
  ready: '满足初筛',
  due_risk: '交期风险',
  status_not_pending: '状态不可排',
  missing_product: '产品未配置',
  missing_recipe: '配方未配置',
  no_eligible_machine: '无可用机台',
  material_not_ready: '物料未齐套',
};
const importRowStatusLabels = {
  new: '新增',
  conflict: '已存在',
  duplicate_input: '文件内重复',
  rejected: '拒绝',
};
const diagnosticEvidenceLabels = {
  target_width: '订单幅宽',
  target_thickness: '订单厚度',
  cleanroom_req: '洁净等级',
  recipe_layers: '配方层数',
  available_width_range: '可用幅宽范围',
  available_thickness_range: '可用厚度范围',
  max_machine_layers: '最大机台层数',
  tardiness_mins: '延期',
  setup_time_mins: '换产',
  assigned_machine: '排入机台',
  machine_blocker: '机台阻断',
};

function labelOptions(values, labels = {}) {
  return values.map(value => ({ value, label: labels[value] || value }));
}

function renderOption(option) {
  if (typeof option === 'object') return option;
  return { value: option, label: option };
}

const emptyRuleDraft = {
  material: { from_material: '', to_material: '', switch_time_mins: 120, scrap_weight_kg: 0, description: '', is_enabled: true, disabled_reason: '' },
  gmp: { from_order_class: 'ANY', to_order_class: 'NORMAL', clearance_time_mins: 0, description: '', is_enabled: true, disabled_reason: '' },
  spec: { attribute: 'Width_Up', condition_desc: '<= 50mm', threshold_lower: 0, threshold_upper: 50, change_time_mins: 30, scrap_weight_kg: 0, description: '', is_enabled: true, disabled_reason: '' },
  maintenance: { machine_id: '', start_time: '', end_time: '', maintenance_type: 'ROUTINE', reason: '', is_recurring: false, recurrence_rule: '', is_enabled: true, disabled_reason: '' },
};

function Field({ label, children }) {
  return (
    <label className="config-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function TextInput({ value, onChange, type = 'text', placeholder = '', testId }) {
  return <input type={type} value={value ?? ''} placeholder={placeholder} data-testid={testId} onChange={e => onChange(e.target.value)} />;
}

function NumberInput({ value, onChange, testId }) {
  return (
    <input
      type="number"
      value={value ?? ''}
      data-testid={testId}
      onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value))}
    />
  );
}

function SelectInput({ value, onChange, options, testId }) {
  return (
    <select value={value ?? ''} data-testid={testId} onChange={e => onChange(e.target.value)}>
      {options.map(option => {
        const item = renderOption(option);
        return <option key={item.value} value={item.value}>{item.label}</option>;
      })}
    </select>
  );
}

function SwitchInput({ checked, onChange, disabled = false, testId }) {
  return (
    <button
      type="button"
      className={`switch ${checked ? 'on' : ''}`}
      onClick={() => onChange(!checked)}
      aria-pressed={checked}
      disabled={disabled}
      data-testid={testId}
    >
      <span />
    </button>
  );
}

function StatusLine({ message, tone }) {
  if (!message) return null;
  return <div className={`config-status ${tone === 'error' ? 'error' : 'ok'}`}>{message}</div>;
}

function formatConfigTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-';
}

function formatAuditKey(key = '') {
  if (!key) return '配置项';
  return key
    .split(',')
    .map(item => auditKeyLabels[item] || item)
    .join('、');
}

function changedFieldCount(entry) {
  const before = entry.before_state || {};
  const after = entry.after_state || {};
  return new Set([...Object.keys(before), ...Object.keys(after)]).size;
}

function formatEvidence(item) {
  if (!item) return '';
  const label = diagnosticEvidenceLabels[item.metric] || item.metric;
  const actual = item.actual ?? '-';
  const unit = item.unit ? ` ${item.unit}` : '';
  return `${label}: ${actual}${unit}`;
}

function formatScreeningCode(code) {
  return screeningCodeLabels[code] || code || '初筛项';
}

function OrderDiagnosticPanel({ diagnostics, loading, error, generatedAt }) {
  if (loading) {
    return <div className="config-diagnostic-panel compact">正在计算当前订单初筛...</div>;
  }
  if (error) {
    return <div className="config-diagnostic-panel error">{error}</div>;
  }
  if (!diagnostics?.length) return null;

  const rank = { critical: 0, warning: 1, info: 2 };
  const visible = [...diagnostics].sort((a, b) => (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9)).slice(0, 4);

  return (
    <div className="config-diagnostic-panel">
      <div className="config-diagnostic-head">
        <div>
          <strong>当前订单初筛</strong>
          <span>当前计算结果{generatedAt ? ` · ${new Date(generatedAt).toLocaleString('zh-CN')}` : ''} · {diagnostics.length} 条</span>
        </div>
      </div>
      <div className="diagnostic-list compact">
        {visible.map(diagnostic => (
          <div key={diagnostic.id || `${diagnostic.entity_id}-${diagnostic.code}`} className={`diagnostic-row severity-${diagnostic.severity || 'info'}`}>
            <div>
              <span className="diagnostic-code">{formatScreeningCode(diagnostic.code)}</span>
              <strong>{diagnostic.display_title || diagnostic.entity_id}</strong>
              <span className="diagnostic-tag">{diagnosticSeverityLabels[diagnostic.severity] || diagnostic.severity || '提示'}</span>
            </div>
            <p>{diagnostic.root_cause}</p>
            {!!diagnostic.evidence?.length && (
              <div className="evidence-strip">
                {diagnostic.evidence.slice(0, 5).map(item => (
                  <span key={`${diagnostic.id}-${item.metric}-${item.actual}`}>{formatEvidence(item)}</span>
                ))}
              </div>
            )}
            {!!diagnostic.recommendations?.length && (
              <div className="diagnostic-actions">
                {diagnostic.recommendations.slice(0, 3).map(action => (
                  <Link key={`${diagnostic.id}-${action.action}`} to={action.href}>{action.label}</Link>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function buildOrderDraft(order) {
  return {
    product_type: order.product_type,
    target_width: order.target_width,
    target_thickness: order.target_thickness,
    total_quantity_kg: order.total_quantity_kg,
    cleanroom_req: order.cleanroom_req,
    order_class: order.order_class,
    corona_req: order.corona_req,
    core_size_inch: order.core_size_inch,
    due_date: toDatetimeLocal(order.due_date),
    material_available_time: toDatetimeLocal(order.material_available_time),
    status: order.status,
    priority_override: order.priority_override ?? '',
  };
}

function buildNewOrderDraft(sample) {
  return {
    order_id: '',
    product_type: sample?.product_type || '',
    customer_class: sample?.customer_class || 'STANDARD',
    target_width: sample?.target_width || 520,
    target_thickness: sample?.target_thickness || 35,
    total_quantity_kg: sample?.total_quantity_kg || 1200,
    cleanroom_req: cleanroomOptions.includes(sample?.cleanroom_req) ? sample.cleanroom_req : 'Class_100K',
    order_class: 'NORMAL',
    corona_req: false,
    core_size_inch: 3,
    due_date: '',
    material_available_time: '',
    priority_override: '',
    reason_text: '',
  };
}

function buildMachineDraft(machine) {
  return {
    name: machine.name,
    status: machine.status,
    cleanroom_level: machine.cleanroom_level,
    layer_structure: machine.layer_structure,
    die_diameter_mm: machine.die_diameter_mm,
    min_width: machine.min_width,
    max_width: machine.max_width,
    min_thickness: machine.min_thickness,
    max_thickness: machine.max_thickness,
    hourly_output_kg: machine.hourly_output_kg,
    max_slitting_lanes: machine.max_slitting_lanes,
    current_width: machine.current_width ?? 0,
    current_thickness: machine.current_thickness ?? 0,
    current_materials: (machine.current_materials || []).join(', '),
    current_corona: Boolean(machine.current_corona),
    current_core_size: machine.current_core_size ?? 3,
  };
}

function sameDraft(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function OrdersConfig({ orders, setOrders, onSaved, initialOrderId }) {
  const [selectedId, setSelectedId] = useState('');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [editorDirty, setEditorDirty] = useState(false);
  const [pendingOrderId, setPendingOrderId] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [importSourceName, setImportSourceName] = useState('UI import');
  const [importPreview, setImportPreview] = useState(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState(() => buildNewOrderDraft(orders[0]));
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState('');
  const [diagnosticState, setDiagnosticState] = useState({
    loading: false,
    error: '',
    generatedAt: '',
    items: [],
  });
  const selectedKey = selectedId || initialOrderId;
  const selected = useMemo(() => orders.find(o => o.order_id === selectedKey) || orders[0], [orders, selectedKey]);
  const filteredOrders = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return orders.filter(order => {
      if (statusFilter && order.status !== statusFilter) return false;
      if (!needle) return true;
      return [
        order.order_id,
        order.product_type,
        order.assigned_machine,
        order.status,
        order.cleanroom_req,
        order.order_class,
      ].some(value => String(value || '').toLowerCase().includes(needle));
    });
  }, [orders, query, statusFilter]);

  const requestSelect = useCallback((orderId) => {
    if (orderId === selected?.order_id) return;
    if (editorDirty && pendingOrderId !== orderId) {
      setPendingOrderId(orderId);
      return;
    }
    setEditorDirty(false);
    setPendingOrderId('');
    setSelectedId(orderId);
  }, [editorDirty, pendingOrderId, selected?.order_id]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(async () => {
      if (!selected?.order_id) {
        if (!cancelled) {
          setDiagnosticState({ loading: false, error: '', generatedAt: '', items: [] });
        }
        return;
      }

      if (!cancelled) {
        setDiagnosticState(prev => ({ ...prev, loading: true, error: '' }));
      }

      try {
        const res = await getOrderScreening(selected.order_id);
        if (cancelled) return;
        const item = res.data.item;
        setDiagnosticState({
          loading: false,
          error: '',
          generatedAt: res.data.generated_at,
          items: item ? [{
            id: `screening-${item.order_id}-${item.code}`,
            entity_id: item.order_id,
            display_title: `${item.order_id} · ${screeningStatusLabels[item.screening_status] || item.screening_status}`,
            severity: item.severity,
            code: item.code,
            root_cause: item.root_cause,
            evidence: item.evidence || [],
            recommendations: item.recommendations || [],
          }] : [],
        });
      } catch (err) {
        if (cancelled) return;
        setDiagnosticState({
          loading: false,
          error: err.response?.data?.detail || err.message || '无法读取订单初筛。',
          generatedAt: '',
          items: [],
        });
      }
    });

    return () => { cancelled = true; };
  }, [selected?.order_id]);

  if (!selected) return <div className="loading">暂无订单</div>;

  const previewImport = async () => {
    setImportBusy(true);
    setImportError('');
    try {
      const rows = parseOrderImportRows(importText);
      const res = await previewOrderImport({ rows, conflict_policy: 'reject_duplicates' });
      setImportPreview(res.data);
    } catch (err) {
      setImportPreview(null);
      setImportError(err.response?.data?.detail || err.message || '导入预览失败。');
    } finally {
      setImportBusy(false);
    }
  };

  const commitImport = async () => {
    setImportBusy(true);
    setImportError('');
    try {
      const rows = parseOrderImportRows(importText);
      const res = await commitOrderImport({
        rows,
        conflict_policy: 'reject_duplicates',
        source_name: importSourceName || 'UI import',
      });
      const nextOrders = await loadAllOrders();
      setOrders(nextOrders);
      setImportPreview(res.data);
      onSaved(`已导入 ${res.data.created_count} 条订单`);
    } catch (err) {
      setImportError(err.response?.data?.detail || err.message || '导入提交失败。');
    } finally {
      setImportBusy(false);
    }
  };

  const patchCreateDraft = (key, value) => {
    setCreateDraft(prev => ({ ...prev, [key]: value }));
    setCreateError('');
  };

  const toggleCreateOrder = () => {
    if (!createOpen && !createDraft.product_type) {
      setCreateDraft(buildNewOrderDraft(orders[0]));
    }
    setCreateOpen(prev => !prev);
    setCreateError('');
  };

  const submitCreateOrder = async () => {
    const required = [
      ['order_id', '订单号'],
      ['product_type', '产品类型'],
      ['target_width', '幅宽'],
      ['target_thickness', '厚度'],
      ['total_quantity_kg', '数量'],
      ['due_date', '交期'],
      ['reason_text', '创建原因'],
    ];
    const missing = required.find(([key]) => createDraft[key] === '' || createDraft[key] == null);
    if (missing) {
      setCreateError(`请填写${missing[1]}。`);
      return;
    }
    setCreateBusy(true);
    setCreateError('');
    try {
      const payload = {
        ...createDraft,
        order_id: createDraft.order_id.trim(),
        product_type: createDraft.product_type.trim(),
        customer_class: createDraft.customer_class || 'STANDARD',
        due_date: fromDatetimeLocal(createDraft.due_date),
        material_available_time: createDraft.material_available_time ? fromDatetimeLocal(createDraft.material_available_time) : null,
        priority_override: createDraft.priority_override === '' ? null : createDraft.priority_override,
        reason_code: 'ORDER_CREATE',
      };
      const res = await createOrder(payload);
      const nextOrders = await loadAllOrders();
      setOrders(nextOrders);
      setSelectedId(payload.order_id);
      setQuery(payload.order_id);
      setCreateOpen(false);
      setCreateDraft(buildNewOrderDraft(nextOrders[0]));
      onSaved(`订单 ${payload.order_id} 已创建，修订 #${res.data.revision_id}`);
    } catch (err) {
      setCreateError(err.response?.data?.detail || err.message || '创建订单失败。');
    } finally {
      setCreateBusy(false);
    }
  };

  return (
    <div className="config-grid">
      <div className="config-list">
        <div className="config-list-header">
          <TextInput value={query} onChange={setQuery} placeholder="搜索订单、产品、机台" />
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">全部状态</option>
            {orderStatusOptions.map(status => (
              <option key={status} value={status}>{orderStatusLabels[status] || status}</option>
            ))}
          </select>
          <small>{filteredOrders.length} / {orders.length} 条订单</small>
        </div>
        <button className="btn btn-ghost" type="button" onClick={() => setImportOpen(prev => !prev)}>
          {importOpen ? '收起导入' : '批量导入订单'}
        </button>
        <button className="btn btn-primary" type="button" data-testid="config-create-order-open" onClick={toggleCreateOrder}>
          {createOpen ? '收起新建' : '新建订单'}
        </button>
        {createOpen && (
          <div className="config-inline-confirm">
            <div>
              <strong>新建订单</strong>
              <span>用于临时插单或小批量补录。新订单默认进入待排状态。</span>
              <div className="config-form compact">
                <Field label="订单号"><TextInput value={createDraft.order_id} testId="config-order-create-id" onChange={v => patchCreateDraft('order_id', v)} /></Field>
                <Field label="产品类型"><TextInput value={createDraft.product_type} testId="config-order-create-product" onChange={v => patchCreateDraft('product_type', v)} /></Field>
                <Field label="客户等级"><SelectInput value={createDraft.customer_class} testId="config-order-create-customer" onChange={v => patchCreateDraft('customer_class', v)} options={labelOptions(customerClassOptions, customerClassLabels)} /></Field>
                <Field label="幅宽 mm"><NumberInput value={createDraft.target_width} testId="config-order-create-width" onChange={v => patchCreateDraft('target_width', v)} /></Field>
                <Field label="厚度 um"><NumberInput value={createDraft.target_thickness} testId="config-order-create-thickness" onChange={v => patchCreateDraft('target_thickness', v)} /></Field>
                <Field label="数量 kg"><NumberInput value={createDraft.total_quantity_kg} testId="config-order-create-quantity" onChange={v => patchCreateDraft('total_quantity_kg', v)} /></Field>
                <Field label="洁净等级"><SelectInput value={createDraft.cleanroom_req} testId="config-order-create-cleanroom" onChange={v => patchCreateDraft('cleanroom_req', v)} options={labelOptions(cleanroomOptions, cleanroomLabels)} /></Field>
                <Field label="订单类型"><SelectInput value={createDraft.order_class} testId="config-order-create-class" onChange={v => patchCreateDraft('order_class', v)} options={labelOptions(orderClassOptions, orderClassLabels)} /></Field>
                <Field label="交期"><TextInput type="datetime-local" value={createDraft.due_date} testId="config-order-create-due" onChange={v => patchCreateDraft('due_date', v)} /></Field>
                <Field label="材料可用时间"><TextInput type="datetime-local" value={createDraft.material_available_time} onChange={v => patchCreateDraft('material_available_time', v)} /></Field>
                <Field label="纸芯英寸"><NumberInput value={createDraft.core_size_inch} onChange={v => patchCreateDraft('core_size_inch', v)} /></Field>
                <Field label="电晕"><SwitchInput checked={Boolean(createDraft.corona_req)} onChange={v => patchCreateDraft('corona_req', v)} /></Field>
              </div>
              <Field label="创建原因">
                <textarea
                  rows={2}
                  value={createDraft.reason_text}
                  data-testid="config-order-create-reason"
                  onChange={event => patchCreateDraft('reason_text', event.target.value)}
                />
              </Field>
              {createError && <span className="config-status error">{createError}</span>}
            </div>
            <div className="config-actions">
              <button className="btn btn-primary" type="button" disabled={createBusy} data-testid="config-order-create-submit" onClick={submitCreateOrder}>
                {createBusy ? '创建中...' : '创建订单'}
              </button>
              <button className="btn btn-ghost" type="button" disabled={createBusy} onClick={() => setCreateOpen(false)}>取消</button>
            </div>
          </div>
        )}
        {importOpen && (
          <div className="config-inline-confirm">
            <div>
              <strong>导入订单</strong>
              <span>支持 CSV、TSV 或 JSON 数组。必须先预览，当前策略为拒绝重复订单。</span>
              <input
                type="file"
                accept=".csv,.tsv,.txt,.json"
                onChange={event => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  setImportSourceName(file.name);
                  file.text().then(setImportText).catch(() => setImportError('读取导入文件失败。'));
                }}
              />
              <textarea
                value={importText}
                rows={6}
                placeholder="order_id,product_type,target_width,target_thickness,total_quantity_kg,cleanroom_req,order_class,due_date"
                onChange={event => {
                  setImportText(event.target.value);
                  setImportPreview(null);
                }}
              />
              {importError && <span className="config-status error">{importError}</span>}
              {importPreview && (
                <div className="config-diagnostic-panel compact">
                  <strong>
                    新增 {importPreview.summary?.new_count || importPreview.created_count || 0}，
                    冲突 {importPreview.summary?.conflict_count || 0}，
                    文件重复 {importPreview.summary?.duplicate_input_count || 0}，
                    拒绝 {importPreview.summary?.rejected_count || 0}
                  </strong>
                  <div className="diagnostic-list compact">
                    {(importPreview.rows || []).slice(0, 8).map(row => (
                      <div key={`${row.row_index}-${row.order_id || 'row'}`} className={`diagnostic-row severity-${row.row_status === 'new' ? 'info' : 'warning'}`}>
                        <div>
                          <span className="diagnostic-code">第 {row.row_index} 行</span>
                          <strong>{row.order_id || '-'}</strong>
                        <span className="diagnostic-tag">{importRowStatusLabels[row.row_status] || row.row_status}</span>
                        </div>
                        {!!row.errors?.length && <p>{row.errors.join('；')}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="config-actions">
              <button className="btn btn-ghost" type="button" disabled={importBusy || !importText.trim()} onClick={previewImport}>
                {importBusy ? '处理中...' : '预览导入'}
              </button>
              <button className="btn btn-primary" type="button" disabled={importBusy || !importPreview?.summary?.new_count} onClick={commitImport}>
                提交新增订单
              </button>
            </div>
          </div>
        )}
        {pendingOrderId && editorDirty && (
          <InlineConfirm
            message={`当前订单有未保存修改，确认切换到 ${pendingOrderId}？`}
            detail="切换后未保存草稿会被丢弃。"
            confirmLabel="确认切换"
            onConfirm={() => requestSelect(pendingOrderId)}
            onCancel={() => setPendingOrderId('')}
          />
        )}
        {filteredOrders.map(order => (
          <button
            key={order.order_id}
            className={selected.order_id === order.order_id ? 'selected' : ''}
            data-testid={`config-order-item-${order.order_id}`}
            onClick={() => requestSelect(order.order_id)}
          >
            <strong>{order.order_id}</strong>
            <span>{order.product_type}</span>
            <small>{order.assigned_machine || orderStatusLabels[order.status] || order.status}</small>
          </button>
        ))}
        {!filteredOrders.length && <div className="config-empty">没有匹配的订单。</div>}
      </div>
      <OrderEditor
        key={selected.order_id}
        order={selected}
        setOrders={setOrders}
        onSaved={onSaved}
        onDirtyChange={setEditorDirty}
        diagnostics={diagnosticState.items}
        diagnosticsLoading={diagnosticState.loading}
        diagnosticsError={diagnosticState.error}
        diagnosticsGeneratedAt={diagnosticState.generatedAt}
      />
    </div>
  );
}

function OrderEditor({
  order,
  setOrders,
  onSaved,
  onDirtyChange,
  diagnostics,
  diagnosticsLoading,
  diagnosticsError,
  diagnosticsGeneratedAt,
}) {
  const baseDraft = useMemo(() => buildOrderDraft(order), [order]);
  const [draft, setDraft] = useState(() => buildOrderDraft(order));
  const [reasonCode, setReasonCode] = useState('DATA_CORRECTION');
  const [reasonText, setReasonText] = useState('');
  const [revisionResult, setRevisionResult] = useState(null);
  const isDirty = useMemo(() => !sameDraft(draft, baseDraft), [draft, baseDraft]);

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  const patch = (key, value) => setDraft(prev => ({ ...prev, [key]: value }));
  const save = async () => {
    if (isDirty && !reasonText.trim()) {
      onSaved('请填写订单修订原因。', 'error');
      return;
    }
    const payload = {
      ...draft,
      due_date: fromDatetimeLocal(draft.due_date),
      material_available_time: draft.material_available_time ? fromDatetimeLocal(draft.material_available_time) : null,
      priority_override: draft.priority_override === '' ? null : draft.priority_override,
      reason_code: reasonCode,
      reason_text: reasonText.trim(),
    };
    const res = await updateOrder(order.order_id, payload);
    const nextOrder = { ...order, ...payload };
    setOrders(prev => prev.map(o => o.order_id === order.order_id ? nextOrder : o));
    setDraft(buildOrderDraft(nextOrder));
    setRevisionResult(res.data);
    setReasonText('');
    onDirtyChange(false);
    onSaved(`订单 ${order.order_id} 已保存，修订 #${res.data.revision_id}`);
  };

  return (
    <div className="config-editor">
      <div className="config-editor-head">
        <div>
          <h3>{order.order_id}</h3>
          <p>{order.product_type}</p>
        </div>
        <button className="btn btn-primary" data-testid="config-order-save" onClick={save}>保存订单</button>
      </div>
      {revisionResult && (
        <div className="config-diagnostic-panel compact" data-testid="config-order-revision-summary">
          <strong>{revisionResult.revision_id ? `修订 #${revisionResult.revision_id}` : '无字段变化'}</strong>
          <span>
            {revisionResult.impacted_draft_run_ids?.length
              ? `影响草案：#${revisionResult.impacted_draft_run_ids.join(', #')}`
              : '无受影响草案'}
          </span>
        </div>
      )}
      <OrderDiagnosticPanel
        diagnostics={diagnostics}
        loading={diagnosticsLoading}
        error={diagnosticsError}
        generatedAt={diagnosticsGeneratedAt}
      />
      <div className="config-form">
        <Field label="产品类型"><TextInput value={draft.product_type} onChange={v => patch('product_type', v)} /></Field>
        <Field label="幅宽 mm"><NumberInput value={draft.target_width} testId="config-order-width" onChange={v => patch('target_width', v)} /></Field>
        <Field label="厚度 um"><NumberInput value={draft.target_thickness} onChange={v => patch('target_thickness', v)} /></Field>
        <Field label="数量 kg"><NumberInput value={draft.total_quantity_kg} onChange={v => patch('total_quantity_kg', v)} /></Field>
        <Field label="洁净等级"><SelectInput value={draft.cleanroom_req} onChange={v => patch('cleanroom_req', v)} options={labelOptions(cleanroomOptions, cleanroomLabels)} /></Field>
        <Field label="订单类型"><SelectInput value={draft.order_class} onChange={v => patch('order_class', v)} options={labelOptions(orderClassOptions, orderClassLabels)} /></Field>
        <Field label="状态"><SelectInput value={draft.status} onChange={v => patch('status', v)} options={labelOptions(orderStatusOptions, orderStatusLabels)} /></Field>
        <Field label="交期"><TextInput type="datetime-local" value={draft.due_date} onChange={v => patch('due_date', v)} /></Field>
        <Field label="材料可用时间"><TextInput type="datetime-local" value={draft.material_available_time} onChange={v => patch('material_available_time', v)} /></Field>
        <Field label="纸芯英寸"><NumberInput value={draft.core_size_inch} onChange={v => patch('core_size_inch', v)} /></Field>
        <Field label="延期权重覆盖"><NumberInput value={draft.priority_override} onChange={v => patch('priority_override', v)} /></Field>
        <Field label="电晕"><SwitchInput checked={Boolean(draft.corona_req)} onChange={v => patch('corona_req', v)} /></Field>
      </div>
      <div className="config-form compact">
        <Field label="修订原因分类">
          <SelectInput value={reasonCode} onChange={setReasonCode} options={orderRevisionReasonOptions.map(([value, label]) => ({ value, label }))} />
        </Field>
        <Field label="修订原因">
          <textarea
            rows={3}
            value={reasonText}
            data-testid="config-order-reason-text"
            placeholder="说明为什么修改订单字段"
            onChange={event => setReasonText(event.target.value)}
          />
        </Field>
      </div>
    </div>
  );
}

function MachinesConfig({ machines, setMachines, onSaved, initialMachineId }) {
  const [selectedId, setSelectedId] = useState('');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [cleanroomFilter, setCleanroomFilter] = useState('');
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyConfirming, setApplyConfirming] = useState(false);
  const [pendingMachineId, setPendingMachineId] = useState('');
  const selectedKey = selectedId || initialMachineId;
  const selected = useMemo(() => machines.find(m => m.machine_id === selectedKey) || machines[0], [machines, selectedKey]);
  const [draft, setDraft] = useState(null);
  const baseDraft = useMemo(() => selected ? buildMachineDraft(selected) : null, [selected]);
  const isDirty = useMemo(() => draft && baseDraft ? !sameDraft(draft, baseDraft) : false, [draft, baseDraft]);
  const filteredMachines = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return machines.filter(machine => {
      if (statusFilter && machine.status !== statusFilter) return false;
      if (cleanroomFilter && machine.cleanroom_level !== cleanroomFilter) return false;
      if (!needle) return true;
      return [
        machine.machine_id,
        machine.name,
        machine.status,
        machine.cleanroom_level,
        machine.last_order_id,
      ].some(value => String(value || '').toLowerCase().includes(needle));
    });
  }, [machines, query, statusFilter, cleanroomFilter]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!selected || cancelled) return;
      setDraft(buildMachineDraft(selected));
    });
    return () => { cancelled = true; };
  }, [selected]);

  if (!selected || !draft) return <div className="loading">暂无机台</div>;

  const requestSelect = (machineId) => {
    if (machineId === selected.machine_id) return;
    if (isDirty && pendingMachineId !== machineId) {
      setPendingMachineId(machineId);
      return;
    }
    setPendingMachineId('');
    setSelectedId(machineId);
  };

  const patch = (key, value) => setDraft(prev => ({ ...prev, [key]: value }));
  const save = async () => {
    const payload = {
      ...draft,
      current_materials: String(draft.current_materials || '').split(',').map(x => x.trim()).filter(Boolean),
    };
    await updateMachine(selected.machine_id, payload);
    const nextMachine = { ...selected, ...payload };
    setMachines(prev => prev.map(m => m.machine_id === selected.machine_id ? nextMachine : m));
    setDraft(buildMachineDraft(nextMachine));
    onSaved(`机台 ${selected.machine_id} 已保存`);
  };
  const applyEndState = async () => {
    if (!applyConfirming) {
      setApplyConfirming(true);
      return;
    }
    setApplyBusy(true);
    try {
      const res = await applyScheduleEndState();
      const machineRes = await getMachines();
      setMachines(machineRes.data);
      onSaved(`已应用运行 #${res.data.run_id} 的 ${res.data.applied_count} 台机台末态`);
      setApplyConfirming(false);
    } catch (err) {
      onSaved(err.response?.data?.detail || err.message || '应用排程末态失败', 'error');
    } finally {
      setApplyBusy(false);
    }
  };

  return (
    <div className="config-grid">
      <div className="config-list">
        <div className="config-list-header">
          <TextInput value={query} onChange={setQuery} placeholder="搜索机台、名称、最后工单" />
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">全部状态</option>
            {machineStatusOptions.map(status => <option key={status} value={status}>{machineStatusLabels[status] || status}</option>)}
          </select>
          <select value={cleanroomFilter} onChange={e => setCleanroomFilter(e.target.value)}>
            <option value="">全部洁净等级</option>
            {cleanroomOptions.map(level => <option key={level} value={level}>{cleanroomLabels[level] || level}</option>)}
          </select>
          <small>{filteredMachines.length} / {machines.length} 台机台</small>
        </div>
        {pendingMachineId && isDirty && (
          <InlineConfirm
            message={`当前机台有未保存修改，确认切换到 ${pendingMachineId}？`}
            detail="切换后未保存草稿会被丢弃。"
            confirmLabel="确认切换"
            onConfirm={() => requestSelect(pendingMachineId)}
            onCancel={() => setPendingMachineId('')}
          />
        )}
        {filteredMachines.map(machine => (
          <button key={machine.machine_id} className={selected.machine_id === machine.machine_id ? 'selected' : ''} onClick={() => requestSelect(machine.machine_id)}>
            <strong>{machine.machine_id}</strong>
            <span>{machine.name}</span>
            <small>{machineStatusLabels[machine.status] || machine.status} · {machine.min_width}-{machine.max_width}mm</small>
          </button>
        ))}
        {!filteredMachines.length && <div className="config-empty">没有匹配的机台。</div>}
      </div>
      <div className="config-editor">
        <div className="config-editor-head">
          <div>
            <h3>{selected.machine_id}</h3>
            <p>{selected.name}</p>
          </div>
          <div className="config-actions">
            <button className="btn btn-ghost" onClick={applyEndState} disabled={applyBusy}>
              {applyBusy ? '应用中...' : (applyConfirming ? '确认应用末态' : '应用排程末态')}
            </button>
            {applyConfirming && !applyBusy && (
              <button className="btn btn-ghost" onClick={() => setApplyConfirming(false)}>取消</button>
            )}
            <button className="btn btn-primary" onClick={save}>保存机台</button>
          </div>
        </div>
        <div className="config-form">
          <Field label="名称"><TextInput value={draft.name} onChange={v => patch('name', v)} /></Field>
          <Field label="状态"><SelectInput value={draft.status} onChange={v => patch('status', v)} options={labelOptions(machineStatusOptions, machineStatusLabels)} /></Field>
          <Field label="洁净等级"><SelectInput value={draft.cleanroom_level} onChange={v => patch('cleanroom_level', v)} options={labelOptions(cleanroomOptions, cleanroomLabels)} /></Field>
          <Field label="层数"><NumberInput value={draft.layer_structure} onChange={v => patch('layer_structure', v)} /></Field>
          <Field label="模头 mm"><NumberInput value={draft.die_diameter_mm} onChange={v => patch('die_diameter_mm', v)} /></Field>
          <Field label="最小幅宽"><NumberInput value={draft.min_width} onChange={v => patch('min_width', v)} /></Field>
          <Field label="最大幅宽"><NumberInput value={draft.max_width} onChange={v => patch('max_width', v)} /></Field>
          <Field label="最小厚度"><NumberInput value={draft.min_thickness} onChange={v => patch('min_thickness', v)} /></Field>
          <Field label="最大厚度"><NumberInput value={draft.max_thickness} onChange={v => patch('max_thickness', v)} /></Field>
          <Field label="时产 kg/h"><NumberInput value={draft.hourly_output_kg} onChange={v => patch('hourly_output_kg', v)} /></Field>
          <Field label="分切道数"><NumberInput value={draft.max_slitting_lanes} onChange={v => patch('max_slitting_lanes', v)} /></Field>
          <Field label="当前幅宽"><NumberInput value={draft.current_width} onChange={v => patch('current_width', v)} /></Field>
          <Field label="当前厚度"><NumberInput value={draft.current_thickness} onChange={v => patch('current_thickness', v)} /></Field>
          <Field label="当前电晕"><SwitchInput checked={Boolean(draft.current_corona)} onChange={v => patch('current_corona', v)} /></Field>
          <Field label="当前纸芯英寸"><NumberInput value={draft.current_core_size} onChange={v => patch('current_core_size', v)} /></Field>
          <Field label="当前挂料"><TextInput value={draft.current_materials} onChange={v => patch('current_materials', v)} /></Field>
        </div>
      </div>
    </div>
  );
}

function ConfigAuditPanel({ audit }) {
  const rows = Array.isArray(audit) ? audit.slice(0, 10) : [];

  return (
    <section className="config-audit-panel" data-testid="config-audit-panel">
      <div className="config-audit-head">
        <div>
          <h3>配置审计</h3>
          <p>记录全局策略和规则启停变更，解释排程结果为什么发生变化。</p>
        </div>
        <span>{rows.length} 条最近记录</span>
      </div>
      <div className="config-audit-list">
        {rows.map(entry => (
          <article key={entry.id} className="config-audit-item">
            <div>
              <strong>{entry.scope_label || auditScopeLabels[entry.config_scope] || entry.config_scope || '配置'}</strong>
              <span>{formatAuditKey(entry.config_key)} · {entry.changed_by || '系统'} · {formatConfigTime(entry.created_at)}</span>
            </div>
            <p>{entry.reason_text || '未填写原因'}</p>
            <small>{entry.entity_id || 'global'} · 影响字段 {changedFieldCount(entry)}</small>
          </article>
        ))}
        {!rows.length && (
          <div className="config-empty">暂无配置变更审计记录。</div>
        )}
      </div>
    </section>
  );
}

function PolicyConfig({ settings, rules, audit, onSettingsSaved, onAuditReload, onSaved }) {
  const [draftOverrides, setDraftOverrides] = useState({});
  const [changeReason, setChangeReason] = useState('');
  const [riskConfirmed, setRiskConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const draft = { ...(settings || {}), ...draftOverrides };
  const riskyDisabledKeys = highRiskPolicyKeys.filter(key => draft[key] === false && settings?.[key] !== false);
  const requiresRiskConfirm = riskyDisabledKeys.length > 0;

  const patch = (key, value) => {
    if (highRiskPolicyKeys.includes(key)) setRiskConfirmed(false);
    setDraftOverrides(prev => ({ ...prev, [key]: value }));
  };
  const cancelRiskChanges = () => {
    setRiskConfirmed(false);
    setDraftOverrides(prev => {
      const next = { ...prev };
      highRiskPolicyKeys.forEach(key => {
        if (settings?.[key] !== false) next[key] = true;
      });
      return next;
    });
  };

  const save = async () => {
    if (requiresRiskConfirm && !riskConfirmed) {
      onSaved('关闭关键约束前请先确认高风险变更。', 'error');
      return;
    }
    const reason = changeReason.trim();
    if (!reason) {
      onSaved('保存全局策略前请填写变更原因。', 'error');
      return;
    }
    setSaving(true);
    try {
      const payload = policyGroups
        .flatMap(group => group.keys)
        .reduce((acc, key) => ({ ...acc, [key]: draft[key] !== false }), { change_reason: reason });
      const res = await updateScheduleSettings(payload);
      onSettingsSaved(res.data);
      await onAuditReload?.();
      setDraftOverrides({});
      setChangeReason('');
      setRiskConfirmed(false);
      onSaved(`全局策略已保存，当前版本 #${res.data.policy_version}`);
    } catch (err) {
      onSaved(err.response?.data?.detail || err.message || '保存全局策略失败', 'error');
    } finally {
      setSaving(false);
    }
  };

  const stateCounts = rules.rule_state_counts || {};

  return (
    <div className="policy-page" data-testid="config-policy-page">
      <div className="policy-summary">
        <div>
          <h3>全局排程策略</h3>
          <p>版本 #{draft.policy_version || 1} · 最近更新 {draft.updated_by || '-'} · {formatConfigTime(draft.updated_at)}</p>
        </div>
        <div className="policy-rule-counts">
          {Object.entries(ruleSectionLabels).map(([key, label]) => (
            <span key={key}>
              {label}：启用 {stateCounts[ruleSectionCountKeys[key]]?.enabled ?? 0} / 禁用 {stateCounts[ruleSectionCountKeys[key]]?.disabled ?? 0}
            </span>
          ))}
        </div>
      </div>

      <div className="policy-groups">
        {policyGroups.map(group => (
          <section key={group.title} className="policy-group">
            <h4>{group.title}</h4>
            <div className="policy-switch-grid">
              {group.keys.map(key => (
                <label key={key} className="policy-switch">
                  <div>
                    <strong>{policySettingLabels[key]}</strong>
                    <span>{policySettingDescriptions[key]}</span>
                  </div>
                  <SwitchInput
                    checked={draft[key] !== false}
                    disabled={saving}
                    testId={`config-policy-${key}`}
                    onChange={value => patch(key, value)}
                  />
                </label>
              ))}
            </div>
          </section>
        ))}
      </div>

      {requiresRiskConfirm && (
        <InlineConfirm
          testId="config-policy-risk-confirm"
          message="关闭关键排程约束"
          detail={`${riskyDisabledKeys.map(key => policySettingLabels[key]).join('、')} 将只适合诊断或临时模拟，正式发布前需要重新预排和复核。`}
          confirmLabel={riskConfirmed ? '已确认' : '确认高风险变更'}
          onConfirm={() => setRiskConfirmed(true)}
          onCancel={cancelRiskChanges}
        />
      )}

      <div className="policy-save-bar">
        <Field label="变更原因">
          <textarea
            value={changeReason}
            data-testid="config-policy-change-reason"
            placeholder="说明为什么调整全局策略，便于草案快照和审计追踪。"
            onChange={event => setChangeReason(event.target.value)}
          />
        </Field>
        <button className="btn btn-primary" type="button" disabled={saving} data-testid="config-policy-save" onClick={save}>
          {saving ? '保存中...' : '保存全局策略'}
        </button>
      </div>
      <ConfigAuditPanel audit={audit} />
    </div>
  );
}

function RulesConfig({ rules, machines, settings, reload, onSaved, initialSection, onSectionChange }) {
  const [fallbackSection, setFallbackSection] = useState('material');
  const section = ruleSectionIds.includes(initialSection) ? initialSection : fallbackSection;
  const [draft, setDraft] = useState(emptyRuleDraft);
  const [dedupeBusy, setDedupeBusy] = useState(false);
  const [dedupeConfirming, setDedupeConfirming] = useState(false);
  const [pendingDeleteKey, setPendingDeleteKey] = useState('');
  const [stateFilter, setStateFilter] = useState('all');
  const duplicateSummary = rules.maintenance_duplicate_summary || { group_count: 0, duplicate_row_count: 0, groups: [] };
  const setupRuleCounts = rules.rule_state_counts || {};
  const allSetupRulesDisabled = ['material_switch', 'gmp_clearance', 'spec_change']
    .every(key => (setupRuleCounts[key]?.enabled ?? 0) === 0);
  const deleteKey = (kind, id) => `${kind}:${id}`;
  const filterRows = (rows = []) => rows.filter(row => {
    if (stateFilter === 'enabled') return row.is_enabled !== false;
    if (stateFilter === 'disabled') return row.is_enabled === false;
    return true;
  });

  const updateDraft = (group, key, value) => {
    setDraft(prev => ({ ...prev, [group]: { ...prev[group], [key]: value } }));
  };
  const selectSection = (nextSection) => {
    setFallbackSection(nextSection);
    setDedupeConfirming(false);
    setPendingDeleteKey('');
    onSectionChange?.(nextSection);
  };

  const saveInline = async (kind, id, payload) => {
    if (kind === 'material') await updateMaterialSwitchRule(id, payload);
    if (kind === 'gmp') await updateGmpRule(id, payload);
    if (kind === 'spec') await updateSpecRule(id, payload);
    if (kind === 'maintenance') await updateMaintenanceWindow(id, payload);
    await reload();
    onSaved('规则已保存');
  };

  const deleteRule = async (kind, id) => {
    const key = deleteKey(kind, id);
    if (pendingDeleteKey !== key) {
      setPendingDeleteKey(key);
      return;
    }
    if (kind === 'material') await deleteMaterialSwitchRule(id);
    if (kind === 'gmp') await deleteGmpRule(id);
    if (kind === 'spec') await deleteSpecRule(id);
    if (kind === 'maintenance') await deleteMaintenanceWindow(id);
    setPendingDeleteKey('');
    await reload();
    onSaved('规则已删除');
  };

  const createRule = async () => {
    if (section === 'material') await createMaterialSwitchRule(draft.material);
    if (section === 'gmp') await createGmpRule(draft.gmp);
    if (section === 'spec') await createSpecRule(draft.spec);
    if (section === 'maintenance') await createMaintenanceWindow(draft.maintenance);
    await reload();
    onSaved('规则已创建');
  };
  const dedupeMaintenance = async () => {
    if (!duplicateSummary.duplicate_row_count) return;
    if (!dedupeConfirming) {
      setDedupeConfirming(true);
      return;
    }
    setDedupeBusy(true);
    try {
      const res = await dedupeMaintenanceWindows();
      await reload();
      onSaved(`已合并 ${res.data.deleted_count} 条重复维护窗口`);
      setDedupeConfirming(false);
    } catch (err) {
      onSaved(err.response?.data?.detail || err.message || '合并维护窗口失败', 'error');
    } finally {
      setDedupeBusy(false);
    }
  };

  return (
    <div>
      <div className="config-tabbar secondary">
        {[
          ['material', ruleSectionLabels.material],
          ['gmp', ruleSectionLabels.gmp],
          ['spec', ruleSectionLabels.spec],
          ['maintenance', ruleSectionLabels.maintenance],
        ].map(([id, label]) => (
          <button key={id} className={section === id ? 'active' : ''} onClick={() => selectSection(id)}>{label}</button>
        ))}
      </div>
      <div className="rule-toolbar">
        <div>
          {rules.rule_state_counts && Object.entries(ruleSectionLabels).map(([key, label]) => {
            const counts = rules.rule_state_counts[ruleSectionCountKeys[key]] || { enabled: 0, disabled: 0 };
            return <span key={key}>{label}：启用 {counts.enabled} / 禁用 {counts.disabled}</span>;
          })}
        </div>
        <select value={stateFilter} data-testid="config-rule-state-filter" onChange={event => setStateFilter(event.target.value)}>
          {Object.entries(ruleStateFilterLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      <div className="config-policy-note" data-testid="config-rule-runtime-note">
        规则启停只影响新建预排程草案，历史草案保留创建时策略快照。
        {settings?.setup_rules_enabled !== false && allSetupRulesDisabled && (
          <strong> 当前物料、GMP、规格换产规则均未启用，新草案不应产生隐藏换产时间。</strong>
        )}
      </div>

      {section === 'material' && (
        <EditableRuleTable
          columns={['from_material', 'to_material', 'switch_time_mins', 'scrap_weight_kg', 'description']}
          rows={filterRows(rules.material_switch)}
          numeric={['switch_time_mins', 'scrap_weight_kg']}
          onSave={(id, payload) => saveInline('material', id, payload)}
          onDelete={id => deleteRule('material', id)}
          deleteConfirming={id => pendingDeleteKey === deleteKey('material', id)}
          onCancelDelete={() => setPendingDeleteKey('')}
        />
      )}
      {section === 'gmp' && (
        <EditableRuleTable
          columns={['from_order_class', 'to_order_class', 'clearance_time_mins', 'description']}
          rows={filterRows(rules.gmp_clearance)}
          numeric={['clearance_time_mins']}
          onSave={(id, payload) => saveInline('gmp', id, payload)}
          onDelete={id => deleteRule('gmp', id)}
          deleteConfirming={id => pendingDeleteKey === deleteKey('gmp', id)}
          onCancelDelete={() => setPendingDeleteKey('')}
        />
      )}
      {section === 'spec' && (
        <EditableRuleTable
          columns={['attribute', 'condition_desc', 'threshold_lower', 'threshold_upper', 'change_time_mins', 'scrap_weight_kg', 'description']}
          rows={filterRows(rules.spec_change)}
          numeric={['threshold_lower', 'threshold_upper', 'change_time_mins', 'scrap_weight_kg']}
          onSave={(id, payload) => saveInline('spec', id, payload)}
          onDelete={id => deleteRule('spec', id)}
          deleteConfirming={id => pendingDeleteKey === deleteKey('spec', id)}
          onCancelDelete={() => setPendingDeleteKey('')}
        />
      )}
      {section === 'maintenance' && (
        <>
          <MaintenanceDuplicatePanel
            summary={duplicateSummary}
            busy={dedupeBusy}
            confirming={dedupeConfirming}
            onDedupe={dedupeMaintenance}
            onCancel={() => setDedupeConfirming(false)}
          />
          <MaintenanceTable
            rows={filterRows(rules.maintenance)}
            machines={machines}
            onSave={(id, payload) => saveInline('maintenance', id, payload)}
            onDelete={id => deleteRule('maintenance', id)}
            deleteConfirming={id => pendingDeleteKey === deleteKey('maintenance', id)}
            onCancelDelete={() => setPendingDeleteKey('')}
          />
        </>
      )}

      <div className="config-create">
        <h3>新增{ruleSectionLabels[section]}</h3>
        <RuleDraftForm section={section} draft={draft} machines={machines} updateDraft={updateDraft} />
        <button className="btn btn-primary" onClick={createRule}>创建规则</button>
      </div>
    </div>
  );
}

function InlineConfirm({ message, detail, confirmLabel, onConfirm, onCancel, testId }) {
  return (
    <div className="config-inline-confirm" data-testid={testId}>
      <div>
        <strong>{message}</strong>
        {detail && <span>{detail}</span>}
      </div>
      <div className="config-actions">
        <button className="btn btn-danger" onClick={onConfirm}>{confirmLabel}</button>
        <button className="btn btn-ghost" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}

function EditableRuleTable({ columns, rows, numeric, onSave, onDelete, deleteConfirming, onCancelDelete }) {
  const [edits, setEdits] = useState({});
  const valueFor = (row, col) => edits[row.id]?.[col] ?? row[col] ?? '';
  const enabledFor = row => edits[row.id]?.is_enabled ?? row.is_enabled !== false;
  const patch = (id, col, value) => setEdits(prev => ({ ...prev, [id]: { ...prev[id], [col]: value } }));

  return (
    <div className="config-table-wrap">
      <table className="data-table config-table">
        <thead><tr>{columns.map(col => <th key={col}>{ruleColumnLabels[col] || col}</th>)}<th>{ruleColumnLabels.is_enabled}</th><th /></tr></thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.id} className={enabledFor(row) ? '' : 'disabled-rule'}>
              {columns.map(col => (
                <td key={col}>
                  <input
                    type={numeric.includes(col) ? 'number' : 'text'}
                    value={valueFor(row, col)}
                    onChange={e => patch(row.id, col, numeric.includes(col) ? Number(e.target.value) : e.target.value)}
                  />
                </td>
              ))}
              <td>
                <div className="rule-enable-cell">
                  <SwitchInput checked={enabledFor(row)} testId={`config-rule-${row.id}-enabled`} onChange={value => patch(row.id, 'is_enabled', value)} />
                  <span>{enabledFor(row) ? '启用' : '禁用'}</span>
                  {!enabledFor(row) && (
                    <input
                      value={valueFor(row, 'disabled_reason')}
                      placeholder="禁用原因"
                      data-testid={`config-rule-${row.id}-disabled-reason`}
                      onChange={event => patch(row.id, 'disabled_reason', event.target.value)}
                    />
                  )}
                </div>
              </td>
              <td>
                <div className="config-actions">
                  <button className="btn btn-ghost" data-testid={`config-rule-${row.id}-save`} onClick={() => onSave(row.id, edits[row.id] || {})}>保存</button>
                  <button className="btn btn-danger" onClick={() => onDelete(row.id)}>
                    {deleteConfirming?.(row.id) ? '确认删除' : '删除'}
                  </button>
                  {deleteConfirming?.(row.id) && (
                    <button className="btn btn-ghost" onClick={onCancelDelete}>取消</button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="config-empty">暂未配置规则。</div>}
    </div>
  );
}

function MaintenanceDuplicatePanel({ summary, busy, confirming, onDedupe, onCancel }) {
  if (!summary?.duplicate_row_count) return null;
  const examples = (summary.groups || []).slice(0, 3);

  return (
    <div className="config-maintenance-alert">
      <div>
        <strong>检测到 {summary.group_count} 组重复维护窗口</strong>
        <span>重复行 {summary.duplicate_row_count} 条，当前列表已临时去重显示。</span>
      </div>
      <div className="config-maintenance-alert-list">
        {examples.map(group => (
          <span key={`${group.keep_id}-${group.machine_id}`}>
            {group.machine_id} · {toDatetimeLocal(group.start_time)} · {group.duplicate_count} 条
          </span>
        ))}
      </div>
      <div className="config-actions">
        <button className="btn btn-danger" onClick={onDedupe} disabled={busy}>
          {busy ? '合并中...' : (confirming ? `确认合并 ${summary.duplicate_row_count} 条` : '一键合并重复窗口')}
        </button>
        {confirming && !busy && (
          <button className="btn btn-ghost" onClick={onCancel}>取消</button>
        )}
      </div>
    </div>
  );
}

function MaintenanceTable({ rows, machines, onSave, onDelete, deleteConfirming, onCancelDelete }) {
  const [edits, setEdits] = useState({});
  const valueFor = (row, col) => edits[row.id]?.[col] ?? row[col] ?? '';
  const enabledFor = row => edits[row.id]?.is_enabled ?? row.is_enabled !== false;
  const patch = (id, col, value) => setEdits(prev => ({ ...prev, [id]: { ...prev[id], [col]: value } }));

  return (
    <div className="config-table-wrap">
      <table className="data-table config-table">
        <thead>
          <tr>
            <th>{ruleColumnLabels.machine_id}</th>
            <th>{ruleColumnLabels.start_time}</th>
            <th>{ruleColumnLabels.end_time}</th>
            <th>{ruleColumnLabels.maintenance_type}</th>
            <th>{ruleColumnLabels.reason}</th>
            <th>{ruleColumnLabels.is_enabled}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.id} className={enabledFor(row) ? '' : 'disabled-rule'}>
              <td>{row.machine_id}</td>
              <td><input type="datetime-local" value={toDatetimeLocal(valueFor(row, 'start_time'))} onChange={e => patch(row.id, 'start_time', fromDatetimeLocal(e.target.value))} /></td>
              <td><input type="datetime-local" value={toDatetimeLocal(valueFor(row, 'end_time'))} onChange={e => patch(row.id, 'end_time', fromDatetimeLocal(e.target.value))} /></td>
              <td><SelectInput value={valueFor(row, 'maintenance_type')} onChange={v => patch(row.id, 'maintenance_type', v)} options={labelOptions(maintenanceTypeOptions, maintenanceTypeLabels)} /></td>
              <td><input value={valueFor(row, 'reason')} onChange={e => patch(row.id, 'reason', e.target.value)} /></td>
              <td>
                <div className="rule-enable-cell">
                  <SwitchInput checked={enabledFor(row)} testId={`config-maintenance-${row.id}-enabled`} onChange={value => patch(row.id, 'is_enabled', value)} />
                  <span>{enabledFor(row) ? '启用' : '禁用'}</span>
                  {!enabledFor(row) && (
                    <input
                      value={valueFor(row, 'disabled_reason')}
                      placeholder="禁用原因"
                      data-testid={`config-maintenance-${row.id}-disabled-reason`}
                      onChange={event => patch(row.id, 'disabled_reason', event.target.value)}
                    />
                  )}
                </div>
              </td>
              <td>
                <div className="config-actions">
                  <button className="btn btn-ghost" data-testid={`config-maintenance-${row.id}-save`} onClick={() => onSave(row.id, edits[row.id] || {})}>保存</button>
                  <button className="btn btn-danger" onClick={() => onDelete(row.id)}>
                    {deleteConfirming?.(row.id) ? '确认删除' : '删除'}
                  </button>
                  {deleteConfirming?.(row.id) && (
                    <button className="btn btn-ghost" onClick={onCancelDelete}>取消</button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="config-empty">暂未配置维护窗口。</div>}
      {!machines.length && <div className="config-empty">暂无可用于新增维护窗口的机台。</div>}
    </div>
  );
}

function RuleDraftForm({ section, draft, machines, updateDraft }) {
  if (section === 'material') return (
    <div className="config-form compact">
      <Field label="原材料"><TextInput value={draft.material.from_material} onChange={v => updateDraft('material', 'from_material', v)} /></Field>
      <Field label="目标材料"><TextInput value={draft.material.to_material} onChange={v => updateDraft('material', 'to_material', v)} /></Field>
      <Field label="切换分钟"><NumberInput value={draft.material.switch_time_mins} onChange={v => updateDraft('material', 'switch_time_mins', v)} /></Field>
      <Field label="废料 kg"><NumberInput value={draft.material.scrap_weight_kg} onChange={v => updateDraft('material', 'scrap_weight_kg', v)} /></Field>
      <Field label="说明"><TextInput value={draft.material.description} onChange={v => updateDraft('material', 'description', v)} /></Field>
      <Field label="启用"><SwitchInput checked={draft.material.is_enabled !== false} onChange={v => updateDraft('material', 'is_enabled', v)} /></Field>
      {draft.material.is_enabled === false && <Field label="禁用原因"><TextInput value={draft.material.disabled_reason} onChange={v => updateDraft('material', 'disabled_reason', v)} /></Field>}
    </div>
  );
  if (section === 'gmp') return (
    <div className="config-form compact">
      <Field label="原订单类型"><SelectInput value={draft.gmp.from_order_class} onChange={v => updateDraft('gmp', 'from_order_class', v)} options={labelOptions(['ANY', ...orderClassOptions, 'CONTINUOUS_RUN'], orderClassLabels)} /></Field>
      <Field label="目标订单类型"><SelectInput value={draft.gmp.to_order_class} onChange={v => updateDraft('gmp', 'to_order_class', v)} options={labelOptions(['ANY', ...orderClassOptions], orderClassLabels)} /></Field>
      <Field label="清场分钟"><NumberInput value={draft.gmp.clearance_time_mins} onChange={v => updateDraft('gmp', 'clearance_time_mins', v)} /></Field>
      <Field label="说明"><TextInput value={draft.gmp.description} onChange={v => updateDraft('gmp', 'description', v)} /></Field>
      <Field label="启用"><SwitchInput checked={draft.gmp.is_enabled !== false} onChange={v => updateDraft('gmp', 'is_enabled', v)} /></Field>
      {draft.gmp.is_enabled === false && <Field label="禁用原因"><TextInput value={draft.gmp.disabled_reason} onChange={v => updateDraft('gmp', 'disabled_reason', v)} /></Field>}
    </div>
  );
  if (section === 'spec') return (
    <div className="config-form compact">
      <Field label="属性"><SelectInput value={draft.spec.attribute} onChange={v => updateDraft('spec', 'attribute', v)} options={labelOptions(specAttributeOptions, specAttributeLabels)} /></Field>
      <Field label="条件"><TextInput value={draft.spec.condition_desc} onChange={v => updateDraft('spec', 'condition_desc', v)} /></Field>
      <Field label="下限"><NumberInput value={draft.spec.threshold_lower} onChange={v => updateDraft('spec', 'threshold_lower', v)} /></Field>
      <Field label="上限"><NumberInput value={draft.spec.threshold_upper} onChange={v => updateDraft('spec', 'threshold_upper', v)} /></Field>
      <Field label="变更分钟"><NumberInput value={draft.spec.change_time_mins} onChange={v => updateDraft('spec', 'change_time_mins', v)} /></Field>
      <Field label="废料 kg"><NumberInput value={draft.spec.scrap_weight_kg} onChange={v => updateDraft('spec', 'scrap_weight_kg', v)} /></Field>
      <Field label="说明"><TextInput value={draft.spec.description} onChange={v => updateDraft('spec', 'description', v)} /></Field>
      <Field label="启用"><SwitchInput checked={draft.spec.is_enabled !== false} onChange={v => updateDraft('spec', 'is_enabled', v)} /></Field>
      {draft.spec.is_enabled === false && <Field label="禁用原因"><TextInput value={draft.spec.disabled_reason} onChange={v => updateDraft('spec', 'disabled_reason', v)} /></Field>}
    </div>
  );
  return (
    <div className="config-form compact">
      <Field label="机台"><SelectInput value={draft.maintenance.machine_id} onChange={v => updateDraft('maintenance', 'machine_id', v)} options={[{ value: '', label: '请选择机台' }, ...machines.map(m => m.machine_id)]} /></Field>
      <Field label="开始时间"><TextInput type="datetime-local" value={toDatetimeLocal(draft.maintenance.start_time)} onChange={v => updateDraft('maintenance', 'start_time', fromDatetimeLocal(v))} /></Field>
      <Field label="结束时间"><TextInput type="datetime-local" value={toDatetimeLocal(draft.maintenance.end_time)} onChange={v => updateDraft('maintenance', 'end_time', fromDatetimeLocal(v))} /></Field>
      <Field label="维护类型"><SelectInput value={draft.maintenance.maintenance_type} onChange={v => updateDraft('maintenance', 'maintenance_type', v)} options={labelOptions(maintenanceTypeOptions, maintenanceTypeLabels)} /></Field>
      <Field label="原因"><TextInput value={draft.maintenance.reason} onChange={v => updateDraft('maintenance', 'reason', v)} /></Field>
      <Field label="启用"><SwitchInput checked={draft.maintenance.is_enabled !== false} onChange={v => updateDraft('maintenance', 'is_enabled', v)} /></Field>
      {draft.maintenance.is_enabled === false && <Field label="禁用原因"><TextInput value={draft.maintenance.disabled_reason} onChange={v => updateDraft('maintenance', 'disabled_reason', v)} /></Field>}
    </div>
  );
}

function toDatetimeLocal(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromDatetimeLocal(value) {
  if (!value) return null;
  return new Date(value).toISOString();
}

function parseDelimitedLine(line, delimiter) {
  const cells = [];
  let current = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];
    if (char === '"' && quoted && next === '"') {
      current += '"';
      index += 1;
      continue;
    }
    if (char === '"') {
      quoted = !quoted;
      continue;
    }
    if (char === delimiter && !quoted) {
      cells.push(current.trim());
      current = '';
      continue;
    }
    current += char;
  }
  cells.push(current.trim());
  return cells;
}

function parseOrderImportRows(text) {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith('[')) {
    const rows = JSON.parse(trimmed);
    if (!Array.isArray(rows)) throw new Error('JSON 导入内容必须是数组。');
    return rows;
  }
  const lines = trimmed.split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error('导入内容需要包含表头和至少一行订单。');
  const delimiter = lines[0].includes('\t') ? '\t' : ',';
  const headers = parseDelimitedLine(lines[0], delimiter);
  return lines.slice(1).map(line => {
    const values = parseDelimitedLine(line, delimiter);
    return headers.reduce((row, header, index) => {
      row[header] = values[index] ?? '';
      return row;
    }, {});
  });
}

async function loadAllOrders() {
  const pageSize = 500;
  let page = 1;
  const items = [];

  while (true) {
    const res = await getOrders({ page, size: pageSize });
    const nextItems = res.data.items || [];
    const total = res.data.total || nextItems.length;
    items.push(...nextItems);
    if (!nextItems.length || items.length >= total) break;
    page += 1;
  }

  return items;
}

export default function ConfigPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab');
  const activeFromParams = tabs.some(tab => tab.id === requestedTab) ? requestedTab : null;
  const initialOrderId = searchParams.get('order') || '';
  const initialMachineId = searchParams.get('machine') || '';
  const requestedRuleSection = searchParams.get('section') || '';
  const initialRuleSection = ruleSectionIds.includes(requestedRuleSection) ? requestedRuleSection : 'material';
  const [activeFallback, setActiveFallback] = useState('policy');
  const active = activeFromParams || activeFallback;
  const [orders, setOrders] = useState([]);
  const [machines, setMachines] = useState([]);
  const [rules, setRules] = useState(null);
  const [settings, setSettings] = useState(null);
  const [audit, setAudit] = useState([]);
  const [status, setStatus] = useState({ message: '', tone: 'ok' });

  const showSaved = (message, tone = 'ok') => setStatus({ message, tone });

  const loadAll = useCallback(async (options = {}) => {
    const [ordersRes, machinesRes, rulesRes, settingsRes, auditRes] = await Promise.all([
      loadAllOrders(),
      getMachines(),
      getRulesSummary(),
      getScheduleSettings(),
      getConfigAudit({ limit: 50 }),
    ]);
    if (options.isCancelled?.()) return;
    setOrders(ordersRes);
    setMachines(machinesRes.data);
    setRules(rulesRes.data);
    setSettings(settingsRes.data);
    setAudit(auditRes.data || []);
  }, [setAudit, setMachines, setOrders, setRules, setSettings]);

  const reloadAudit = useCallback(async () => {
    const auditRes = await getConfigAudit({ limit: 50 });
    setAudit(auditRes.data || []);
  }, [setAudit]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(async () => {
      try {
        await loadAll({ isCancelled: () => cancelled });
      } catch (err) {
        if (!cancelled) {
          setStatus({ message: err.response?.data?.detail || err.message, tone: 'error' });
        }
      }
    });
    return () => { cancelled = true; };
  }, [loadAll]);

  if (!rules || !settings) return <div className="loading">配置加载中...</div>;

  return (
    <div>
      <div className="page-header">
        <h2>配置中心</h2>
        <button className="btn btn-ghost" onClick={loadAll}>刷新</button>
      </div>
      <div className="config-tabbar">
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={active === tab.id ? 'active' : ''}
            onClick={() => {
              setActiveFallback(tab.id);
              setSearchParams(tab.id === 'rules' ? { tab: tab.id, section: initialRuleSection } : { tab: tab.id });
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <StatusLine message={status.message} tone={status.tone} />
      {active === 'policy' && (
        <PolicyConfig
          settings={settings}
          rules={rules}
          audit={audit}
          onSettingsSaved={setSettings}
          onAuditReload={reloadAudit}
          onSaved={showSaved}
        />
      )}
      {active === 'orders' && <OrdersConfig orders={orders} setOrders={setOrders} onSaved={showSaved} initialOrderId={initialOrderId} />}
      {active === 'machines' && <MachinesConfig machines={machines} setMachines={setMachines} onSaved={showSaved} initialMachineId={initialMachineId} />}
      {active === 'rules' && (
        <RulesConfig
          rules={rules}
          machines={machines}
          settings={settings}
          reload={loadAll}
          onSaved={showSaved}
          initialSection={initialRuleSection}
          onSectionChange={section => setSearchParams({ tab: 'rules', section })}
        />
      )}
    </div>
  );
}
