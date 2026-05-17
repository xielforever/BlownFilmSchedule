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
export const triggerSchedule = () => api.post('/schedule/trigger');
export const getOrders = (params) => api.get('/orders', { params });
export const getMachines = () => api.get('/machines');
export const getMachineTimeline = (id) => api.get(`/machines/${id}/timeline`);

export default api;
