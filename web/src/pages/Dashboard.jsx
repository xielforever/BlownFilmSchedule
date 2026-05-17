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
    
    const machines = [...new Set(tasks.map(t => t.machine_id))].sort();
    
    const colors = {
      'MEDICAL_HIGH': '#10b981',
      'MEDICAL_STD': '#3b82f6',
      'PACKAGING': '#f59e0b',
      'SPECIAL': '#8b5cf6',
      'URGENT': '#ef4444'
    };

    const patternCanvas = document.createElement('canvas');
    patternCanvas.width = 10;
    patternCanvas.height = 10;
    const ctx = patternCanvas.getContext('2d');
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(0, 0, 10, 10);
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, 10);
    ctx.lineTo(10, 0);
    ctx.stroke();
    const hatchPattern = { image: patternCanvas, repeat: 'repeat' };

    const renderItem = (params, api) => {
      const categoryIndex = api.value(0);
      const start = api.coord([api.value(1), categoryIndex]);
      const end = api.coord([api.value(2), categoryIndex]);
      const height = api.size([0, 1])[1] * 0.6;
      const width = Math.max(end[0] - start[0], 1.5);
      
      const d = api.value(3);
      const style = api.style();
      
      if (!d.is_setup && width > 40) {
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

    const data = [];
    tasks.forEach(t => {
      const machineIndex = machines.indexOf(t.machine_id);
      const startTime = new Date(t.start).getTime();
      const endTime = new Date(t.end).getTime();
      
      if (t.setup_mins > 0 && t.setup_start) {
        const setupStartTime = new Date(t.setup_start).getTime();
        data.push({
          name: t.order_id + ' (换产)',
          value: [machineIndex, setupStartTime, startTime, { ...t, is_setup: true }],
          itemStyle: { color: hatchPattern, borderColor: '#475569', borderWidth: 1 }
        });
      }

      data.push({
        name: t.order_id,
        value: [machineIndex, startTime, endTime, t],
        itemStyle: { color: colors[t.order_class] || colors['MEDICAL_STD'] }
      });
    });

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        formatter: function (params) {
          const d = params.value[3];
          if (d.is_setup) {
            return `${params.marker} <b>${d.order_id} (换产准备)</b>: ${d.setup_mins} 分钟`;
          }
          return `${params.marker} <b>${d.order_id}</b>: ${d.duration_mins} 分钟`;
        }
      },
      grid: { top: 30, right: 40, bottom: 40, left: 80 },
      xAxis: {
        type: 'time',
        splitLine: { show: true, lineStyle: { color: '#334155', type: 'dashed', opacity: 0.5 } },
        axisLabel: { color: '#94a3b8', fontSize: 11 }
      },
      yAxis: {
        type: 'category',
        data: machines,
        inverse: true,
        splitLine: { show: true, lineStyle: { color: '#334155', opacity: 0.3 } },
        axisLabel: { color: '#f1f5f9', fontWeight: 600, fontSize: 11 }
      },
      dataZoom: [
        { type: 'slider', xAxisIndex: 0, bottom: 0, height: 16, borderColor: '#334155', backgroundColor: '#1e293b', fillerColor: 'rgba(59,130,246,0.15)', textStyle: { color: '#94a3b8' }, showDetail: false },
        { type: 'inside', xAxisIndex: 0 },
        { type: 'slider', yAxisIndex: 0, right: 0, width: 16, borderColor: '#334155', backgroundColor: '#1e293b', fillerColor: 'rgba(59,130,246,0.15)', showDetail: false },
        { type: 'inside', yAxisIndex: 0 }
      ],
      series: [{
        type: 'custom',
        renderItem: renderItem,
        encode: { x: [1, 2], y: 0 },
        data: data
      }]
    });
    
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [tasks]);
  
  return <div ref={ref} style={{ width: '100%', height: Math.max(400, [...new Set(tasks?.map(t => t.machine_id))].length * 40) }} />;
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
