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
    // A fresh, higher unread count means something new landed while this
    // tab was open — give it the same whistle sound a push notification
    // would get, instead of a silent badge nobody notices.
    if (lastUnread !== null && count > lastUnread && window.SquadTurfPush) {
      window.SquadTurfPush.playWhistle();
    }
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
})();
