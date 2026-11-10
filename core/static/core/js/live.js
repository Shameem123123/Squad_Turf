// SquadTurf — near-real-time updates without websockets.
// Polls a cheap "signature" endpoint. When it changes, the notification badge
// refreshes and any page with id="live-region" swaps just that region in place.
(function () {
  'use strict';
  var BASE_MS = 10000, MAX_MS = 60000;
  if (!document.body || !('live' in document.body.dataset)) return;

  var lastSig = null, inFlight = false, delay = BASE_MS;

  function setBadges(count) {
    document.querySelectorAll('[data-notif-badge]').forEach(function (el) {
      el.textContent = count > 99 ? '99+' : String(count);
      el.hidden = count <= 0;
    });
  }

  function refreshRegion() {
    var region = document.getElementById('live-region');
    if (!region) return;
    fetch(location.pathname + location.search, { credentials: 'same-origin' })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var next = new DOMParser().parseFromString(html, 'text/html').getElementById('live-region');
        if (next) region.innerHTML = next.innerHTML;
      })
      .catch(function () { /* retried on the next change */ });
  }

  function poll() {
    if (inFlight || document.hidden) return schedule();
    inFlight = true;
    fetch('/api/live/', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        setBadges(data.unread || 0);
        if (lastSig !== null && data.sig !== lastSig) refreshRegion();
        lastSig = data.sig;
        delay = BASE_MS;
      })
      .catch(function () { delay = Math.min(delay * 2, MAX_MS); })   // back off when offline
      .finally(function () { inFlight = false; schedule(); });
  }

  function schedule() { setTimeout(poll, delay); }

  document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', function (e) {
      if (e.data && e.data.type === 'squadturf-push') poll();
    });
  }
  poll();
})();
