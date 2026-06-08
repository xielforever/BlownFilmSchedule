import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.APS_API_BASE_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': apiTarget,
    },
  },
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('echarts') || id.includes('zrender')) {
              return 'echarts';
            }
            if (id.includes('react') || id.includes('react-router-dom')) {
              return 'react-vendor';
            }
            return 'vendor';
          }
          if (id.includes('/src/pages/ScheduleWorkbench')) {
            return 'page-workbench';
          }
          if (id.includes('/src/pages/Dashboard')) {
            return 'page-dashboard';
          }
          if (id.includes('/src/pages/GanttPage')) {
            return 'page-gantt';
          }
          if (id.includes('/src/pages/ConfigPage')) {
            return 'page-config';
          }
        }
      }
    }
  }
})

