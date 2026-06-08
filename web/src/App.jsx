import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import './index.css';

const LoginPage = lazy(() => import('./pages/LoginPage'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const GanttPage = lazy(() => import('./pages/GanttPage'));
const OrdersPage = lazy(() => import('./pages/OrdersPage'));
const MachinesPage = lazy(() => import('./pages/MachinesPage'));
const ConfigPage = lazy(() => import('./pages/ConfigPage'));
const ScheduleWorkbench = lazy(() => import('./pages/ScheduleWorkbench'));

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('aps_token');
  return token ? children : <Navigate to="/login" />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="route-loading">正在加载...</div>}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
            <Route index element={<Dashboard />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="workbench" element={<ScheduleWorkbench />} />
            <Route path="gantt" element={<GanttPage />} />
            <Route path="orders" element={<OrdersPage />} />
            <Route path="machines" element={<MachinesPage />} />
            <Route path="config" element={<ConfigPage />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
