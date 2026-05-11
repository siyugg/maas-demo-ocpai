import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/chat': 'http://localhost:8080',
      '/weather': 'http://localhost:8080',
      '/admin': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
    },
  },
})
