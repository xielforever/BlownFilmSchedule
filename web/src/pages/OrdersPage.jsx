import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getOrders, screenOrders } from '../api/client';
import { screeningDetailLines } from './ordersViewModel';

const PAGE_SIZE = 50;
const statusOptions = ['', 'PENDING', 'SCHEDULED', 'IN_PRODUCTION', 'COMPLETED', 'CANCELLED'];
const statusLabels = {
  PENDING: '待排',
  SCHEDULED: '已排',
  IN_PRODUCTION: '生产中',
  COMPLETED: '已完成',
  CANCELLED: '已取消',
};
const screeningLabels = {
  ready: '可排',
  risk: '风险',
  blocked: '阻断',
};

function ScreeningBadge({ item }) {
  if (!item) return <span style={{ color: 'var(--text-muted)' }}>计算中</span>;
  const cls = {
    ready: 'badge-scheduled',
    risk: 'badge-urgent',
    blocked: 'badge-pending',
  }[item.screening_status] || 'badge-pending';
  const detailLines = screeningDetailLines(item);
  return (
    <div className="screening-cell">
      <span className={`badge ${cls}`} title={item.root_cause}>
        {screeningLabels[item.screening_status] || item.screening_status}
      </span>
      {detailLines.map(line => <small key={line}>{line}</small>)}
    </div>
  );
}

function StatusBadge({ status }) {
  const cls = {
    PENDING: 'badge-pending',
    SCHEDULED: 'badge-scheduled',
    IN_PRODUCTION: 'badge-production',
    COMPLETED: 'badge-completed',
    CANCELLED: 'badge-pending',
  };
  return <span className={`badge ${cls[status] || 'badge-pending'}`}>{statusLabels[status] || status}</span>;
}

export default function OrdersPage() {
  const [orders, setOrders] = useState([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState('');
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [screeningItems, setScreeningItems] = useState([]);
  const [screeningError, setScreeningError] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(async () => {
      if (cancelled) return;
      setLoading(true);
      setError('');
      setScreeningError('');
      try {
        const r = await getOrders({
          status: filter || undefined,
          q: debouncedQuery || undefined,
          page,
          size: PAGE_SIZE,
        });
        if (cancelled) return;
        const nextOrders = r.data.items || [];
        setOrders(nextOrders);
        setTotal(r.data.total);
        if (!nextOrders.length) {
          setScreeningItems([]);
          return;
        }
        try {
          const screeningRes = await screenOrders({
            scope: 'selected',
            order_ids: nextOrders.map(order => order.order_id),
          });
          if (!cancelled) setScreeningItems(screeningRes.data.items || []);
        } catch (screeningErr) {
          if (!cancelled) {
            setScreeningItems([]);
            setScreeningError(screeningErr.response?.data?.detail || screeningErr.message || '订单初筛失败');
          }
        }
      } catch (err) {
        if (cancelled) return;
        setError(err.response?.data?.detail || err.message || '订单加载失败');
        setScreeningItems([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [filter, debouncedQuery, page]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);
  const screeningByOrderId = useMemo(
    () => new Map(screeningItems.map(item => [item.order_id, item])),
    [screeningItems],
  );
  const firstRow = total ? (page - 1) * PAGE_SIZE + 1 : 0;
  const lastRow = Math.min(total, page * PAGE_SIZE);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>订单管理 <span style={{ fontSize: 14, color: 'var(--text-muted)', fontWeight: 400 }}>({total} 条)</span></h2>
          <p className="page-subtitle">{firstRow}-{lastRow} / {total}，可搜索订单、产品、客户或机台</p>
        </div>
        <Link className="btn btn-primary" to="/config?tab=orders">配置订单</Link>
      </div>

      <div className="page-toolbar">
        <input
          className="search-input"
          value={query}
          placeholder="搜索订单、产品、客户、机台"
          onChange={e => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
        <div className="segmented-control">
          {statusOptions.map(status => (
            <button
              key={status}
              className={filter === status ? 'active' : ''}
              onClick={() => {
                setFilter(status);
                setPage(1);
              }}
            >
              {status ? statusLabels[status] || status : '全部'}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="config-status error">{error}</div>}
      {screeningError && <div className="config-status error">{screeningError}</div>}

      <div className="card table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>订单号</th>
              <th>产品类型</th>
              <th>规格</th>
              <th>重量</th>
              <th>客户</th>
              <th>交期</th>
              <th>状态</th>
              <th>初筛</th>
              <th>机台</th>
              <th>废料</th>
              <th>实际投料</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {!loading && orders.map(o => (
              <tr key={o.order_id} className="fade-in">
                <td style={{ fontWeight: 600 }}>{o.order_id}</td>
                <td>{o.product_type}</td>
                <td>{o.target_width}mm × {o.target_thickness}um</td>
                <td>{o.total_quantity_kg} kg</td>
                <td>
                  {o.customer_class === 'VIP' && <span className="badge badge-vip" style={{ marginRight: 4 }}>VIP</span>}
                  {o.order_class === 'URGENT' && <span className="badge badge-urgent">加急</span>}
                  {o.order_class === 'SAMPLE' && <span className="badge badge-urgent">样品</span>}
                  {o.order_class === 'NORMAL' && o.customer_class !== 'VIP' && <span style={{ color: 'var(--text-muted)' }}>标准</span>}
                </td>
                <td style={{ fontSize: 12 }}>{o.due_date ? new Date(o.due_date).toLocaleDateString('zh-CN') : '-'}</td>
                <td><StatusBadge status={o.status} /></td>
                <td><ScreeningBadge item={screeningByOrderId.get(o.order_id)} /></td>
                <td style={{ fontWeight: 500 }}>{o.assigned_machine || '-'}</td>
                <td>{o.scrap_kg > 0 ? `${o.scrap_kg} kg` : '-'}</td>
                <td style={{ fontWeight: 600, color: o.actual_material_kg > 0 ? 'var(--accent-green)' : 'inherit' }}>
                  {o.actual_material_kg > 0 ? `${o.actual_material_kg} kg` : '-'}
                </td>
                <td><Link className="btn btn-ghost btn-small" to={`/config?tab=orders&order=${encodeURIComponent(o.order_id)}`}>编辑</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <div className="config-empty">订单加载中...</div>}
        {!loading && !orders.length && <div className="config-empty">当前筛选条件下没有订单。</div>}
        <div className="table-footer">
          <span>{firstRow}-{lastRow} / 共 {total} 条</span>
          <div className="pager">
            <button className="btn btn-ghost btn-small" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>上一页</button>
            <span>第 {page} / {totalPages} 页</span>
            <button className="btn btn-ghost btn-small" disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>下一页</button>
          </div>
        </div>
      </div>
    </div>
  );
}
