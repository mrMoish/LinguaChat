import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png'],
      manifest: {
        name: 'ИИ Переводчик и Ассистент',
        short_name: 'Переводчик',
        description: 'Перевод текста, фото, PDF и голосовых сообщений с мини-уроками',
        theme_color: '#ffffff',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          {
            src: 'pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png'
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any maskable' // Для красивой иконки на Android
          }
        ]
      },
      workbox: {
        clientsClaim: true,    // Мгновенно активирует новую версию
        skipWaiting: true,     // Не ждет закрытия вкладок для обновления
        runtimeCaching: [
          {
            // Кэшируем запросы к бэкенду (Network First)
            urlPattern: /^https:\/\/.*\.onrender\.com\/api\/.*/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              networkTimeoutSeconds: 10
            }
          },
          {
            // Кэшируем шрифты и стили (Cache First)
            urlPattern: /\.(?:js|css|woff2?|png|jpg|jpeg|svg|gif)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'assets-cache',
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 60 * 60 * 24 * 30
              }
            }
          }
        ]
      }
    })
  ],
  server: {
    allowedHosts: true, // Разрешаем доступ через ngrok
    proxy: {
      '/api': 'http://localhost:8000' // Обязательно оставляем прокси для бэкенда!
    }
  }
})