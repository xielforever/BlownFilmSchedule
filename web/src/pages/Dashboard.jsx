import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import * as echarts from 'echarts';
import { getDashboard, getGantt, getScheduleDiagnostics, getScheduleStatus } from '../api/client';
import { dashboardDeferredReasonCards, dashboardOrderBucketCards } from './dashboardViewModel';

const ORDER_CLASS_COLORS = {
  URGENT: '#ef4444',
  NORMAL: '#3b82f6',
  SAMPLE: '#f59e0b',
};

const ORDER_CLASS_LABELS = {
  URGENT: '加急',
  NORMAL: '普通',
  SAMPLE: '样品',
};

const DIAGNOSTIC_CATEGORY_LABELS = {
  eligibility: '可排性',
  lateness: '延期',
  material: '物料',
  validation: '校验',
  unknown: '未知',
};

const SCHEDULE_STATE_LABELS = {
  idle: '空闲',
  running: '运行中',
  succeeded: '成功',
  failed: '失败',
  PARTIAL: '部分排程',
  OPTIMAL: '最优',
  FEASIBLE: '可行',
};

function formatGanttTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-';
}

function formatGanttDuration(minutes) {
  if (!minutes && minutes !== 0) return '-';
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins ? `${hours} 小时 ${mins} 分钟` : `${hours} 小时`;
}

function formatActor(value) {
  if (!value) return '-';
  return value === 'system' ? '系统' : value;
}

function formatRunStatus(value) {
  if (!value) return '-';
  return SCHEDULE_STATE_LABELS[value] || value;
}

function formatScheduleMessage(message) {
  const messages = {
    'Schedule job status': '排程任务状态',
    'Schedule failed.': '排程失败。',
    'Schedule succeeded.': '排程成功。',
    'Schedule completed.': '排程完成。',
  };
  return messages[message] || message || '排程任务状态';
}

function getGanttMachineIds(ganttData) {
  if (!ganttData) return [];
  const configured = (ganttData.machines || []).map(machine => machine.machine_id);
  const eventMachines = [
    ...(ganttData.tasks || []),
    ...(ganttData.maintenance || []),
    ...(ganttData.downtime || []),
    ...(ganttData.idle || []),
  ].map(item => item.machine_id);
  return [...new Set([...configured, ...eventMachines].filter(Boolean))].sort();
}

function buildHatchPattern(borderColor = '#475569') {
  const patternCanvas = document.createElement('canvas');
  patternCanvas.width = 10;
  patternCanvas.height = 10;
  const ctx = patternCanvas.getContext('2d');
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, 10, 10);
  ctx.strokeStyle = borderColor;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, 10);
  ctx.lineTo(10, 0);
  ctx.stroke();
  return { image: patternCanvas, repeat: 'repeat' };
}

function renderDashboardGanttTooltip(params) {
  const d = params.value[3];
  const start = new Date(params.value[1]).toLocaleString('zh-CN');
  const end = new Date(params.value[2]).toLocaleString('zh-CN');

  if (d.kind === 'idle') {
    return `<b>空档</b><br/>${d.reason || '空档区间'}<br/>持续时间：${formatGanttDuration(d.duration_mins)}<br/>${start} ~ ${end}` +
      (d.guidance ? `<br/><span style="color:#bfdbfe">${d.guidance}</span>` : '');
  }
  if (d.kind === 'setup') {
    return `<b>${d.order_id} 换产</b><br/>持续时间：${formatGanttDuration(d.setup_mins)}<br/>${start} ~ ${end}`;
  }
  if (d.kind === 'maintenance') {
    return `<b>维护</b><br/>${d.type || '计划维护'}${d.reason ? ` - ${d.reason}` : ''}<br/>持续时间：${formatGanttDuration(d.duration_mins)}<br/>${start} ~ ${end}` +
      (d.guidance ? `<br/><span style="color:#bfdbfe">${d.guidance}</span>` : '');
  }
  if (d.kind === 'downtime') {
    return `<b>停机</b><br/>${d.type || '事件'}${d.cause ? ` - ${d.cause}` : ''}<br/>级别：${d.severity || '-'}<br/>持续时间：${formatGanttDuration(d.duration_mins)}<br/>${start} ~ ${end}` +
      (d.guidance ? `<br/><span style="color:#bfdbfe">${d.guidance}</span>` : '');
  }

  return `<b>${d.order_id}</b><br/>${d.product_type || '生产'}<br/>` +
    `${d.target_width}mm x ${d.target_thickness}um<br/>` +
    `换产：${formatGanttDuration(d.setup_mins)} | 废料：${d.scrap_kg} kg<br/>` +
    `${start} ~ ${end}` +
    (d.is_late ? `<br/><span style="color:#ef4444">延期 ${formatGanttDuration(d.tardiness_mins)}</span>` : '') +
    (d.guidance ? `<br/><span style="color:#bfdbfe">${d.guidance}</span>` : '');
}

