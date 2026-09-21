// Service Worker for Antigravity / HiddiBot Progressive Web App (PWA)
const CACHE_NAME = 'hiddibot-pwa-v2';
const STATIC_ASSETS = [
  '/',
  '/avatars/Logo.webp',
  '/avatars/favicon.ico',
  '/manifest.json'
];

// 1. نصب سرویس ورکر و کش اولیه فایل‌های ضروری
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('PWA Pre-cache non-fatal warning:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// 2. فعال‌سازی و پاکسازی کش‌های قدیمی
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 3. استراتژی واکشی هوشمند (Network-First برای صفحات و APIها، Cache-First برای استاتیک)
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // درخواست‌های کراس‌اورجین (مانند تلگرام و CDNها) نباید توسط سرویس ورکر رهگیری یا مسدود شوند
  if (url.origin !== self.location.origin) {
    return;
  }

  // فقط درخواست‌های GET کش شوند
  if (req.method !== 'GET') {
    return;
  }

  // فایل‌های استاتیک و تصاویر (Cache-First)
  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/avatars/') || url.pathname.includes('/css/') || url.pathname.includes('/fonts/')) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // صفحات وب و پورتال (Network-First با بازگشت به کش در زمان قطعی)
  event.respondWith(
    fetch(req)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const clone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
        }
        return networkResponse;
      })
      .catch(() => {
        return caches.match(req).then((cached) => {
          if (cached) return cached;
          if (req.headers.get('accept') && req.headers.get('accept').includes('text/html')) {
            return caches.match('/');
          }
        });
      })
  );
});
