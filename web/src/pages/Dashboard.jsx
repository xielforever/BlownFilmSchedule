import { useState, useEffect, useRef, useMemo } from 'react';
import * as echarts from 'echarts';
import { getDashboard, getGantt, triggerSchedule } from '../api/client';

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

function DashboardGanttChart({ tasks }) {
  const ref = useRef(null);
  
  useEffect(() => {
    if (!ref.current || !tasks?.length) return;
    const chart = echarts.init(ref.current, 'dark');
    
    // Group machines
    const machines = [...new Set(tasks.map(t => t.machine_id))].sort();
    
    const colors = {
      'MEDICAL_HIGH': '#10b981', // green
      'MEDICAL_STD': '#3b82f6',  // blue
      'PACKAGING': '#f59e0b',    // yellow
      'SPECIAL': '#8b5cf6',      // purple
      'URGENT': '#ef4444'        // red
    };

    const renderItem = (params, api) => {
      const categoryIndex = api.value(0);
      const start = api.coord([api.value(1), categoryIndex]);
      const end = api.coord([api.value(2), categoryIndex]);
      const height = api.size([0, 1])[1] * 0.6;
      const rectShape = echarts.graphic.clipRectByRect({
        x: start[0],
        y: start[1] - height / 2,
        width: end[0] - start[0],
        height: height
      }, {
        x: params.coordSys.x,
        y: params.coordSys.y,
        width: params.coordSys.width,
        height: params.coordSys.height
      });
      return rectShape && {
        type: 'rect',
        transition: ['shape'],
        shape: {
          x: rectShape.x,
          y: rectShape.y,
          width: Math.max(rectShape.width, 4), // min width
          height: rectShape.height,
          r: 4 // border radius
        },
        style: api.style()
      };
    };

    const data = [];
    tasks.forEach(t => {
      const machineIndex = machines.indexOf(t.machine_id);
      const startTime = new Date(t.start).getTime();
      const endTime = new Date(t.end).getTime();
      
      // If there's a setup/changeover time, render it as a gray block
      if (t.setup_mins > 0 && t.setup_start) {
        const setupStartTime = new Date(t.setup_start).getTime();
        data.push({
          name: t.order_id + ' (换产)',
          value: [machineIndex, setupStartTime, startTime, t.setup_mins],
          itemStyle: { color: 'rgba(255, 255, 255, 0.1)', borderColor: '#64748b', borderWidth: 1, borderType: 'dashed' }
        });
      }

      // Main production block
      data.push({
        name: t.order_id,
        value: [machineIndex, startTime, endTime, t.duration_mins],
        itemStyle: { color: colors[t.order_class] || colors['MEDICAL_STD'] }
      });
    });

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        formatter: function (params) {
          return params.marker + params.name + ': ' + params.value[3] + ' mins';
        }
      },
      grid: { top: 50, right: 30, bottom: 30, left: 100 },
      xAxis: {
        type: 'time',
        splitLine: { show: true, lineStyle: { color: 'rgba(255,255,255,0.05)' } },
        axisLabel: { color: '#94a3b8' }
      },
      yAxis: {
        type: 'category',
        data: machines,
        splitLine: { show: true, lineStyle: { color: 'rgba(255,255,255,0.05)' } },
        axisLabel: { color: '#94a3b8' }
      },
      series: [{
        type: 'custom',
        renderItem: renderItem,
        itemStyle: { opacity: 0.9 },
        encode: { x: [1, 2], y: 0 },
        data: data
      }]
    });
    
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [tasks]);
  
  return <div ref={ref} style={{ width: '100%', height: 400 }} />;
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

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [tasks, setTasks] = useState(null);

  useEffect(() => {
    getDashboard().then(r => setSummary(r.data));
    getGantt().then(r => setTasks(r.data.tasks));
  }, []);

  if (!summary || !tasks) return <div className="loading">加载中...</div>;

  return (
    <div>
      <div className="page-header">
        <h2 style={{ fontSize: '24px', fontWeight: 500 }}>Dashboard (APS)</h2>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Total Orders" value={summary.total_orders} />
        <KpiCard label="On-Time Rate" value={`${summary.on_time_rate}%`} valueColor="#10b981" />
        <KpiCard label="Total Scrap" value={`${summary.total_scrap_kg}kg`} />
        <KpiCard label="Machine Utilization" value={`${summary.avg_utilization}%`} valueColor="#3b82f6" />
      </div>

      {/* Gantt Chart Section */}
      <div className="card" style={{ marginBottom: 24, padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '16px 24px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button className="btn btn-ghost" style={{ background: 'rgba(255,255,255,0.1)', color: '#fff' }}>Interactive</button>
            <button className="btn btn-ghost" style={{ border: 'none' }}>Starnt Chart</button>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <select className="btn btn-ghost" style={{ outline: 'none' }}>
              <option>Scheduled Start</option>
            </select>
            <select className="btn btn-ghost" style={{ outline: 'none' }}>
              <option>End Timers</option>
            </select>
          </div>
        </div>
        <div style={{ padding: '20px' }}>
          <DashboardGanttChart tasks={tasks} />
        </div>
      </div>

      {/* Machine Utilization Section */}
      <div className="card" style={{ padding: '24px' }}>
        <h3 style={{ fontSize: '16px', color: '#fff', marginBottom: '24px', fontWeight: 500 }}>Machine Utilization</h3>
        <MachineUtilizationChart tasks={tasks} />
      </div>
    </div>
  );
}
