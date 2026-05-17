import { useState, useEffect } from 'react';
import { getOrders } from '../api/client';

function StatusBadge({ status }) {
  const cls = { PENDING: 'badge-pending', SCHEDULED: 'badge-scheduled',
    IN_PRODUCTION: 'badge-production', COMPLETED: 'badge-completed', CANCELLED: 'badge-pending' };
  const labels = { PENDING: '待排', SCHEDULED: '已排', IN_PRODUCTION: '生产中', COMPLETED: '已完', CANCELLED: '已取消' };
  return <span className={`badge ${cls[status] || 'badge-pending'}`}>{labels[status] || status}</span>;
}

export default function OrdersPage() {
  const [orders, setOrders] = useState([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    getOrders({ status: filter || undefined }).then(r => {
      setOrders(r.data.items);
      setTotal(r.data.total);
    });
  }, [filter]);

  return (
    <div>
      <div className="page-header">
        <h2>订单管理 <span style={{ fontSize: 14, color: 'var(--text-muted)', fontWeight: 400 }}>({total} 笔)</span></h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {['', 'PENDING', 'SCHEDULED', 'COMPLETED'].map(s => (
            <button key={s} className={`btn ${filter === s ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => setFilter(s)} style={{ fontSize: 12, padding: '6px 14px' }}>
              {s || '全部'}
            </button>
          ))}
        </div>
      </div>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>订单号</th><th>产品类型</th><th>规格</th><th>重量</th>
              <th>客户</th><th>交期</th><th>状态</th>
              <th>机台</th><th>废料</th><th>实际投料</th>
            </tr>
          </thead>
          <tbody>
            {orders.map(o => (
              <tr key={o.order_id} className="fade-in">
                <td style={{ fontWeight: 600 }}>{o.order_id}</td>
                <td>{o.product_type}</td>
                <td>{o.target_width}mm × {o.target_thickness}μm</td>
                <td>{o.total_quantity_kg} kg</td>
                <td>
                  {o.customer_class === 'VIP' && <span className="badge badge-vip" style={{ marginRight: 4 }}>VIP</span>}
                  {o.order_class === 'URGENT' && <span className="badge badge-urgent">URGENT</span>}
                  {o.order_class === 'SAMPLE' && <span className="badge badge-urgent">SAMPLE</span>}
                  {o.order_class === 'NORMAL' && o.customer_class !== 'VIP' && <span style={{ color: 'var(--text-muted)' }}>标准</span>}
                </td>
                <td style={{ fontSize: 12 }}>{o.due_date ? new Date(o.due_date).toLocaleDateString('zh-CN') : '-'}</td>
                <td><StatusBadge status={o.status} /></td>
                <td style={{ fontWeight: 500 }}>{o.assigned_machine || '-'}</td>
                <td>{o.scrap_kg > 0 ? `${o.scrap_kg} kg` : '-'}</td>
                <td style={{ fontWeight: 600, color: o.actual_material_kg > 0 ? 'var(--accent-green)' : 'inherit' }}>
                  {o.actual_material_kg > 0 ? `${o.actual_material_kg} kg` : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
