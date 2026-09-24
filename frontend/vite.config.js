import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const backendOrigin = process.env.FA_API_ORIGIN
  || `http://127.0.0.1:${process.env.FA_PORT || 8000}`

export default defineConfig(({ mode }) => {
  const manualChunks = mode === 'docker'
    ? (id) => {
        if (!id.includes('/node_modules/')) return undefined
        if (id.includes('/node_modules/element-plus/') || id.includes('/node_modules/@element-plus/')) {
          if (id.includes('/node_modules/element-plus/es/components/table/')) return 'element-plus-table'
          return 'element-plus'
        }
        if (
          id.includes('/node_modules/@vue/')
          || id.includes('/node_modules/vue/')
          || id.includes('/node_modules/vue-router/')
        ) {
          return 'vue-vendor'
        }
        return 'vendor'
      }
    : undefined

  return {
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
      rollupOptions: manualChunks ? { output: { manualChunks } } : undefined,
    },
  }
})
