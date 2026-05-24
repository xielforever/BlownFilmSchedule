import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login } from '../api/client';

function formatLoginError(err) {
  const detail = err.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const firstMessage = detail.find(item => item?.message || item?.msg);
    return firstMessage?.message || firstMessage?.msg || '登录失败';
  }
  if (detail && typeof detail === 'object') {
    return detail.message || detail.msg || '登录失败';
  }
  return err.message || '登录失败';
}

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await login(username, password);
      localStorage.setItem('aps_token', res.data.access_token);
      navigate('/');
    } catch (err) {
      setError(formatLoginError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login-card fade-in" onSubmit={handleSubmit}>
        <h1>APS 智能排程系统</h1>
        <p>医疗PE薄膜吹膜机排程管理平台</p>
        <div className="form-group">
          <label>用户名</label>
          <input type="text" value={username} onChange={e => setUsername(e.target.value)}
                 placeholder="用户名，例如 admin / planner / viewer" autoFocus />
        </div>
        <div className="form-group">
          <label>密码</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                 placeholder="输入密码" />
        </div>
        <button className="btn btn-primary login-btn" type="submit" disabled={loading}>
          {loading ? '登录中...' : '登录'}
        </button>
        {error && <div className="login-error">{error}</div>}
      </form>
    </div>
  );
}
