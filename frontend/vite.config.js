import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Custom plugin for detailed error logging in dev terminal
const detailedErrorLogger = {
  name: 'detailed-error-logger',
  apply: 'serve',
  config() {
    return {
      logLevel: 'info',
    };
  },
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.method === 'POST' && req.url === '/__client-error') {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', () => {
          try {
            const errorData = JSON.parse(body);
            console.error('\n[CLIENT ERROR]');
            console.error('  Time:', errorData.timestamp);
            console.error('  URL:', errorData.url);
            console.error('  User Agent:', errorData.userAgent);
            console.error('  Args:', JSON.stringify(errorData.args, null, 2));
            console.error('  Stack:', errorData.stack);
            console.error('  Referer:', req.headers.referer);
            console.error('  Origin:', req.headers.origin);
            console.error('');
          } catch (e) {
            console.error('[CLIENT ERROR] Failed to parse:', e.message);
          }
          res.statusCode = 200;
          res.end('ok');
        });
        return;
      }
      next();
    });
  },
  buildStart() {
    console.log('\n[DEV] Build started at', new Date().toISOString());
  },
  buildEnd(err) {
    if (err) {
      console.error('\n[DEV] Build error:', err);
    } else {
      console.log('\n[DEV] Build completed successfully');
    }
  },
  handleHotUpdate(ctx) {
    console.log('\n[HMR] Hot update detected for:', ctx.file);
    if (ctx.modules) {
      ctx.modules.forEach((mod) => {
        if (mod.id) console.log('[HMR] Affected module:', mod.id);
      });
    }
  },
  transformError(err) {
    console.error('\n[DEV] Transform error:');
    console.error('  Message:', err.message);
    console.error('  File:', err.id || 'unknown');
    console.error('  Stack:', err.stack);
  },
};

export default defineConfig({
  plugins: [
    react(),
    detailedErrorLogger,
    {
      name: 'error-logger',
      configureServer(server) {
        server.middlewares.use((err, req, res, next) => {
          console.error('\n[SERVER ERROR]', err);
          next(err);
        });
      },
      handleHotUpdate(ctx) {
        console.log('[HMR] Update:', ctx.file);
        for (const module of ctx.modules) {
          if (module.id) {
            console.log('[HMR] Module:', module.id);
          }
        }
      },
    },
    VitePWA({
      registerType: 'autoUpdate', // Автоматически проверяет и применяет обновления
      includeAssets: ['favicon.ico', 'apple-touch-icon.png'],
      manifest: {
        name: 'TraChat: AI Translator and Language Friend',
        short_name: 'TraChat',
        description: 'AI Translator and Language Friend',
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
            purpose: 'any maskable'
          }
        ]
      },
      workbox: {
        // КРИТИЧЕСКИ ВАЖНО ДЛЯ ОБНОВЛЕНИЙ PWA:
        clientsClaim: true,
        skipWaiting: true, // Принудительно активирует новый SW сразу
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            // HTML всегда грузим с сети (NetworkFirst), чтобы получить свежие ссылки на JS/CSS
            urlPattern: ({ request }) => request.mode === 'navigate',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'html-cache',
              networkTimeoutSeconds: 3
            }
          },
          {
            // Хэшированные ассеты кэшируем навсегда (CacheFirst), так как имя файла меняется при билде
            urlPattern: /\.(?:js|css|woff2?|png|jpg|jpeg|svg|gif)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'assets-cache',
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 60 * 60 * 24 * 30 // 30 дней
              }
            }
          }
        ]
      }
    })
  ],
  server: {
    allowedHosts: true,
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})