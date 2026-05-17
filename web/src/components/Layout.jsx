import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { getMe } from '../api/client';

export default function Layout() {
  const [user, setUser] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    getMe().then(r => setUser(r.data)).catch(() => navigate('/login'));
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('aps_token');
    navigate('/login');
  };

  const links = [
    { to: '/', icon: '⊞', label: 'Dashboard' },
    { to: '/gantt', icon: '☷', label: 'Gantt Chart' },
    { to: '/orders', icon: '📋', label: 'Orders' },
    { to: '/machines', icon: '⚙️', label: 'Machines' },
    { to: '/setup', icon: '🔲', label: 'Setup Matrix' },
    { to: '/reports', icon: '📊', label: 'Reports' },
  ];

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '28px', height: '28px', background: 'linear-gradient(135deg, #38bdf8, #818cf8)', borderRadius: '6px' }}></div>
          <h1 style={{ fontSize: '18px', background: 'none', WebkitTextFillColor: '#fff', letterSpacing: '0' }}>APS System</h1>
        </div>
        <nav className="sidebar-nav">
          {links.map(l => (
            <NavLink key={l.to} to={l.to} end className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon" style={{ fontSize: '16px' }}>{l.icon}</span>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button className="btn btn-ghost" style={{width:'100%', fontSize:13}} onClick={handleLogout}>Logout</button>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div className="topbar-left">
            <button className="btn-icon" style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '20px', cursor: 'pointer' }}>☰</button>
          </div>
          <div className="topbar-right" style={{ display: 'flex', alignItems: 'center', gap: '20px', color: '#94a3b8', fontSize: '18px' }}>
            <span style={{ cursor: 'pointer' }}>⚙️</span>
            <span style={{ cursor: 'pointer' }}>🔔</span>
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
