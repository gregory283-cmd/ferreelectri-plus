self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = { body: event.data ? event.data.text() : '' };
  }

  const url = typeof data.url === 'string' && data.url.startsWith('/')
    ? data.url
    : '/admin-panel/dashboard/';
  event.waitUntil(self.registration.showNotification(data.title || 'Nuevo pedido', {
    body: data.body || 'Hay un pedido que requiere revisión.',
    icon: '/static/dashboard/pwa/icon-192.png',
    badge: '/static/dashboard/pwa/icon-192.png',
    tag: data.tag || 'ferreelectri-admin-order',
    data: { url },
    renotify: true,
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const destination = new URL(event.notification.data?.url || '/admin-panel/dashboard/', self.location.origin);
  if (destination.origin !== self.location.origin) return;

  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
    for (const client of clients) {
      if (client.url.startsWith(self.location.origin) && 'focus' in client) {
        return client.navigate(destination.href).then(() => client.focus());
      }
    }
    return self.clients.openWindow(destination.href);
  }));
});