function KpiCard({ label, value, valueColor }) {
  return (
    <div className="kpi-card fade-in" style={{ padding: '28px 32px' }}>
      <div className="kpi-label" style={{ marginBottom: '16px', fontSize: '15px', color: '#cbd5e1' }}>{label}</div>
      <div className="kpi-value" style={{ 
        color: valueColor || '#fff', 
        fontSize: '42px', 
        margin: 0,
        background: 'none',
        WebkitTextFillColor: valueColor || '#fff' 
      }}>
        {value}
      </div>
    </div>
  );
}

function DashboardGanttChart({ ganttData }) {
  const ref = useRef(null);
  const machineIds = useMemo(() => getGanttMachineIds(ganttData), [ganttData]);
  
  useEffect(() => {
    if (!ref.current || !ganttData || !machineIds.length) return undefined;
    const chart = echarts.init(ref.current, 'dark');
    const setupPattern = buildHatchPattern('#475569');
    const maintenancePattern = buildHatchPattern('#ef4444');

    const renderItem = (params, api) => {
      const categoryIndex = api.value(0);
      const start = api.coord([api.value(1), categoryIndex]);
      const end = api.coord([api.value(2), categoryIndex]);
      const width = Math.max(end[0] - start[0], 0);
      const d = api.value(3);
      const height = api.size([0, 1])[1] * (d.kind === 'idle' ? 0.34 : 0.62);
      const style = api.style();
      
      if (d.kind === 'production' && width > 40) {
         style.text = d.order_id;
         style.textFill = '#ffffff';
         style.fontSize = 10;
         style.width = width - 8;
         style.overflow = 'truncate';
      }

      const rectShape = echarts.graphic.clipRectByRect({
        x: start[0], y: start[1] - height / 2, width: width, height: height
      }, {
        x: params.coordSys.x, y: params.coordSys.y,
        width: params.coordSys.width, height: params.coordSys.height
      });

      return rectShape && {
        type: 'rect',
        transition: ['shape'],
        shape: { ...rectShape, r: Math.min(2, rectShape.width / 2) },
        style: style
      };
    };

    const productionByClass = {};
    const setupData = [];

    (ganttData.tasks || []).forEach(t => {
      const machineIndex = machineIds.indexOf(t.machine_id);
      if (machineIndex < 0) return;
      const startTime = new Date(t.start).getTime();
      const endTime = new Date(t.end).getTime();
      const className = t.order_class || 'NORMAL';
      
      if (t.setup_mins > 0 && t.setup_start) {
        const setupStartTime = new Date(t.setup_start).getTime();
        setupData.push({
          name: t.order_id + ' (换产)',
          value: [machineIndex, setupStartTime, startTime, { ...t, kind: 'setup' }],
          itemStyle: { color: setupPattern, borderColor: '#475569', borderWidth: 1 }
        });
      }

      if (!productionByClass[className]) productionByClass[className] = [];
      productionByClass[className].push({
        name: t.order_id,
        value: [machineIndex, startTime, endTime, { ...t, kind: 'production' }],
        itemStyle: { color: ORDER_CLASS_COLORS[className] || '#64748b' }
      });
    });

    const idleData = (ganttData.idle || []).map(item => {
      const machineIndex = machineIds.indexOf(item.machine_id);
      if (machineIndex < 0) return null;
      return {
        name: item.reason || '空档',
        value: [machineIndex, new Date(item.start).getTime(), new Date(item.end).getTime(), { ...item, kind: 'idle' }],
        itemStyle: { color: 'rgba(148, 163, 184, 0.24)', borderColor: 'rgba(148, 163, 184, 0.42)', borderWidth: 1 },
      };
    }).filter(Boolean);

    const maintenanceData = (ganttData.maintenance || []).map(item => {
      const machineIndex = machineIds.indexOf(item.machine_id);
      if (machineIndex < 0) return null;
      return {
        name: item.reason || '维护',
        value: [machineIndex, new Date(item.start).getTime(), new Date(item.end).getTime(), { ...item, kind: 'maintenance' }],
        itemStyle: { color: maintenancePattern, borderColor: '#ef4444', borderWidth: 1 },
      };
    }).filter(Boolean);

    const downtimeData = (ganttData.downtime || []).map(item => {
      const machineIndex = machineIds.indexOf(item.machine_id);
      if (machineIndex < 0) return null;
      return {
        name: item.type || '停机',
        value: [machineIndex, new Date(item.start).getTime(), new Date(item.end).getTime(), { ...item, kind: 'downtime' }],
        itemStyle: { color: 'rgba(239, 68, 68, 0.58)', borderColor: '#fca5a5', borderWidth: 1 },
      };
    }).filter(Boolean);

    const series = [
      {
        type: 'custom',
        name: '空档',
        z: 1,
        renderItem,
        encode: { x: [1, 2], y: 0 },
        data: idleData,
        emphasis: { disabled: true },
      },
      {
        type: 'custom',
        name: '停机',
        z: 3,
        renderItem,
        encode: { x: [1, 2], y: 0 },
        data: downtimeData,
      },
      {
        type: 'custom',
        name: '维护',
        z: 4,
        renderItem,
        encode: { x: [1, 2], y: 0 },
        data: maintenanceData,
      },
      {
        type: 'custom',
        name: '换产',
        z: 5,
        renderItem,
        encode: { x: [1, 2], y: 0 },
        data: setupData,
      },
      ...Object.keys(productionByClass).sort().map(className => ({
        type: 'custom',
        name: ORDER_CLASS_LABELS[className] || className,
        z: 6,
        renderItem,
        encode: { x: [1, 2], y: 0 },
        data: productionByClass[className],
        emphasis: { disabled: true },
      })),
    ];

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { formatter: renderDashboardGanttTooltip },
      legend: {
        top: 0,
        left: 0,
        textStyle: { color: '#cbd5e1', fontSize: 12 },
        itemWidth: 14,
        itemHeight: 14,
        icon: 'roundRect',
        type: 'scroll',
      },
      grid: { top: 58, right: 40, bottom: 48, left: 92 },
      xAxis: {
        type: 'time',
        min: ganttData.horizon?.start ? new Date(ganttData.horizon.start).getTime() : undefined,
        max: ganttData.horizon?.end ? new Date(ganttData.horizon.end).getTime() : undefined,
        splitLine: { show: true, lineStyle: { color: '#334155', type: 'dashed', opacity: 0.18 } },
        axisLabel: { color: '#94a3b8', fontSize: 11 }
      },
      yAxis: {
        type: 'category',
        data: machineIds,
        inverse: true,
        splitLine: { show: true, lineStyle: { color: '#334155', opacity: 0.14 } },
        axisLabel: { color: '#f1f5f9', fontWeight: 600, fontSize: 11 }
      },
      dataZoom: [
        { type: 'slider', xAxisIndex: 0, bottom: 2, height: 18, borderColor: '#334155', backgroundColor: '#1e293b', fillerColor: 'rgba(59,130,246,0.15)', textStyle: { color: '#94a3b8' }, showDetail: false, filterMode: 'weakFilter' },
        { type: 'inside', xAxisIndex: 0, filterMode: 'weakFilter' },
        { type: 'slider', yAxisIndex: 0, right: 0, width: 16, borderColor: '#334155', backgroundColor: '#1e293b', fillerColor: 'rgba(59,130,246,0.15)', showDetail: false },
        { type: 'inside', yAxisIndex: 0 }
      ],
      series,
    });
    
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [ganttData, machineIds]);

  if (!ganttData || !machineIds.length) {
    return <div className="config-empty">暂无有效甘特图数据。</div>;
  }
  
  return <div ref={ref} style={{ width: '100%', height: Math.max(440, machineIds.length * 52 + 120) }} />;
}

