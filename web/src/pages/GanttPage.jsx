import { useState, useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import { getGantt } from '../api/client';

const PRODUCT_COLORS = {
  '医用多层输液袋膜': '#6366f1',
  '医药袋高洁净内衬膜': '#8b5cf6',
  '医药袋常规内衬膜': '#a78bfa',
  '医疗器械顶盖透气膜': '#06b6d4',
  '医疗器械吸塑包装膜': '#14b8a6',
  '医用大宗防潮外包装膜': '#f97316',
  '临床试验加急样品膜': '#ec4899',
};

export default function GanttPage() {
  const [data, setData] = useState(null);
  const chartRef = useRef(null);

  useEffect(() => { getGantt().then(r => setData(r.data)); }, []);

  useEffect(() => {
    if (!chartRef.current || !data?.tasks?.length) return;

    const machines = [...new Set(data.tasks.map(t => t.machine_id))].sort();
    const chart = echarts.init(chartRef.current, 'dark');

    // Build Gantt bars as custom series
    const seriesData = [];
    data.tasks.forEach(t => {
      const start = new Date(t.start).getTime();
      const end = new Date(t.end).getTime();
      const yIdx = machines.indexOf(t.machine_id);
      const color = PRODUCT_COLORS[t.product_type] || '#64748b';
      
      if (t.setup_mins > 0 && t.setup_start) {
        const setupStart = new Date(t.setup_start).getTime();
        seriesData.push({
          value: [yIdx, setupStart, start, { ...t, is_setup: true }],
          itemStyle: { color: 'rgba(255, 255, 255, 0.1)', borderColor: '#64748b', borderWidth: 1, borderType: 'dashed' },
        });
      }

      seriesData.push({
        value: [yIdx, start, end, t],
        itemStyle: { color, borderRadius: 3 },
      });
    });

    // Maintenance windows
    const maintData = data.maintenance.map(m => {
      const yIdx = machines.indexOf(m.machine_id);
      if (yIdx < 0) return null;
      return {
        value: [yIdx, new Date(m.start).getTime(), new Date(m.end).getTime(), m],
        itemStyle: { color: 'rgba(100,116,139,0.3)', borderColor: '#64748b', borderWidth: 1, borderType: 'dashed' },
      };
    }).filter(Boolean);

    function renderGanttBar(params, api) {
      const yIdx = api.value(0);
      const start = api.coord([api.value(1), yIdx]);
      const end = api.coord([api.value(2), yIdx]);
      const height = api.size([0, 1])[1] * 0.6;
      return {
        type: 'rect',
        shape: { x: start[0], y: start[1] - height / 2, width: Math.max(end[0] - start[0], 2), height },
        style: api.style(),
      };
    }

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        formatter: (params) => {
          const d = params.value[3];
          if (d.order_id) {
            if (d.is_setup) {
              return `<b>${d.order_id} (换产准备)</b><br/>换产耗时: ${d.setup_mins} 分钟<br/>` +
                     `${new Date(d.setup_start).toLocaleString()} ~ ${new Date(d.start).toLocaleString()}`;
            }
            return `<b>${d.order_id}</b><br/>${d.product_type}<br/>` +
              `${d.target_width}mm × ${d.target_thickness}μm<br/>` +
              `换产: ${d.setup_mins} min | 废料: ${d.scrap_kg} kg<br/>` +
              `${new Date(d.start).toLocaleString()} ~ ${new Date(d.end).toLocaleString()}` +
              (d.is_late ? `<br/><span style="color:#ef4444">⚠ 逾期 ${d.tardiness_mins} min</span>` : '');
          }
          return `维保: ${d.reason || '计划维保'}`;
        }
      },
      grid: { top: 40, right: 40, bottom: 60, left: 100 },
      xAxis: { type: 'time', axisLabel: { color: '#94a3b8', fontSize: 11 } },
      yAxis: { type: 'category', data: machines, axisLabel: { color: '#f1f5f9', fontSize: 12, fontWeight: 600 },
        inverse: true },
      dataZoom: [
        { type: 'slider', xAxisIndex: 0, bottom: 10, height: 20, borderColor: '#334155',
          backgroundColor: '#1e293b', fillerColor: 'rgba(59,130,246,0.15)',
          handleStyle: { color: '#3b82f6' }, textStyle: { color: '#94a3b8' } },
        { type: 'inside', xAxisIndex: 0 },
      ],
      series: [
        { type: 'custom', name: '生产任务', renderItem: renderGanttBar, encode: { x: [1, 2], y: 0 },
          data: seriesData },
        { type: 'custom', name: '维保窗口', renderItem: renderGanttBar, encode: { x: [1, 2], y: 0 },
          data: maintData },
      ],
    });

    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [data]);

  // Build legend
  const products = data?.tasks ? [...new Set(data.tasks.map(t => t.product_type))] : [];

  return (
    <div>
      <div className="page-header">
        <h2>排程甘特图</h2>
      </div>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
        {products.map(p => (
          <div key={p} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <span style={{ width: 12, height: 12, borderRadius: 3, background: PRODUCT_COLORS[p] || '#64748b', display: 'inline-block' }} />
            {p}
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <span style={{ width: 12, height: 12, borderRadius: 3, background: '#475569', border: '1px dashed #64748b', display: 'inline-block' }} />
          维保窗口
        </div>
      </div>
      <div className="card">
        {data ? (
          <div ref={chartRef} className="gantt-wrapper" style={{ height: 520 }} />
        ) : (
          <div className="loading">加载甘特图数据...</div>
        )}
      </div>
    </div>
  );
}
