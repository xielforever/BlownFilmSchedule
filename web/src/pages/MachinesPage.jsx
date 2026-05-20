import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getMachines, getScheduleDiagnostics } from '../api/client';

const machineStatusLabels = {
  ACTIVE: '运行中',
  MAINTENANCE: '维护中',
  OFFLINE: '离线',
};
const diagnosticSeverityLabels = {
  critical: '关键',
  warning: '警告',
  info: '提示',
};
const diagnosticCategoryLabels = {
  capacity: '产能',
  setup: '换产',
  idle: '空档',
  maintenance: '维护',
  downtime: '停机',
};
const diagnosticEvidenceLabels = {
  load_pct: '负载',
  production_mins: '生产',
  horizon_mins: '窗口',
  scheduled_orders: '订单',
  setup_mins: '换产',
  setup_ratio: '换产占比',
};

function severityRank(severity) {
  return { critical: 0, warning: 1, info: 2 }[severity] ?? 9;
}

function formatEvidence(item) {
  const label = diagnosticEvidenceLabels[item.metric] || item.metric;
  const unit = item.unit ? ` ${item.unit}` : '';
  return `${label}: ${item.actual ?? '-'}${unit}`;
}

function prioritizeEvidence(evidence = []) {
  const priority = ['load_pct', 'setup_ratio', 'setup_mins', 'production_mins', 'scheduled_orders'];
  return [...evidence]
    .sort((a, b) => {
      const left = priority.indexOf(a.metric);
      const right = priority.indexOf(b.metric);
      return (left === -1 ? 99 : left) - (right === -1 ? 99 : right);
    })
    .slice(0, 3);
}

function MachineDiagnostics({ diagnostics }) {
  if (!diagnostics.length) {
    return <div className="machine-diagnostic-empty">当前无机台级诊断</div>;
  }

  const visible = diagnostics
    .slice()
    .sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
    .slice(0, 2);

  return (
    <div className="machine-diagnostics">
      {visible.map(diagnostic => (
        <div key={diagnostic.id || `${diagnostic.entity_id}-${diagnostic.code}`} className={`machine-diagnostic severity-${diagnostic.severity || 'info'}`}>
          <div className="machine-diagnostic-head">
            <span>{diagnosticCategoryLabels[diagnostic.category] || diagnostic.category}</span>
            <strong>{diagnostic.display_title || diagnostic.code}</strong>
            <em>{diagnosticSeverityLabels[diagnostic.severity] || diagnostic.severity || '提示'}</em>
          </div>
          <p>{diagnostic.root_cause}</p>
          {!!diagnostic.evidence?.length && (
            <div className="machine-diagnostic-evidence">
              {prioritizeEvidence(diagnostic.evidence).map(item => (
                <span key={`${diagnostic.id}-${item.metric}`}>{formatEvidence(item)}</span>
              ))}
            </div>
          )}
          {!!diagnostic.recommendations?.length && (
            <div className="machine-diagnostic-actions">
              {diagnostic.recommendations.slice(0, 2).map(action => (
                <Link key={`${diagnostic.id}-${action.action}`} to={action.href}>{action.label}</Link>
              ))}
            </div>
          )}
        </div>
      ))}
      {diagnostics.length > visible.length && (
        <small className="machine-diagnostic-more">+ {diagnostics.length - visible.length} 条机台诊断</small>
      )}
    </div>
  );
}

