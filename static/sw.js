/* ═══════════════════════════════════════════════════════
   sw.js — Service Worker للعمل أوفلاين
   نظام المحاسبة SaaS — v2 (Background Sync + Queue)
═══════════════════════════════════════════════════════ */

const CACHE_NAME    = 'hisab-v2';
const STATIC_ASSETS = [
  '/',
  '/static/css/main.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/dashboard',
  '/purchases',
  '/contacts',
  '/accounting',
  '/analytics',
  '/offline',
];

const DB_NAME    = 'hisab-offline';
const STORE_NAME = 'sync-queue';

/* ─── فتح IndexedDB داخل SW ──────────────────────────── */
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = e => {
      e.target.result.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
    };
    req.onsuccess  = e => resolve(e.target.result);
    req.onerror    = e => reject(e.target.error);
  });
}

/* ─── تثبيت ──────────────────────────────────────────── */
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      cache.addAll(STATIC_ASSETS).catch(() => {})
    )
  );
});

/* ─── تفعيل: حذف الكاشات القديمة ────────────────────── */
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

/* ─── اعتراض الطلبات ────────────────────────────────── */
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  if (!url.protocol.startsWith('http')) return;

  /* POST للـ API — خزّن في Queue إذا أوفلاين */
  if (request.method === 'POST' && url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request.clone()).catch(async () => {
        const db    = await openDB();
        const body  = await request.clone().text();
        const tx    = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).add({
          url:     request.url,
          method:  request.method,
          body:    body,
          headers: Object.fromEntries(request.headers.entries()),
          ts:      Date.now(),
        });
        return new Response(
          JSON.stringify({ success: false, offline: true,
            message: 'حُفظ في قائمة الانتظار — سيُرسَل عند عودة الاتصال' }),
          { status: 202, headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  /* الـ static assets: Cache First */
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response.ok) {
            caches.open(CACHE_NAME).then(c => c.put(request, response.clone()));
          }
          return response;
        }).catch(() => cached || new Response('', { status: 503 }));
      })
    );
    return;
  }

  /* GET — تجاهل طلبات غير HTML */
  if (request.method !== 'GET') return;

  /* الصفحات: Network First → Cache → Offline */
  event.respondWith(
    fetch(request)
      .then(response => {
        if (response.ok) {
          caches.open(CACHE_NAME).then(c => c.put(request, response.clone()));
        }
        return response;
      })
      .catch(() =>
        caches.match(request).then(cached =>
          cached || caches.match('/offline')
        )
      )
  );
});

/* ─── Background Sync ────────────────────────────────── */
self.addEventListener('sync', async event => {
  if (event.tag !== 'offline-queue') return;

  event.waitUntil(
    (async () => {
      const db    = await openDB();
      const tx    = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const items = await new Promise((res, rej) => {
        const req = store.getAll();
        req.onsuccess = e => res(e.target.result);
        req.onerror   = e => rej(e.target.error);
      });

      for (const item of items) {
        try {
          const response = await fetch(item.url, {
            method:  item.method,
            body:    item.body,
            headers: { ...item.headers, 'Content-Type': 'application/json' },
          });
          if (response.ok) {
            const tx2 = db.transaction(STORE_NAME, 'readwrite');
            tx2.objectStore(STORE_NAME).delete(item.id);
            // إبلاغ العملاء
            self.clients.matchAll().then(clients =>
              clients.forEach(c => c.postMessage({ type: 'SYNC_DONE', url: item.url }))
            );
          }
        } catch (e) {
          // سيُعاد المحاولة في المرة القادمة
        }
      }
    })()
  );
});

/* ─── رسائل من الصفحة ────────────────────────────────── */
self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();

  if (event.data === 'TRIGGER_SYNC') {
    self.registration.sync.register('offline-queue').catch(() => {});
  }
});
