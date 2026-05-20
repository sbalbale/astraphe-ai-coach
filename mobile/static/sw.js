// ASTRAPE web push service worker

self.addEventListener('push', (event) => {
  let payload = { title: 'ASTRAPE', body: '', data: {} };
  try {
    payload = { ...payload, ...(event.data?.json() ?? {}) };
  } catch {}

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/astrape-logo.png',
      badge: '/astrape-logo.png',
      data: payload.data,
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url ?? '/dashboard';
  event.waitUntil(
    clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((list) => {
        for (const client of list) {
          if ('focus' in client) return client.focus();
        }
        return clients.openWindow(url);
      })
  );
});
