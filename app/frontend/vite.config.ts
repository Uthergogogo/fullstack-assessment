import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const backend = process.env.PDP_API_ORIGIN ?? 'http://127.0.0.1:8000'
const proxy = { '/api': backend, '/images': backend }

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', strictPort: true, proxy },
  preview: { host: '127.0.0.1', strictPort: true, proxy },
  test: { environment: 'jsdom' },
})
