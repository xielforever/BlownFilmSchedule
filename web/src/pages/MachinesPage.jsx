import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getMachines } from '../api/client';

const machineStatusLabels = {
  ACTIVE: '运行中',
  MAINTENANCE: '维护中',
  OFFLINE: '离线',
};

function MachineCard({ m }) {
  const runPct = Math.min(100, ((m.continuous_run_mins || 0) / 4320) * 100);
  const progClass = runPct > 90 ? 'progress-danger' : runPct > 66 ? 'progress-warn' : 'progress-safe';

  return (
    <div className="machine-card fade-in">
      <div className="machine-header">
        <div>
          <div className="machine-name">{m.name}</div>
          <div className="machine-id">{m.machine_id} · {m.cleanroom_level}</div>
        </div>
        <span className={`badge ${m.status === 'ACTIVE' ? 'badge-completed' : 'badge-urgent'}`}>{machineStatusLabels[m.status] || m.status}</span>
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
      <div className="machine-card-actions">
        <Link className="btn btn-ghost btn-small" to={`/config?tab=machines&machine=${encodeURIComponent(m.machine_id)}`}>编辑配置</Link>
        <Link className="btn btn-ghost btn-small" to={`/gantt?machine=${encodeURIComponent(m.machine_id)}`}>查看 Gantt</Link>
      </div>
    </div>
  );
}

export default function MachinesPage() {
  const [machines, setMachines] = useState([]);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [cleanroomFilter, setCleanroomFilter] = useState('');

  useEffect(() => {
    getMachines().then(r => setMachines(r.data));
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

      <div className="machine-grid">
        {filteredMachines.map(m => <MachineCard key={m.machine_id} m={m} />)}
      </div>
      {!filteredMachines.length && <div className="config-empty">当前筛选条件下没有机台。</div>}
    </div>
  );
}
