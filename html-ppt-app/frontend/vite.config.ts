import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/outputs': 'http://127.0.0.1:8000',
    },
  },
  preview: {
    port: 8080,
    host: '0.0.0.0',
    allowedHosts: ['.railway.app', 'localhost', '127.0.0.1'],
  },
})