function MachineUtilizationChart({ tasks }) {
  const ref = useRef(null);
  
  const data = useMemo(() => {
    if (!tasks?.length) return [];
    const usage = {};
    let minTime = Infinity, maxTime = -Infinity;
    tasks.forEach(t => {
      if (!usage[t.machine_id]) usage[t.machine_id] = 0;
      usage[t.machine_id] += t.duration_mins;
      const st = new Date(t.start).getTime();
      const et = new Date(t.end).getTime();
      if (st < minTime) minTime = st;
      if (et > maxTime) maxTime = et;
    });
    const spanMins = (maxTime - minTime) / 60000;
    const machines = Object.keys(usage).sort();
    return machines.map(m => {
      const pct = spanMins > 0 ? (usage[m] / spanMins) * 100 : 0;
      return { machine: m, value: Math.min(100, Math.round(pct)) };
    });
  }, [tasks]);

  useEffect(() => {
    if (!ref.current || !data.length) return;
    const chart = echarts.init(ref.current, 'dark');
    
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { top: 30, right: 20, bottom: 30, left: 50 },
      xAxis: {
        type: 'category',
        data: data.map(d => d.machine),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#94a3b8' }
      },
      yAxis: {
        type: 'value',
        max: 100,
        axisLine: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } },
        axisLabel: { color: '#94a3b8', formatter: '{value}%' }
      },
      series: [
        {
          // Background gray bar
          type: 'bar',
          itemStyle: { color: 'rgba(255,255,255,0.05)', borderRadius: [4, 4, 0, 0] },
          barGap: '-100%',
          barWidth: 40,
          data: data.map(() => 100),
          animation: false,
          tooltip: { show: false }
        },
        {
          // Foreground blue bar
          type: 'bar',
          itemStyle: { color: '#3b82f6', borderRadius: [4, 4, 0, 0] },
          barWidth: 40,
          data: data.map(d => d.value)
        }
      ]
    });
    
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [data]);
  
  return <div ref={ref} style={{ width: '100%', height: 250 }} />;
}

