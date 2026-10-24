import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Geliştirmede /api isteklerini FastAPI'ye yönlendir.
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
    // UTC ile yerel saat farkı testlerde görünsün diye sabit bir saat dilimi (UTC+3).
    env: { TZ: 'Europe/Istanbul' },
  },
})
