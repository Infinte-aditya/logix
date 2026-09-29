import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/logs': 'http://localhost:8001',
      '/health': 'http://localhost:8001',
    },
  },
})