async function fetchDashboardData() {
  const [dashboardRes, ganttRes, diagnosticsRes] = await Promise.all([
    getDashboard(),
    getGantt(),
    getScheduleDiagnostics({ entity_type: 'order' }),
  ]);
  return {
    summary: dashboardRes.data,
    gantt: ganttRes.data,
    tasks: ganttRes.data.tasks,
    diagnostics: diagnosticsRes.data.diagnostics || [],
  };
}

function formatJobTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-';
}

function parseScheduleError(error) {
  if (!error) return { noMachine: [], otherLines: [], reasonGroups: [], headline: '' };
  const lines = error.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const noMachine = [];
  const otherLines = [];

  lines.forEach(line => {
    const readableNoMachineMatch = line.match(/([A-Za-z0-9_-]+)\s+\u65e0\u53ef\u7528\u673a\u53f0[:：]?\s*(.*)$/);
    const noMachineMatch = line.match(/订单\s+([A-Za-z0-9_-]+)\s+无可用机台:\s*(.*)$/);
    const parsedNoMachineMatch = readableNoMachineMatch || noMachineMatch;
    if (parsedNoMachineMatch) {
      noMachine.push({ orderId: parsedNoMachineMatch[1], reason: parsedNoMachineMatch[2] });
      return;
    }
    if (/no eligible machines/i.test(line)) {
      noMachine.push({ orderId: '-', reason: line });
      return;
    }
    otherLines.push(line);
  });

  const groupMap = noMachine.reduce((acc, item) => {
    const reason = item.reason || '无可用机台';
    const group = reason.split(',')[0].replace(/^(because|reason)[:：]?\s*/i, '').trim() || '无可用机台';
    acc[group] = (acc[group] || 0) + 1;
    return acc;
  }, {});

  return {
    noMachine,
    otherLines,
    reasonGroups: Object.entries(groupMap)
      .map(([reason, count]) => ({ reason, count }))
      .sort((a, b) => b.count - a.count),
    headline: noMachine.length
      ? `${noMachine.length} 个订单无可用机台`
      : (otherLines[0] || '排程失败。'),
  };
}

