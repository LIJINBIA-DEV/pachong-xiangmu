import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: '../api/webui',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    watch: {
      // Ignore crawler output, while still watching src/components/data.
      ignored: [
        ...['data', 'logs', 'browser_data'].map((name) => `${path.resolve(__dirname, '..', name).replace(/\\/g, '/')}/**`),
        '**/*.xlsx', '**/*.jsonl', '**/*.tmp',
      ],
    },
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${process.env.MEDIACRAWLER_API_PORT || '18080'}`,
        changeOrigin: true,
        ws: true,  // 启用 WebSocket 代理
      },
    },
  },
})
