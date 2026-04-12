/**
 * 看盤助手 Service Worker
 * 快取靜態資源，支援離線瀏覽
 */

const CACHE_NAME = 'kanpan-helper-v5-cachefix';
const STATIC_ASSETS = [
    './',
    './index.html',
    './style.css',
    './app.js?v=20260412-cachefix',
    './manifest.json',
    './test.html',
    './sample/2026-04-08-lite.json'
];

// 安裝時快取靜態資源
self.addEventListener('install', event => {
    console.log('[Service Worker] 安裝中...');
    
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('[Service Worker] 快取靜態資源');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => {
                console.log('[Service Worker] 安裝完成');
                return self.skipWaiting();
            })
            .catch(err => {
                console.error('[Service Worker] 快取失敗:', err);
            })
    );
});

// 啟動時清理舊快取
self.addEventListener('activate', event => {
    console.log('[Service Worker] 啟動中...');
    
    event.waitUntil(
        caches.keys()
            .then(cacheNames => {
                return Promise.all(
                    cacheNames
                        .filter(name => name !== CACHE_NAME)
                        .map(name => {
                            console.log('[Service Worker] 刪除舊快取:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => {
                console.log('[Service Worker] 啟動完成');
                return self.clients.claim();
            })
    );
});

// 攔截請求
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);
    
    // 報表一律走網路，避免讀到舊版 JSON。
    if (url.pathname.includes('/reports/')) {
        event.respondWith(fetchFreshReport(request));
        return;
    }

    // HTML 導覽頁優先拿最新內容，避免頁面腳本本身被舊快取鎖住。
    if (request.mode === 'navigate') {
        event.respondWith(networkFirst(request));
        return;
    }
    
    // 靜態資源使用快取優先策略
    event.respondWith(cacheFirst(request));
});

// 快取優先策略
async function cacheFirst(request) {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(request);
    
    if (cached) {
        return cached;
    }
    
    try {
        const response = await fetch(request);
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.error('[Service Worker] 網路請求失敗:', error);
        // 嘗試回傳離線頁面（如果有）
        const offlinePage = await cache.match('./index.html');
        if (offlinePage) {
            return offlinePage;
        }
        throw error;
    }
}

// 報表檔案不寫入快取，避免長時間停留在舊值。
async function fetchFreshReport(request) {
    try {
        return await fetch(request, { cache: 'no-store' });
    } catch (error) {
        console.log('[Service Worker] 報表請求失敗:', request.url);
        return new Response(
            JSON.stringify({
                error: '無法取得最新報表資料',
                cached: false
            }),
            {
                status: 503,
                headers: {
                    'Content-Type': 'application/json',
                    'Cache-Control': 'no-store'
                }
            }
        );
    }
}

// 網路優先策略（用於頁面 HTML）
async function networkFirst(request) {
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            // 更新快取
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        console.log('[Service Worker] 網路失敗，嘗試快取:', request.url);
        const cache = await caches.open(CACHE_NAME);
        const cached = await cache.match(request);
        
        if (cached) {
            return cached;
        }
        
        // 回傳一個友好的錯誤響應
        return new Response(
            JSON.stringify({
                error: '離線狀態無法取得最新資料',
                cached: false
            }),
            {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            }
        );
    }
}

// 處理背景同步（可選，用於未來擴展）
self.addEventListener('sync', event => {
    if (event.tag === 'check-latest-report') {
        console.log('[Service Worker] 背景同步檢查最新報告');
        // 這裡可以實現自動檢查新報告
    }
});

// 處理推播通知（可選，用於未來擴展）
self.addEventListener('push', event => {
    const options = {
        body: event.data ? event.data.text() : '看盤助手有新的分析報告',
        icon: 'icons/icon-192x192.png',
        badge: 'icons/icon-72x72.png',
        tag: 'kanpan-report',
        requireInteraction: true
    };
    
    event.waitUntil(
        self.registration.showNotification('看盤助手', options)
    );
});

// 處理通知點擊
self.addEventListener('notificationclick', event => {
    event.notification.close();
    event.waitUntil(
        clients.openWindow('./')
    );
});

console.log('[Service Worker] 已載入');
