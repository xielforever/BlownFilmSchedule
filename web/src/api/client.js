import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('aps_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('aps_token');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export const login = (username, password) =>
  api.post('/auth/login', new URLSearchParams({ username, password }));
export const getMe = () => api.get('/auth/me');
export const getDashboard = () => api.get('/dashboard/summary');
export const getHeatmap = (days = 7) => api.get(`/dashboard/utilization-heatmap?days=${days}`);
export const getGantt = (runId) => api.get('/schedule/gantt' + (runId ? `?run_id=${runId}` : ''));
export const getRuns = () => api.get('/schedule/runs');
export const getScheduleDiagnostics = (params) => api.get('/schedule/diagnostics', { params });
export const getScheduleStatus = () => api.get('/schedule/status');
export const triggerSchedule = () => api.post('/schedule/trigger');
export const getOrders = (params) => api.get('/orders', { params });
export const updateOrder = (id, payload) => api.patch(`/orders/${id}`, payload);
export const getMachines = () => api.get('/machines');
export const updateMachine = (id, payload) => api.patch(`/machines/${id}`, payload);
export const getMachineTimeline = (id) => api.get(`/machines/${id}/timeline`);
export const getRulesSummary = () => api.get('/rules/summary');
export const updateMaterialSwitchRule = (id, payload) => api.patch(`/rules/material-switch/${id}`, payload);
export const createMaterialSwitchRule = (payload) => api.post('/rules/material-switch', payload);
export const deleteMaterialSwitchRule = (id) => api.delete(`/rules/material-switch/${id}`);
export const updateGmpRule = (id, payload) => api.patch(`/rules/gmp-clearance/${id}`, payload);
export const createGmpRule = (payload) => api.post('/rules/gmp-clearance', payload);
export const deleteGmpRule = (id) => api.delete(`/rules/gmp-clearance/${id}`);
export const updateSpecRule = (id, payload) => api.patch(`/rules/spec-change/${id}`, payload);
export const createSpecRule = (payload) => api.post('/rules/spec-change', payload);
export const deleteSpecRule = (id) => api.delete(`/rules/spec-change/${id}`);
export const updateMaintenanceWindow = (id, payload) => api.patch(`/rules/maintenance/${id}`, payload);
export const createMaintenanceWindow = (payload) => api.post('/rules/maintenance', payload);
export const deleteMaintenanceWindow = (id) => api.delete(`/rules/maintenance/${id}`);

export default api;