function diagnosticTarget(diagnostic) {
  const firstRecommendation = diagnostic.recommendations?.[0];
  if (firstRecommendation?.href) return firstRecommendation.href;
  if (diagnostic.entity_type === 'order') return `/config?tab=orders&order=${encodeURIComponent(diagnostic.entity_id)}`;
  if (diagnostic.entity_type === 'machine') return `/config?tab=machines&machine=${encodeURIComponent(diagnostic.entity_id)}`;
  return null;
}

function isOrderActionDiagnostic(diagnostic) {
  if (!diagnostic || diagnostic.entity_type !== 'order') return false;
  const category = diagnostic.category || '';
  const code = diagnostic.code || '';
  return (
    ['eligibility', 'lateness', 'material', 'validation'].includes(category) ||
    code.startsWith('eligibility.') ||
    code.startsWith('lateness.') ||
    code.startsWith('material.')
  );
}

function prioritizedEvidence(evidence, limit = 6) {
  return (evidence || [])
    .map((item, index) => {
      const metric = String(item.metric || '');
      let priority = 1;
      if (metric.includes('examples') || metric.includes('blockers') || metric === 'hard_fit_blockers') priority = 0;
      else if (metric.endsWith('_count') || metric.includes('count')) priority = 2;
      return { item, index, priority };
    })
    .filter(({ item }) => item.actual !== null && item.actual !== undefined && item.actual !== '')
    .sort((a, b) => a.priority - b.priority || a.index - b.index)
    .slice(0, limit)
    .map(({ item }) => item);
}

function DiagnosticList({ diagnostics, limit = 5 }) {
  if (!diagnostics?.length) return null;
  return (
    <div className="diagnostic-list">
      {diagnostics.slice(0, limit).map(diagnostic => {
        const target = diagnosticTarget(diagnostic);
        const evidence = prioritizedEvidence(diagnostic.evidence, 6);
        return (
          <div key={diagnostic.id || `${diagnostic.entity_type}-${diagnostic.entity_id}-${diagnostic.code}`} className={`diagnostic-row severity-${diagnostic.severity || 'info'}`}>
            <div>
              <span className="diagnostic-code">{diagnostic.code}</span>
              <strong>{diagnostic.display_title || diagnostic.entity_id}</strong>
            </div>
            <p>{diagnostic.root_cause}</p>
            {!!evidence.length && (
              <div className="evidence-strip">
                {evidence.map(item => (
                  <span key={`${diagnostic.id}-${item.metric}`}>{item.metric}: {String(item.actual)}</span>
                ))}
              </div>
            )}
            <div className="diagnostic-actions">
              <span>{diagnostic.confidence || '未标注'}</span>
              {target && <Link to={target}>打开配置</Link>}
            </div>
          </div>
        );
      })}
      {diagnostics.length > limit && (
        <small className="diagnostic-more">+ 还有 {diagnostics.length - limit} 条诊断</small>
      )}
    </div>
  );
}

