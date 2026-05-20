import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { getMe } from '../api/client';

export default function Layout() {
  const [user, setUser] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    getMe().then(r => setUser(r.data)).catch(() => navigate('/login'));
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem('aps_token');
    navigate('/login');
  };

  const links = [
    { to: '/', icon: '仪', label: '仪表盘' },
    { to: '/workbench', icon: '排', label: '排程工作台' },
    { to: '/gantt', icon: '甘', label: 'Gantt 图' },
    { to: '/orders', icon: '单', label: '订单' },
    { to: '/machines', icon: '机', label: '机台' },
    { to: '/config', icon: '配', label: '配置' },
  ];

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '28px', height: '28px', background: 'linear-gradient(135deg, #38bdf8, #818cf8)', borderRadius: '6px' }} />
          <h1 style={{ fontSize: '18px', background: 'none', WebkitTextFillColor: '#fff', letterSpacing: '0' }}>APS 排程系统</h1>
        </div>
        <nav className="sidebar-nav">
          {links.map(link => (
            <NavLink key={link.to} to={link.to} end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon" style={{ fontSize: '13px', fontWeight: 700 }}>{link.icon}</span>
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button className="btn btn-ghost" style={{ width: '100%', fontSize: 13 }} onClick={handleLogout}>退出登录</button>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-text">APS 排程工作台</span>
          </div>
          <div className="topbar-right" style={{ display: 'flex', alignItems: 'center', gap: '20px', color: '#94a3b8', fontSize: '18px' }}>
            <NavLink className="topbar-link" to="/config">设置</NavLink>
            <span className="topbar-text">告警</span>
            <div className="avatar" style={{ width: '32px', height: '32px', borderRadius: '50%', background: '#38bdf8', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', fontWeight: 'bold' }}>
              {user ? user.name[0] : 'U'}
            </div>
          </div>
        </header>
        <div className="page-content" style={{ padding: '32px', flex: 1 }}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
