import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5273,
    proxy: {
      '/api': 'http://127.0.0.1:6200',
      '/media': 'http://127.0.0.1:6200',
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
