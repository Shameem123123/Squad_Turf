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

// One generic vibration pattern for every event type — browsers do NOT
// support a custom sound file for showNotification() (that option was
// dropped from the spec years ago), so the OS/browser always plays its own
// default notification tone for a background/closed-app push. Keeping a
// single vibration pattern too means every SquadTurf push feels like a
// normal phone notification rather than a distinct jingle per event.
var VIBRATE_PATTERN = [200, 80, 200];

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
    // A per-verb tag means a JOIN_REQUEST banner and a REQUEST_ACCEPTED
    // banner never collapse into each other, and renotify:true forces the
    // OS to re-alert (vibrate/heads-up) on every single one rather than
    // silently swapping the old banner for the new one.
    tag: 'squadturf-' + (data.verb || 'notification'),
    renotify: true,
    requireInteraction: false,
    silent: false,
    vibrate: VIBRATE_PATTERN,
  };

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(data.title || 'SquadTurf', options),
      // Tell any open tabs a push landed so they can refresh their badge
      // instantly instead of waiting for the next poll. No sound is played
      // here or by any listening tab — showNotification() above already
      // triggers the OS/browser's own default notification sound, and
      // that's the only sound a SquadTurf push ever produces.
      self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clientList) {
        clientList.forEach(function (client) {
          client.postMessage({ type: 'squadturf-push', title: data.title, body: data.body, url: data.url, verb: data.verb });
        });
      }),
    ])
  );
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
