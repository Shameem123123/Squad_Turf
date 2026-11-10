// SquadTurf — shared front-end behaviour (progress bar, spinners, flashes, push prompt).
(function () {
  'use strict';

  /* ---- top progress bar: the standard loading indicator --------------------- */
  var bar = document.createElement('div');
  bar.className = 'st-progress';
  bar.innerHTML = '<i></i>';
  var fill = bar.firstChild, timer = null, pct = 0;

  function start() {
    clearInterval(timer);
    pct = 8;
    fill.style.width = pct + '%';
    bar.classList.add('is-on');
    timer = setInterval(function () {
      pct += (90 - pct) * 0.12;            // ease toward 90%, finish when the page swaps
      fill.style.width = pct + '%';
    }, 200);
  }
  function done() {
    clearInterval(timer);
    fill.style.width = '100%';
    setTimeout(function () { bar.classList.remove('is-on'); fill.style.width = '0'; }, 220);
  }
  window.StProgress = { start: start, done: done };

  document.addEventListener('DOMContentLoaded', function () {
    document.body.appendChild(bar);

    // Flash messages: dismiss on tap, or after a few seconds.
    document.querySelectorAll('.st-flash').forEach(function (el, i) {
      var close = el.querySelector('button');
      if (close) close.addEventListener('click', function () { el.remove(); });
      setTimeout(function () {
        el.style.transition = 'opacity .3s';
        el.style.opacity = '0';
        setTimeout(function () { el.remove(); }, 300);
      }, 5000 + i * 400);
    });

    initPushBanner();
  });

  window.addEventListener('pageshow', done);   // back/forward cache

  // Navigating to another page of the site.
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    if (a.target === '_blank' || a.hasAttribute('download')) return;
    var url = new URL(a.href, location.href);
    if (url.origin !== location.origin) return;
    if (url.pathname === location.pathname && url.search === location.search) return;
    if (/^(tel|mailto|javascript):/.test(a.getAttribute('href'))) return;
    start();
  });

  // Forms: show a spinner on the submit button so a slow request never looks frozen.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    setTimeout(function () {
      if (e.defaultPrevented || form.hasAttribute('data-no-spinner')) return;
      start();
      var btn = form.querySelector('button[type=submit], button:not([type])');
      if (btn && !btn.classList.contains('is-loading')) {
        btn.style.minWidth = btn.offsetWidth + 'px';
        btn.classList.add('is-loading');
        btn.innerHTML = '<span class="st-spinner" aria-hidden="true"></span><span class="sr-only">Loading</span>';
      }
    }, 0);
  });

  // iOS Safari only applies :active styles when a touch listener exists.
  document.addEventListener('touchstart', function () {}, { passive: true });

  /* ---- menus ------------------------------------------------------------------ */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') document.querySelectorAll('.st-menu-open').forEach(function (m) { m.hidden = true; });
  });

  /* ---- push prompt (stays until notifications are on) --------------------------- */
  function initPushBanner() {
    var banner = document.getElementById('push-banner');
    if (!banner) return;
    var supported = 'serviceWorker' in navigator && 'PushManager' in window;
    if (!supported) { banner.hidden = true; return; }
    var btn = document.getElementById('push-enable-btn');
    if (!btn) return;
    btn.addEventListener('click', function () {
      btn.disabled = true;
      btn.textContent = 'Enabling…';
      window.SquadTurfPush.subscribe().then(function (result) {
        if (result.ok) { banner.hidden = true; return; }
        btn.disabled = false;
        btn.textContent = 'Enable';
        alert(window.SquadTurfPush.messageFor(result.reason));
      });
    });
  }
})();
