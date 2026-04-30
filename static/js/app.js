// app.js — إدارة القائمة الجانبية + PWA Offline Queue

document.addEventListener('DOMContentLoaded', function () {
  // تمييز الرابط النشط
  const currentPath = window.location.pathname;
  document.querySelectorAll('.sidebar-nav a').forEach(link => {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('active');
    }
  });

  // زر القائمة للموبايل
  const hamburger = document.querySelector('.hamburger');
  const sidebar   = document.querySelector('.sidebar');
  const overlay   = document.getElementById('sidebar-overlay');

  if (hamburger && sidebar) {
    hamburger.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      if (overlay) overlay.classList.toggle('active');
    });
  }
  if (overlay) {
    overlay.addEventListener('click', () => {
      sidebar.classList.remove('open');
      overlay.classList.remove('active');
    });
  }

  // إخفاء التنبيهات تلقائياً بعد 5 ثوانٍ
  document.querySelectorAll('.alert').forEach(alert => {
    setTimeout(() => {
      alert.style.transition = 'opacity .4s ease';
      alert.style.opacity = '0';
      setTimeout(() => alert.remove(), 400);
    }, 5000);
  });

  // ─── PWA: شريط حالة الاتصال ───────────────────────────────────────────
  initOfflineBanner();
});

/* ═══════════════════════════════════════════════════════
   PWA Offline / Online Banner + Sync
═══════════════════════════════════════════════════════ */
function initOfflineBanner() {
  const banner = getOrCreateBanner();

  function updateStatus() {
    if (navigator.onLine) {
      banner.style.display = 'none';
      // طلب المزامنة عند العودة
      if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage('TRIGGER_SYNC');
        showSyncToast();
      }
    } else {
      banner.style.display = 'flex';
    }
  }

  window.addEventListener('online',  updateStatus);
  window.addEventListener('offline', updateStatus);
  updateStatus();

  // استقبال رسائل SW
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', event => {
      if (event.data?.type === 'SYNC_DONE') {
        showToast('✅ تمت مزامنة البيانات مع الخادم', 'success');
      }
    });
  }
}

function getOrCreateBanner() {
  let b = document.getElementById('offline-status-bar');
  if (!b) {
    b = document.createElement('div');
    b.id = 'offline-status-bar';
    b.innerHTML = `
      <span>📡</span>
      <span>أنت حالياً غير متصل بالإنترنت — البيانات ستُحفظ محلياً وتُزامن تلقائياً</span>
    `;
    b.style.cssText = `
      display:none; position:fixed; bottom:0; left:0; right:0; z-index:9990;
      background:#b45309; color:#fff; padding:10px 20px;
      align-items:center; gap:10px; font-size:.85rem; font-weight:600;
      box-shadow:0 -4px 12px rgba(0,0,0,.2);
    `;
    document.body.appendChild(b);
  }
  return b;
}

function showSyncToast() {
  showToast('🔄 استُعيد الاتصال — جارٍ مزامنة البيانات...', 'info');
}

function showToast(msg, type = 'info') {
  const t = document.createElement('div');
  t.textContent = msg;
  t.style.cssText = `
    position:fixed; bottom:60px; left:50%; transform:translateX(-50%);
    background:${type === 'success' ? '#059669' : type === 'error' ? '#dc2626' : '#2563eb'};
    color:#fff; padding:10px 22px; border-radius:24px; font-size:.85rem;
    font-weight:600; z-index:9999; box-shadow:0 6px 20px rgba(0,0,0,.25);
    animation: slideUp .3s ease;
  `;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .4s'; }, 3000);
  setTimeout(() => t.remove(), 3500);
}

/* ═══════════════════════════════════════════════════════
   Offline IndexedDB Queue (للاستخدام من الصفحات)
═══════════════════════════════════════════════════════ */
const OfflineQueue = (() => {
  const DB_NAME    = 'hisab-offline';
  const STORE_NAME = 'sync-queue';

  function open() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = e =>
        e.target.result.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
      req.onsuccess  = e => resolve(e.target.result);
      req.onerror    = e => reject(e.target.error);
    });
  }

  async function count() {
    const db = await open();
    return new Promise((res, rej) => {
      const req = db.transaction(STORE_NAME).objectStore(STORE_NAME).count();
      req.onsuccess = e => res(e.target.result);
      req.onerror   = e => rej(e.target.error);
    });
  }

  async function getAll() {
    const db = await open();
    return new Promise((res, rej) => {
      const req = db.transaction(STORE_NAME).objectStore(STORE_NAME).getAll();
      req.onsuccess = e => res(e.target.result);
      req.onerror   = e => rej(e.target.error);
    });
  }

  return { count, getAll };
})();

// عرض عداد القائمة في الـ sidebar إن وجدت بنود معلقة
(async () => {
  try {
    const n = await OfflineQueue.count();
    if (n > 0) {
      const badge = document.createElement('span');
      badge.textContent = n;
      badge.style.cssText = `
        background:#ef4444;color:#fff;border-radius:50%;
        width:18px;height:18px;display:inline-flex;
        align-items:center;justify-content:center;font-size:.7rem;
        margin-right:4px;font-weight:700;
      `;
      const dashLink = document.querySelector('.sidebar-nav a[href="/dashboard"]');
      if (dashLink) dashLink.prepend(badge);
    }
  } catch(e) { /* تجاهل */ }
})();

