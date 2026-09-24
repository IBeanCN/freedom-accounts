import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const backendOrigin = process.env.FA_API_ORIGIN
  || `http://127.0.0.1:${process.env.FA_PORT || 8000}`

export default defineConfig({
  base: '/static/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': backendOrigin,
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
