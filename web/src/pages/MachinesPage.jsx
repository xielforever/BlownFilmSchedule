import { useState, useEffect } from 'react';
import { getMachines } from '../api/client';

function MachineCard({ m }) {
  const runPct = Math.min(100, (m.continuous_run_mins / 4320) * 100);
  const progClass = runPct > 90 ? 'progress-danger' : runPct > 66 ? 'progress-warn' : 'progress-safe';

  return (
    <div className="machine-card fade-in">
      <div className="machine-header">
        <div>
          <div className="machine-name">{m.name}</div>
          <div className="machine-id">{m.machine_id} · {m.cleanroom_level}</div>
        </div>
        <span className={`badge ${m.status === 'ACTIVE' ? 'badge-completed' : 'badge-urgent'}`}>{m.status}</span>
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
        <span className="machine-stat-label">时产量</span>
        <span className="machine-stat-value">{m.hourly_output_kg} kg/h</span>
      </div>
      <div className="machine-stat">
        <span className="machine-stat-label">当前幅宽</span>
        <span className="machine-stat-value" style={{ color: 'var(--accent-blue)' }}>{m.current_width} mm</span>
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

      {/* 72h progress */}
      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
        连续运行: {m.continuous_run_mins} / 4320 min ({runPct.toFixed(0)}%)
      </div>
      <div className="progress-bar">
        <div className={`progress-fill ${progClass}`} style={{ width: `${runPct}%` }} />
      </div>
    </div>
  );
}

export default function MachinesPage() {
  const [machines, setMachines] = useState([]);

  useEffect(() => {
    getMachines().then(r => setMachines(r.data));
  }, []);

  if (!machines.length) return <div className="loading">加载中...</div>;

  return (
    <div>
      <div className="page-header">
        <h2>机台状态 <span style={{ fontSize: 14, color: 'var(--text-muted)', fontWeight: 400 }}>({machines.length} 台)</span></h2>
      </div>
      <div className="machine-grid">
        {machines.map(m => <MachineCard key={m.machine_id} m={m} />)}
      </div>
    </div>
  );
}
