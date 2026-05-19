import { useState, useEffect, useMemo, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as echarts from 'echarts';
import { getGantt } from '../api/client';

const ORDER_CLASS_COLORS = {
  URGENT: '#ef4444',
  NORMAL: '#3b82f6',
  SAMPLE: '#f59e0b',
};

const ORDER_CLASS_LABELS = {
  URGENT: 'URGENT',
  NORMAL: '普通',
  SAMPLE: '样品',
};

const GANTT_KIND_LABELS = {
  production: '生产',
  setup: '换产',
  idle: '空档',
  maintenance: '维护',
  downtime: '停机',
};

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-';
}

function formatDuration(minutes) {
  if (!minutes && minutes !== 0) return '-';
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins ? `${hours} 小时 ${mins} 分钟` : `${hours} 小时`;
}

function getMachineIds(chartData) {
  if (!chartData) return [];
  const configured = (chartData.machines || []).map(machine => machine.machine_id);
  const eventMachines = [
    ...(chartData.tasks || []),
    ...(chartData.maintenance || []),
    ...(chartData.downtime || []),
    ...(chartData.idle || []),
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

function renderTooltip(params) {
  const d = params.value[3];
  const start = new Date(params.value[1]).toLocaleString('zh-CN');
  const end = new Date(params.value[2]).toLocaleString('zh-CN');

  if (d.kind === 'idle') {
    return `<b>空档</b><br/>${d.reason || '空档区间'}<br/>持续时间：${formatDuration(d.duration_mins)}<br/>${start} ~ ${end}` +
      (d.guidance ? `<br/><span style="color:#bfdbfe">${d.guidance}</span>` : '');
  }
  if (d.kind === 'setup') {
    return `<b>${d.order_id} 换产</b><br/>持续时间：${formatDuration(d.setup_mins)}<br/>${start} ~ ${end}`;
  }
  if (d.kind === 'maintenance') {
    return `<b>维护</b><br/>${d.type || '计划维护'}${d.reason ? ` - ${d.reason}` : ''}<br/>持续时间：${formatDuration(d.duration_mins)}<br/>${start} ~ ${end}` +
      (d.guidance ? `<br/><span style="color:#bfdbfe">${d.guidance}</span>` : '');
  }
  if (d.kind === 'downtime') {
    return `<b>停机</b><br/>${d.type || '事件'}${d.cause ? ` - ${d.cause}` : ''}<br/>级别：${d.severity || '-'}<br/>持续时间：${formatDuration(d.duration_mins)}<br/>${start} ~ ${end}` +
      (d.guidance ? `<br/><span style="color:#bfdbfe">${d.guidance}</span>` : '');
  }

  return `<b>${d.order_id}</b><br/>${d.product_type || '生产'}<br/>` +
    `${d.target_width}mm x ${d.target_thickness}um<br/>` +
    `换产：${formatDuration(d.setup_mins)} | 废料：${d.scrap_kg} kg<br/>` +
    `${start} ~ ${end}` +
    (d.is_late ? `<br/><span style="color:#ef4444">延期 ${formatDuration(d.tardiness_mins)}</span>` : '') +
    (d.guidance ? `<br/><span style="color:#bfdbfe">${d.guidance}</span>` : '');
}

function getEventDiagnostics(event) {
  if (!event) return [];
  const diagnostics = [];
  if (event.diagnostic) diagnostics.push(event.diagnostic);
  if (Array.isArray(event.diagnostics)) diagnostics.push(...event.diagnostics);
  return diagnostics;
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

function EventDiagnosticPanel({ event }) {
  if (!event) {
    return (
      <div className="gantt-event-panel empty">
        选择一个事件查看根因和后续建议。
      </div>
    );
  }

  const diagnostics = getEventDiagnostics(event);
  const title = event.kind === 'production'
    ? event.order_id
    : `${GANTT_KIND_LABELS[event.kind] || event.kind || '事件'} · ${event.machine_id}`;

  return (
    <div className="gantt-event-panel">
      <div className="gantt-event-head">
        <div>
          <span className="diagnostic-code">{GANTT_KIND_LABELS[event.kind] || event.kind}</span>
          <h3>{title}</h3>
        </div>
        <span>{formatTime(event.start)} - {formatTime(event.end)}</span>
      </div>
      <div className="gantt-event-meta">
        <span>机台 {event.machine_id}</span>
        {event.duration_mins !== undefined && <span>时长 {formatDuration(event.duration_mins)}</span>}
        {event.confidence && <span>{event.confidence}</span>}
        {event.code && <span>{event.code}</span>}
      </div>
      {event.guidance && <p className="gantt-guidance">{event.guidance}</p>}
      {diagnostics.length ? (
        <div className="diagnostic-list compact">
          {diagnostics.map(diagnostic => (
            <div key={diagnostic.id || diagnostic.code} className={`diagnostic-row severity-${diagnostic.severity || 'info'}`}>
              <div>
                <span className="diagnostic-code">{diagnostic.code}</span>
                <strong>{diagnostic.display_title || diagnostic.entity_id}</strong>
              </div>
              <p>{diagnostic.root_cause}</p>
              {!!diagnostic.evidence?.length && (
                <div className="evidence-strip">
                  {prioritizedEvidence(diagnostic.evidence, 6).map(item => (
                    <span key={`${diagnostic.id}-${item.metric}`}>{item.metric}: {String(item.actual ?? '-')}</span>
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
      ) : (
        <p className="gantt-guidance">该事件暂无结构化诊断。</p>
      )}
    </div>
  );
}

export default function GanttPage() {
  const [data, setData] = useState(null);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [searchParams] = useSearchParams();
  const chartRef = useRef(null);
  const machineFilter = searchParams.get('machine') || '';

  const chartData = useMemo(() => {
    if (!data || !machineFilter) return data;
    return {
      ...data,
      machines: (data.machines || []).filter(machine => machine.machine_id === machineFilter),
      tasks: (data.tasks || []).filter(task => task.machine_id === machineFilter),
      maintenance: (data.maintenance || []).filter(item => item.machine_id === machineFilter),
      downtime: (data.downtime || []).filter(item => item.machine_id === machineFilter),
      idle: (data.idle || []).filter(item => item.machine_id === machineFilter),
    };
  }, [data, machineFilter]);

  const machineIds = useMemo(() => getMachineIds(chartData), [chartData]);

  useEffect(() => {
    getGantt().then(r => setData(r.data));
  }, []);

  useEffect(() => {
    if (!chartRef.current || !chartData || !machineIds.length) return undefined;

    const chart = echarts.init(chartRef.current, 'dark');
    const setupPattern = buildHatchPattern('#475569');
    const maintenancePattern = buildHatchPattern('#ef4444');

    const productionByClass = {};
    const setupData = [];

    (chartData.tasks || []).forEach(task => {
      const yIdx = machineIds.indexOf(task.machine_id);
      if (yIdx < 0) return;
      const start = new Date(task.start).getTime();
      const end = new Date(task.end).getTime();
      const className = task.order_class || 'NORMAL';

      if (task.setup_mins > 0 && task.setup_start) {
        setupData.push({
          value: [yIdx, new Date(task.setup_start).getTime(), start, { ...task, kind: 'setup' }],
          itemStyle: { color: setupPattern, borderColor: '#475569', borderWidth: 1 },
        });
      }

      if (!productionByClass[className]) productionByClass[className] = [];
      productionByClass[className].push({
        value: [yIdx, start, end, { ...task, kind: 'production' }],
        itemStyle: { color: ORDER_CLASS_COLORS[className] || '#64748b' },
      });
    });

    const idleData = (chartData.idle || []).map(item => {
      const yIdx = machineIds.indexOf(item.machine_id);
      if (yIdx < 0) return null;
      return {
        value: [yIdx, new Date(item.start).getTime(), new Date(item.end).getTime(), { ...item, kind: 'idle' }],
        itemStyle: { color: 'rgba(148, 163, 184, 0.22)', borderColor: 'rgba(148, 163, 184, 0.38)', borderWidth: 1 },
      };
    }).filter(Boolean);

    const maintenanceData = (chartData.maintenance || []).map(item => {
      const yIdx = machineIds.indexOf(item.machine_id);
      if (yIdx < 0) return null;
      return {
        value: [yIdx, new Date(item.start).getTime(), new Date(item.end).getTime(), { ...item, kind: 'maintenance' }],
        itemStyle: { color: maintenancePattern, borderColor: '#ef4444', borderWidth: 1 },
      };
    }).filter(Boolean);

    const downtimeData = (chartData.downtime || []).map(item => {
      const yIdx = machineIds.indexOf(item.machine_id);
      if (yIdx < 0) return null;
      return {
        value: [yIdx, new Date(item.start).getTime(), new Date(item.end).getTime(), { ...item, kind: 'downtime' }],
        itemStyle: { color: 'rgba(239, 68, 68, 0.55)', borderColor: '#fca5a5', borderWidth: 1 },
      };
    }).filter(Boolean);

    function renderGanttBar(params, api) {
      const yIdx = api.value(0);
      const start = api.coord([api.value(1), yIdx]);
      const end = api.coord([api.value(2), yIdx]);
      const d = api.value(3);
      const heightRatio = d.kind === 'idle' ? 0.34 : 0.62;
      const height = api.size([0, 1])[1] * heightRatio;
      const width = Math.max(end[0] - start[0], 0);
      const style = api.style();

      if (d.kind === 'production' && width > 44) {
        style.text = d.order_id;
        style.textFill = '#ffffff';
        style.fontSize = 10;
        style.width = width - 8;
        style.overflow = 'truncate';
      }

      const rectShape = echarts.graphic.clipRectByRect({
        x: start[0],
        y: start[1] - height / 2,
        width,
        height,
      }, {
        x: params.coordSys.x,
        y: params.coordSys.y,
        width: params.coordSys.width,
        height: params.coordSys.height,
      });

      return rectShape && {
        type: 'rect',
        transition: ['shape'],
        shape: { ...rectShape, r: Math.min(2, rectShape.width / 2) },
        style,
      };
    }

    const seriesList = [
      {
        type: 'custom',
        name: '空档',
        z: 1,
        renderItem: renderGanttBar,
        encode: { x: [1, 2], y: 0 },
        data: idleData,
        emphasis: { disabled: true },
      },
      {
        type: 'custom',
        name: '停机',
        z: 3,
        renderItem: renderGanttBar,
        encode: { x: [1, 2], y: 0 },
        data: downtimeData,
      },
      {
        type: 'custom',
        name: '维护',
        z: 4,
        renderItem: renderGanttBar,
        encode: { x: [1, 2], y: 0 },
        data: maintenanceData,
      },
      {
        type: 'custom',
        name: '换产',
        z: 5,
        renderItem: renderGanttBar,
        encode: { x: [1, 2], y: 0 },
        data: setupData,
      },
      ...Object.keys(productionByClass).sort().map(className => ({
        type: 'custom',
        name: ORDER_CLASS_LABELS[className] || className,
        z: 6,
        renderItem: renderGanttBar,
        encode: { x: [1, 2], y: 0 },
        data: productionByClass[className],
        emphasis: { disabled: true },
      })),
    ];

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { formatter: renderTooltip },
      legend: {
        top: 0,
        left: 0,
        textStyle: { color: '#cbd5e1', fontSize: 12 },
        itemWidth: 14,
        itemHeight: 14,
        icon: 'roundRect',
        type: 'scroll',
      },
      grid: { top: 60, right: 40, bottom: 60, left: 100 },
      xAxis: {
        type: 'time',
        min: chartData.horizon?.start ? new Date(chartData.horizon.start).getTime() : undefined,
        max: chartData.horizon?.end ? new Date(chartData.horizon.end).getTime() : undefined,
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        splitLine: { show: true, lineStyle: { type: 'dashed', opacity: 0.15, color: '#334155' } },
      },
      yAxis: {
        type: 'category',
        data: machineIds,
        axisLabel: { color: '#f1f5f9', fontSize: 12, fontWeight: 600 },
        inverse: true,
        splitLine: { show: true, lineStyle: { opacity: 0.1, color: '#334155' } },
      },
      dataZoom: [
        {
          type: 'slider',
          xAxisIndex: 0,
          bottom: 10,
          height: 20,
          borderColor: '#334155',
          backgroundColor: '#1e293b',
          fillerColor: 'rgba(59,130,246,0.15)',
          handleStyle: { color: '#3b82f6' },
          textStyle: { color: '#94a3b8' },
          showDetail: true,
          filterMode: 'weakFilter',
        },
        { type: 'inside', xAxisIndex: 0, filterMode: 'weakFilter' },
        {
          type: 'slider',
          yAxisIndex: 0,
          right: 0,
          width: 16,
          borderColor: '#334155',
          backgroundColor: '#1e293b',
          fillerColor: 'rgba(59,130,246,0.15)',
          showDetail: false,
        },
      ],
      series: seriesList,
    }, true);

    const handleClick = (params) => {
      const event = params?.value?.[3];
      if (event) setSelectedEvent(event);
    };
    const resize = () => chart.resize();
    chart.on('click', handleClick);
    window.addEventListener('resize', resize);
    return () => {
      chart.off('click', handleClick);
      window.removeEventListener('resize', resize);
      chart.dispose();
    };
  }, [chartData, machineIds]);

  const dynamicHeight = Math.max(520, machineIds.length * 64 + 140);
  const orderCount = chartData?.tasks?.length || 0;
  const idleCount = chartData?.idle?.length || 0;
  const downtimeCount = chartData?.downtime?.length || 0;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>排程 Gantt</h2>
          <p className="page-subtitle">
            运行 #{chartData?.run_id || '-'} | {machineFilter ? `机台 ${machineFilter}` : `${machineIds.length} 台机台`} | {orderCount} 个订单
          </p>
        </div>
        <div className="gantt-stats">
          <span>空档 {idleCount}</span>
          <span>停机 {downtimeCount}</span>
          <span>{chartData?.horizon ? `${formatTime(chartData.horizon.start)} - ${formatTime(chartData.horizon.end)}` : '暂无有效窗口'}</span>
        </div>
      </div>

      <div className="card gantt-card">
        <div className="gantt-legend-strip">
          <span><i style={{ background: '#3b82f6' }} />生产</span>
          <span><i className="legend-hatch" />换产</span>
          <span><i className="legend-maintenance" />维护</span>
          <span><i style={{ background: 'rgba(239, 68, 68, 0.65)' }} />停机</span>
          <span><i style={{ background: 'rgba(148, 163, 184, 0.28)' }} />空档</span>
        </div>
        {chartData && machineIds.length ? (
          <div ref={chartRef} className="gantt-wrapper" style={{ height: dynamicHeight }} />
        ) : chartData ? (
          <div className="config-empty">当前机台筛选下没有 Gantt 事件。</div>
        ) : (
          <div className="loading">Gantt 数据加载中...</div>
        )}
      </div>

      <EventDiagnosticPanel event={selectedEvent} />
    </div>
  );
}
