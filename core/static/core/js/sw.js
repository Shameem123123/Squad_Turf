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

// Distinct vibration patterns per event type. This is the one piece of
// "distinct feel per notification type" that a service worker can actually
// control for a system-tray notification — browsers do NOT support a
// custom sound file for showNotification() (that option was dropped from
// the spec years ago), so the OS/browser always plays its own default
// notification tone for a true background/closed-app push. The custom
// whistle files only play when a SquadTurf tab is open somewhere (even in
// the background, e.g. while you're in Instagram with the tab still
// alive) — see push.js, which the message-relay below feeds.
var VIBRATE_PATTERNS = {
  JOIN_REQUEST: [180, 60, 180],
  REQUEST_ACCEPTED: [400],
  REQUEST_DECLINED: [120],
  PLAYER_LEFT: [150, 80, 150],
  MATCH_FILLED: [100, 50, 100, 50, 250],
  MATCH_CANCELLED: [120, 90, 120, 220, 500],
  REMINDER: [250, 100, 250],
  NEW_MATCH: [150, 80, 150, 80, 150],
};

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
    vibrate: VIBRATE_PATTERNS[data.verb] || [200, 80, 200, 80, 400],
  };

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(data.title || 'SquadTurf', options),
      // If a SquadTurf tab happens to be open in the foreground, the OS
      // often won't play a sound for it at all — so tell any open tabs to
      // play the whistle themselves instead of relying on the system.
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
