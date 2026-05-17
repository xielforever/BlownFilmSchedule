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

    // Create Canvas Pattern for Setup & Maintenance
    const patternCanvas = document.createElement('canvas');
    patternCanvas.width = 10;
    patternCanvas.height = 10;
    const ctx = patternCanvas.getContext('2d');
    ctx.fillStyle = '#1e293b'; // match card background
    ctx.fillRect(0, 0, 10, 10);
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, 10);
    ctx.lineTo(10, 0);
    ctx.stroke();
    const hatchPattern = { image: patternCanvas, repeat: 'repeat' };

    // Group tasks by product type for native ECharts Legend
    const seriesByProduct = {};
    const setupData = [];
    
    data.tasks.forEach(t => {
      const start = new Date(t.start).getTime();
      const end = new Date(t.end).getTime();
      const yIdx = machines.indexOf(t.machine_id);
      const color = PRODUCT_COLORS[t.product_type] || '#64748b';
      
      if (t.setup_mins > 0 && t.setup_start) {
        const setupStart = new Date(t.setup_start).getTime();
        setupData.push({
          value: [yIdx, setupStart, start, { ...t, is_setup: true }],
          itemStyle: { color: hatchPattern, borderColor: '#475569', borderWidth: 1 },
        });
      }

      if (!seriesByProduct[t.product_type]) seriesByProduct[t.product_type] = [];
      seriesByProduct[t.product_type].push({
        value: [yIdx, start, end, t],
        itemStyle: { color, borderRadius: 3 },
      });
    });

    const maintData = data.maintenance.map(m => {
      const yIdx = machines.indexOf(m.machine_id);
      if (yIdx < 0) return null;
      return {
        value: [yIdx, new Date(m.start).getTime(), new Date(m.end).getTime(), m],
        itemStyle: { color: hatchPattern, borderColor: '#ef4444', borderWidth: 1 },
      };
    }).filter(Boolean);

    function renderGanttBar(params, api) {
      const yIdx = api.value(0);
      const start = api.coord([api.value(1), yIdx]);
      const end = api.coord([api.value(2), yIdx]);
      const height = api.size([0, 1])[1] * 0.6;
      const width = Math.max(end[0] - start[0], 1.5); // Ensure at least 1.5px to be visible
      const d = api.value(3);
      
      const style = api.style();
      // Explicitly set text boundaries so truncation works and prevents bleeding into next order!
      if (!d.is_setup && !d.reason && width > 40) {
         style.text = d.order_id;
         style.textFill = '#ffffff';
         style.fontSize = 10;
         style.width = width - 8; // Force bounding box for truncate
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
        shape: { ...rectShape, r: Math.min(2, rectShape.width / 2) }, // Safe border radius
        style: style,
      };
    }

    const seriesList = Object.keys(seriesByProduct).map(p => ({
      type: 'custom',
      name: p,
      renderItem: renderGanttBar,
      encode: { x: [1, 2], y: 0 },
      data: seriesByProduct[p],
      emphasis: { focus: 'none' }
    }));

    seriesList.push({
      type: 'custom', name: '换产准备', renderItem: renderGanttBar, encode: { x: [1, 2], y: 0 },
      data: setupData
    });
    seriesList.push({
      type: 'custom', name: '维保窗口', renderItem: renderGanttBar, encode: { x: [1, 2], y: 0 },
      data: maintData
    });

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
      legend: {
        top: 0, left: 0,
        textStyle: { color: '#cbd5e1', fontSize: 13 },
        itemWidth: 14, itemHeight: 14, icon: 'roundRect', type: 'scroll'
      },
      grid: { top: 60, right: 40, bottom: 60, left: 100 },
      xAxis: { 
        type: 'time', 
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        splitLine: { show: true, lineStyle: { type: 'dashed', opacity: 0.15, color: '#334155' } }
      },
      yAxis: { 
        type: 'category', data: machines, 
        axisLabel: { color: '#f1f5f9', fontSize: 12, fontWeight: 600 },
        inverse: true,
        splitLine: { show: true, lineStyle: { opacity: 0.1, color: '#334155' } }
      },
      dataZoom: [
        { type: 'slider', xAxisIndex: 0, bottom: 10, height: 20, borderColor: '#334155',
          backgroundColor: '#1e293b', fillerColor: 'rgba(59,130,246,0.15)',
          handleStyle: { color: '#3b82f6' }, textStyle: { color: '#94a3b8' }, showDetail: true },
        { type: 'inside', xAxisIndex: 0 }
      ],
      series: seriesList,
    }, true);

    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [data]);

  const dynamicHeight = data && data.tasks ? Math.max(500, [...new Set(data.tasks.map(t => t.machine_id))].length * 60 + 120) : 520;

  return (
    <div>
      <div className="page-header">
        <h2>排程甘特图</h2>
      </div>
      <div className="card">
        {data ? (
          <div ref={chartRef} className="gantt-wrapper" style={{ height: dynamicHeight }} />
        ) : (
          <div className="loading">加载甘特图数据...</div>
        )}
      </div>
    </div>
  );
}
