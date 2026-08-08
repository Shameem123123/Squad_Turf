// SquadTurf service worker — receives Web Push events and shows a system
// notification even if no SquadTurf tab is open. The browser (or, on
// desktop OSes, the OS-level push relay) must still be running for this
// to fire; it can't wake a fully-quit browser process on every platform,
// but it does not require a SquadTurf tab to be open.

self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', function (event) {
  var data = { title: 'SquadTurf', body: 'You have a new update.', url: '/' };
  try {
    if (event.data) {
      data = event.data.json();
    }
  } catch (e) {
    data.body = event.data ? event.data.text() : data.body;
  }

  var options = {
    body: data.body,
    icon: '/static/core/img/icon-192.png',
    badge: '/static/core/img/icon-192.png',
    data: { url: data.url || '/' },
    tag: 'squadturf-notification',
    renotify: true,
    // The Notification API has no "sound" field — the OS/browser plays its
    // own default notification sound automatically as long as we don't
    // silence it. `vibrate` covers the phone-in-your-pocket case.
    silent: false,
    vibrate: [200, 100, 200, 100, 200],
  };

  event.waitUntil(self.registration.showNotification(data.title || 'SquadTurf', options));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var targetUrl = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if ('focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});
