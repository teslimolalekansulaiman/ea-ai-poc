import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' so the built assets resolve no matter where FastAPI serves them from.
// dev proxy sends /api to the running FastAPI service.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist' },
  server: { proxy: { '/api': 'http://127.0.0.1:8099' } },
})
