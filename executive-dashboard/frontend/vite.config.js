import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['ifc_logo.png'],
      manifest: {
        name: 'Sup — IFC Executive Dashboard',
        short_name: 'Sup',
        description: 'IFC Roofing Executive Dashboard',
        theme_color: '#0f172a',
        background_color: '#0f172a',
        display: 'standalone',
        start_url: '/',
        icons: [
          {
            src: '/ifc_logo.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: '/ifc_logo.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any maskable',
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8091',
      '/auth': 'http://127.0.0.1:8091',
      '/health': 'http://127.0.0.1:8091',
    },
  },
})
