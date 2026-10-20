import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Geliştirmede /api isteklerini FastAPI'ye yönlendir.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