function RootCausePanel({ diagnostics }) {
  const orderDiagnostics = useMemo(
    () => (diagnostics || []).filter(isOrderActionDiagnostic),
    [diagnostics],
  );

  const visible = useMemo(() => {
    const items = orderDiagnostics;
    const rank = { critical: 0, warning: 1, info: 2 };
    return [...items].sort((a, b) => (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9)).slice(0, 6);
  }, [orderDiagnostics]);

  const grouped = useMemo(() => {
    return orderDiagnostics.reduce((acc, item) => {
      const key = item.category || 'unknown';
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
  }, [orderDiagnostics]);

  if (!orderDiagnostics.length) return null;

  return (
    <div className="card root-cause-panel">
      <div className="root-cause-head">
        <div>
          <h3>无法排程 / 延期订单</h3>
          <p>这里只显示无法排程、延期以及受物料约束的订单根因。</p>
        </div>
        <div className="root-cause-counts">
          {Object.entries(grouped).slice(0, 5).map(([category, count]) => (
            <span key={category}>{DIAGNOSTIC_CATEGORY_LABELS[category] || category} {count}</span>
          ))}
        </div>
      </div>
      <DiagnosticList diagnostics={visible} limit={6} />
    </div>
  );
}

function ScheduleJobPanel({ job, error, activeRun }) {
  const [showRaw, setShowRaw] = useState(false);
  const parsedError = useMemo(() => parseScheduleError(error), [error]);
  const structuredDiagnostics = (job?.diagnostics || []).filter(isOrderActionDiagnostic);
  const hasStructuredDiagnostics = structuredDiagnostics.length > 0;

  if (!job && !error && !hasStructuredDiagnostics) return null;
  const state = job?.state || 'idle';
  const activeRunId = activeRun?.run_id || job?.active_run_id || job?.active_run_id_after || null;
  const showingActiveFallback = state === 'failed' && activeRunId;
  const statusMessage = showingActiveFallback
    ? `上一次触发失败，当前仍展示有效运行 #${activeRunId}。`
    : formatScheduleMessage(job?.message);
  const badgeClass = state === 'succeeded'
    ? 'badge-completed'
    : state === 'failed'
      ? 'badge-urgent'
      : state === 'running'
        ? 'badge-scheduled'
        : 'badge-pending';

  return (
    <div className="card" style={{ padding: '18px 20px', marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
          <span className={`badge ${badgeClass}`}>{SCHEDULE_STATE_LABELS[state] || state}</span>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: '#f8fafc', fontSize: 14, fontWeight: 600 }}>
              最近排程触发
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 3 }}>
              {statusMessage}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 18, color: 'var(--text-secondary)', fontSize: 12, whiteSpace: 'nowrap' }}>
          <span>任务 {job?.job_id || '-'}</span>
          <span>触发人 {formatActor(job?.triggered_by)}</span>
          <span>开始 {formatJobTime(job?.started_at)}</span>
          <span>结束 {formatJobTime(job?.finished_at)}</span>
        </div>
      </div>
      <div className="schedule-run-strip">
        <span>当前有效运行</span>
        <strong>#{activeRun?.run_id || job?.active_run_id || '-'}</strong>
        <span>{formatRunStatus(activeRun?.status)}</span>
        <span>{formatActor(activeRun?.triggered_by) || '系统'}</span>
        <span>{formatJobTime(activeRun?.run_time)}</span>
      </div>
      {(error || hasStructuredDiagnostics) && (
        <div className="schedule-error-card">
          <div className="schedule-error-title">
            {hasStructuredDiagnostics ? `${structuredDiagnostics.length} 条结构化根因诊断` : parsedError.headline}
          </div>
          {hasStructuredDiagnostics ? (
            <DiagnosticList diagnostics={structuredDiagnostics} limit={5} />
          ) : parsedError.reasonGroups.length > 0 && (
            <div className="schedule-error-groups">
              {parsedError.reasonGroups.slice(0, 4).map(item => (
                <span key={item.reason}>{item.count} x {item.reason}</span>
              ))}
            </div>
          )}
          {!hasStructuredDiagnostics && parsedError.noMachine.length > 0 && (
            <div className="schedule-error-list">
              {parsedError.noMachine.slice(0, 5).map(item => (
                <div key={`${item.orderId}-${item.reason}`}>
                  {item.orderId === '-' ? (
                    <strong>{item.orderId}</strong>
                  ) : (
                    <Link to={`/config?tab=orders&order=${encodeURIComponent(item.orderId)}`}>
                      <strong>{item.orderId}</strong>
                    </Link>
                  )}
                  <span>{item.reason}</span>
                </div>
              ))}
              {parsedError.noMachine.length > 5 && (
                <small>+ 还有 {parsedError.noMachine.length - 5} 个无法排程订单。打开原始日志可查看完整列表。</small>
              )}
            </div>
          )}
          {!hasStructuredDiagnostics && !parsedError.noMachine.length && parsedError.otherLines.length > 1 && (
            <div className="schedule-error-list">
              {parsedError.otherLines.slice(0, 3).map(line => <div key={line}><span>{line}</span></div>)}
            </div>
          )}
          {error && (
            <>
              <button className="btn btn-ghost btn-small" onClick={() => setShowRaw(open => !open)}>
                {showRaw ? '隐藏原始日志' : '显示原始日志'}
              </button>
              {showRaw && (
                <pre className="raw-log">{error}</pre>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [ganttData, setGanttData] = useState(null);
  const [tasks, setTasks] = useState(null);
  const [diagnostics, setDiagnostics] = useState([]);
  const [scheduleStatus, setScheduleStatus] = useState(null);
  const [scheduleError, setScheduleError] = useState('');

  const refreshDashboardData = useCallback(async () => {
    const { summary: nextSummary, gantt: nextGantt, tasks: nextTasks, diagnostics: nextDiagnostics } = await fetchDashboardData();
    setSummary(nextSummary);
    setGanttData(nextGantt);
    setTasks(nextTasks);
    setDiagnostics(nextDiagnostics);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) refreshDashboardData();
    });
    getScheduleStatus().then(r => {
      if (!cancelled) {
        const nextStatus = r.data;
        setScheduleStatus(nextStatus);
        if (nextStatus.state === 'failed') {
          setScheduleError(nextStatus.stderr_tail || nextStatus.stdout_tail || nextStatus.message || '排程失败。');
        } else if (nextStatus.state === 'succeeded') {
          setScheduleError('');
        }
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [refreshDashboardData]);

  useEffect(() => {
    if (scheduleStatus?.state !== 'running') {
      return undefined;
    }

    const timer = window.setInterval(async () => {
      try {
        const res = await getScheduleStatus();
        const nextStatus = res.data;
        setScheduleStatus(nextStatus);
        if (nextStatus.state !== 'running') {
          window.clearInterval(timer);
          if (nextStatus.state === 'succeeded') {
            setScheduleError('');
            await refreshDashboardData();
          } else if (nextStatus.state === 'failed') {
            setScheduleError(nextStatus.stderr_tail || nextStatus.stdout_tail || nextStatus.message || '排程失败。');
          }
        }
      } catch (err) {
        setScheduleError(err.response?.data?.detail || err.message || '无法读取排程状态。');
        window.clearInterval(timer);
      }
    }, 2000);

    return () => window.clearInterval(timer);
  }, [scheduleStatus?.state, refreshDashboardData]);

  if (!summary || !tasks || !ganttData) return <div className="loading">仪表盘加载中...</div>;
  const visibleDiagnostics = scheduleStatus?.state === 'failed' && scheduleStatus?.diagnostics?.length
    ? scheduleStatus.diagnostics
    : diagnostics;
  const idleCount = ganttData?.idle?.length || 0;
  const downtimeCount = ganttData?.downtime?.length || 0;
  const maintenanceCount = ganttData?.maintenance?.length || 0;
  const orderBucketCards = dashboardOrderBucketCards(summary);
  const deferredReasonCards = dashboardDeferredReasonCards(summary.deferred_reason_counts);
  const bucketToneColors = {
    danger: '#ef4444',
    warning: '#f97316',
    success: '#10b981',
    neutral: undefined,
  };

  return (
    <div>
      <div className="page-header">
        <h2 style={{ fontSize: '24px', fontWeight: 500 }}>仪表盘 (APS)</h2>
        <Link className="btn btn-primary" to="/workbench">进入排程工作台</Link>
      </div>

      <ScheduleJobPanel job={scheduleStatus} error={scheduleError} activeRun={summary} />
      <RootCausePanel diagnostics={visibleDiagnostics} />

      <div className="kpi-grid">
        {orderBucketCards.map(card => (
          <KpiCard key={card.key} label={card.label} value={card.value} valueColor={bucketToneColors[card.tone]} />
        ))}
        <KpiCard label="准时率" value={`${summary.on_time_rate}%`} valueColor="#10b981" />
        <KpiCard label="废料总量" value={`${summary.total_scrap_kg}kg`} />
        <KpiCard label="机台利用率" value={`${summary.avg_utilization}%`} valueColor="#3b82f6" />
      </div>

      {deferredReasonCards.length > 0 && (
        <div className="kpi-grid compact" data-testid="dashboard-deferred-reasons">
          {deferredReasonCards.map(card => (
            <KpiCard key={card.key} label={card.label} value={card.value} valueColor={bucketToneColors[card.tone]} />
          ))}
        </div>
      )}

      {/* Gantt Chart Section */}
      <div className="card dashboard-gantt-card">
        <div className="dashboard-gantt-head">
          <div>
            <h3>交互式甘特图</h3>
            <span>运行 #{summary.run_id || '-'} · {formatRunStatus(summary.status)} · {formatActor(summary.triggered_by) || '系统'}</span>
          </div>
          <div className="gantt-stats">
            <span>空档 {idleCount}</span>
            <span>维护 {maintenanceCount}</span>
            <span>停机 {downtimeCount}</span>
            <Link to="/gantt">打开完整甘特图</Link>
          </div>
        </div>
        <div className="gantt-legend-strip dashboard-gantt-legend">
          <span><i style={{ background: '#3b82f6' }} />生产</span>
          <span><i className="legend-hatch" />换产</span>
          <span><i className="legend-maintenance" />维护</span>
          <span><i style={{ background: 'rgba(239, 68, 68, 0.65)' }} />停机</span>
          <span><i style={{ background: 'rgba(148, 163, 184, 0.28)' }} />空档</span>
          <span>{ganttData?.horizon ? `${formatGanttTime(ganttData.horizon.start)} - ${formatGanttTime(ganttData.horizon.end)}` : '暂无有效窗口'}</span>
        </div>
        <div className="dashboard-gantt-body">
          <DashboardGanttChart ganttData={ganttData} />
        </div>
      </div>

      {/* Machine Utilization Section */}
      <div className="card" style={{ padding: '24px' }}>
        <h3 style={{ fontSize: '16px', color: '#fff', marginBottom: '24px', fontWeight: 500 }}>机台利用率</h3>
        <MachineUtilizationChart tasks={tasks} />
      </div>
    </div>
  );
}
