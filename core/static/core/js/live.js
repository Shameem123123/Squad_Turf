// SquadTurf — near-real-time updates without websockets/Celery.
// Polls a cheap JSON "signature" endpoint every few seconds. If anything
// relevant changed (new match, new join request, request accepted/declined,
// new notification) it quietly refreshes the notification badge and, on
// pages that opt in with id="live-region", swaps that region's HTML in
// place — no full page reload, scroll position preserved.

(function () {
  var POLL_INTERVAL_MS = 8000;
  var body = document.body;
  if (!body || !('liveSig' in body.dataset)) return;

  var lastSig = body.dataset.liveSig || '0';
  var inFlight = false;
  var lastUnread = null;

  function updateBadge(count) {
    var badge = document.getElementById('notif-badge');
    // No sound is played here — SquadTurf doesn't play any sound of its
    // own; the only notification sound a user ever hears is their phone's
    // own default, triggered by the system push in sw.js.
    lastUnread = count;
    [badge, document.getElementById('notif-badge-mobile')].forEach(function (el) {
      if (!el) return;
      if (count > 0) {
        el.textContent = count > 99 ? '99+' : String(count);
        el.classList.remove('hidden');
      } else {
        el.classList.add('hidden');
      }
    });
  }

  function softReload() {
    var region = document.getElementById('live-region');
    if (!region) return;
    fetch(window.location.pathname + window.location.search, { credentials: 'same-origin' })
      .then(function (resp) { return resp.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var newRegion = doc.getElementById('live-region');
        if (newRegion) {
          region.innerHTML = newRegion.innerHTML;
        }
      })
      .catch(function () { /* silent — will retry on next poll */ });
  }

  function poll() {
    if (inFlight || document.hidden) return;
    inFlight = true;
    fetch('/api/live/', { credentials: 'same-origin' })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        updateBadge(data.unread || 0);
        if (data.sig && data.sig !== lastSig) {
          lastSig = data.sig;
          softReload();
        }
      })
      .catch(function () { /* offline / server hiccup — try again next tick */ })
      .finally(function () { inFlight = false; });
  }

  setInterval(poll, POLL_INTERVAL_MS);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) poll();
  });

  // A push can land in between polls — react immediately instead of making
  // the badge/live-region wait up to POLL_INTERVAL_MS to catch up.
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', function (event) {
      if (event.data && event.data.type === 'squadturf-push') poll();
    });
  }
})();
