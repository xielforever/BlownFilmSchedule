import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import Dashboard from './pages/Dashboard';
import GanttPage from './pages/GanttPage';
import OrdersPage from './pages/OrdersPage';
import MachinesPage from './pages/MachinesPage';
import ConfigPage from './pages/ConfigPage';
import './index.css';

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('aps_token');
  return token ? children : <Navigate to="/login" />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Dashboard />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="gantt" element={<GanttPage />} />
          <Route path="orders" element={<OrdersPage />} />
          <Route path="machines" element={<MachinesPage />} />
          <Route path="config" element={<ConfigPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