function MachineDiagnosticsSummary({ diagnostics, runId, error }) {
  if (error) {
    return <div className="machine-diagnostics-summary error">{error}</div>;
  }
  if (!diagnostics.length) return null;

  const counts = diagnostics.reduce((acc, item) => {
    const key = item.code || 'unknown';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="machine-diagnostics-summary">
      <div>
        <strong>机台诊断</strong>
        <span>{runId ? `运行 #${runId}` : '当前有效运行'} · {diagnostics.length} 条</span>
      </div>
      <div>
        {Object.entries(counts).slice(0, 5).map(([code, count]) => (
          <span key={code}>{code} {count}</span>
        ))}
      </div>
    </div>
  );
}

function MachineCard({ m, diagnostics }) {
  const runPct = Math.min(100, ((m.continuous_run_mins || 0) / 4320) * 100);
  const progClass = runPct > 90 ? 'progress-danger' : runPct > 66 ? 'progress-warn' : 'progress-safe';
  const hasWarnings = diagnostics.some(item => item.severity === 'critical' || item.severity === 'warning');

  return (
    <div className="machine-card fade-in">
      <div className="machine-header">
        <div>
          <div className="machine-name">{m.name}</div>
          <div className="machine-id">{m.machine_id} · {m.cleanroom_level}</div>
        </div>
        <div className="machine-badges">
          <span className={`badge ${m.status === 'ACTIVE' ? 'badge-completed' : 'badge-urgent'}`}>{machineStatusLabels[m.status] || m.status}</span>
          {!!diagnostics.length && (
            <span className={`badge ${hasWarnings ? 'badge-urgent' : 'badge-scheduled'}`}>诊断 {diagnostics.length}</span>
          )}
        </div>
      </div>

      <div className="machine-stat">
        <span className="machine-stat-label">层级结构</span>
        <span className="machine-stat-value">{m.layer_structure} 层共挤</span>
      </div>
      <div className="machine-stat">
        <span className="machine-stat-label">幅宽范围</span>
        <span className="machine-stat-value">{m.min_width} ~ {m.max_width} mm</span>
      </div>
      <div className="machine-stat">
        <span className="machine-stat-label">厚度范围</span>
        <span className="machine-stat-value">{m.min_thickness} ~ {m.max_thickness} um</span>
      </div>
      <div className="machine-stat">
        <span className="machine-stat-label">时产量</span>
        <span className="machine-stat-value">{m.hourly_output_kg} kg/h</span>
      </div>
      <div className="machine-stat">
        <span className="machine-stat-label">当前幅宽</span>
        <span className="machine-stat-value" style={{ color: 'var(--accent-blue)' }}>{m.current_width || 0} mm</span>
      </div>
      <div className="machine-stat">
        <span className="machine-stat-label">最后工单</span>
        <span className="machine-stat-value" style={{ color: 'var(--accent-green)' }}>{m.last_order_id || '-'}</span>
      </div>
      <div className="machine-stat">
        <span className="machine-stat-label">当前挂料</span>
        <span className="machine-stat-value" style={{ fontSize: 11 }}>
          {m.current_materials?.slice(0, 2).join(', ') || '-'}
          {m.current_materials?.length > 2 && '...'}
        </span>
      </div>

      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
        连续运行: {m.continuous_run_mins || 0} / 4320 分钟 ({runPct.toFixed(0)}%)
      </div>
      <div className="progress-bar">
        <div className={`progress-fill ${progClass}`} style={{ width: `${runPct}%` }} />
      </div>
      <MachineDiagnostics diagnostics={diagnostics} />
      <div className="machine-card-actions">
        <Link className="btn btn-ghost btn-small" to={`/config?tab=machines&machine=${encodeURIComponent(m.machine_id)}`}>编辑配置</Link>
        <Link className="btn btn-ghost btn-small" to={`/gantt?machine=${encodeURIComponent(m.machine_id)}`}>查看 Gantt</Link>
      </div>
    </div>
  );
}

export default function MachinesPage() {
  const [machines, setMachines] = useState([]);
  const [diagnostics, setDiagnostics] = useState([]);
  const [diagnosticsRunId, setDiagnosticsRunId] = useState(null);
  const [diagnosticsError, setDiagnosticsError] = useState('');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [cleanroomFilter, setCleanroomFilter] = useState('');

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(async () => {
      try {
        const [machineRes, diagnosticsRes] = await Promise.all([
          getMachines(),
          getScheduleDiagnostics({ entity_type: 'machine' }),
        ]);
        if (cancelled) return;
        setMachines(machineRes.data);
        setDiagnostics(diagnosticsRes.data.diagnostics || []);
        setDiagnosticsRunId(diagnosticsRes.data.run_id || null);
        setDiagnosticsError('');
      } catch (err) {
        if (cancelled) return;
        setDiagnosticsError(err.response?.data?.detail || err.message || '无法读取机台诊断。');
        try {
          const machineRes = await getMachines();
          if (!cancelled) setMachines(machineRes.data);
        } catch {
          if (!cancelled) setMachines([]);
        }
      }
    });
    return () => { cancelled = true; };
  }, []);

  const filteredMachines = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return machines.filter(machine => {
      if (statusFilter && machine.status !== statusFilter) return false;
      if (cleanroomFilter && machine.cleanroom_level !== cleanroomFilter) return false;
      if (!needle) return true;
      return [
        machine.machine_id,
        machine.name,
        machine.cleanroom_level,
        machine.status,
        machine.last_order_id,
      ].some(value => String(value || '').toLowerCase().includes(needle));
    });
  }, [machines, query, statusFilter, cleanroomFilter]);

  const diagnosticsByMachine = useMemo(() => diagnostics.reduce((acc, item) => {
    const key = item.entity_id;
    if (!key) return acc;
    acc[key] = acc[key] || [];
    acc[key].push(item);
    return acc;
  }, {}), [diagnostics]);

  if (!machines.length) return <div className="loading">加载中...</div>;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>机台状态 <span style={{ fontSize: 14, color: 'var(--text-muted)', fontWeight: 400 }}>({filteredMachines.length} / {machines.length} 台)</span></h2>
          <p className="page-subtitle">可按状态、洁净等级或最后工单筛选，并直接进入配置页。</p>
        </div>
        <Link className="btn btn-primary" to="/config?tab=machines">配置机台</Link>
      </div>

      <div className="page-toolbar">
        <input
          className="search-input"
          value={query}
          placeholder="搜索机台、名称、最后工单"
          onChange={e => setQuery(e.target.value)}
        />
        <div className="segmented-control">
          {['', 'ACTIVE', 'MAINTENANCE', 'OFFLINE'].map(status => (
            <button key={status} className={statusFilter === status ? 'active' : ''} onClick={() => setStatusFilter(status)}>
              {status ? machineStatusLabels[status] || status : '全部状态'}
            </button>
          ))}
        </div>
        <div className="segmented-control">
          {['', 'Class_10K', 'Class_100K'].map(level => (
            <button key={level} className={cleanroomFilter === level ? 'active' : ''} onClick={() => setCleanroomFilter(level)}>
              {level || '全部洁净等级'}
            </button>
          ))}
        </div>
      </div>

      <MachineDiagnosticsSummary diagnostics={diagnostics} runId={diagnosticsRunId} error={diagnosticsError} />

      <div className="machine-grid">
        {filteredMachines.map(m => (
          <MachineCard key={m.machine_id} m={m} diagnostics={diagnosticsByMachine[m.machine_id] || []} />
        ))}
      </div>
      {!filteredMachines.length && <div className="config-empty">当前筛选条件下没有机台。</div>}
    </div>
  );
}
