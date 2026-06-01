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
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('echarts') || id.includes('zrender')) {
              return 'echarts';
            }
            return 'vendor';
          }
        }
      }
    }
  }
})

