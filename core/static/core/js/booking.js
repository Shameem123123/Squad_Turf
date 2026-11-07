/* SquadTurf booking UI.
 * - spring(): critically-damped by default, velocity hand-off from gestures
 * - Sheet: interruptible bottom sheet, drag to dismiss with velocity projection
 * - Picker: live slot grid. Players select a contiguous range; turf admins tap a
 *   slot to manage it. Availability is polled so the grid is always current. */
(function () {
  'use strict';

  var POLL_MS = 4000;
  var REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var GROUPS = [['morning', 'Morning'], ['afternoon', 'Afternoon'], ['evening', 'Evening'], ['night', 'Night']];

  /* ---------- tiny helpers ------------------------------------------------ */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === false || v == null) return;
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) { if (c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return node;
  }

  function inr(n) { return '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 }); }
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var i = $('input[name=csrfmiddlewaretoken]');
    return i ? i.value : '';
  }
  function buzz(ms) { try { if (navigator.vibrate) navigator.vibrate(ms || 6); } catch (e) { /* noop */ } }
  function dateLabel(iso, long) {
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-IN', long ? { weekday: 'long', day: 'numeric', month: 'long' } : { weekday: 'short', day: 'numeric', month: 'short' });
  }

  var toastEl, toastT;
  function toast(msg) {
    if (!toastEl) { toastEl = el('div', { class: 'bk-toast', role: 'status', 'aria-live': 'polite' }); document.body.appendChild(toastEl); }
    toastEl.textContent = msg;
    toastEl.classList.add('is-on');
    clearTimeout(toastT);
    toastT = setTimeout(function () { toastEl.classList.remove('is-on'); }, 3200);
  }

  /* ---------- spring ------------------------------------------------------ */
  // response = seconds for one natural period, damping = ratio (1 = no overshoot).
  function spring(o) {
    var omega = 2 * Math.PI / (o.response || 0.4);
    var k = omega * omega, c = 2 * (o.damping == null ? 1 : o.damping) * omega;
    var x = o.from, v = o.velocity || 0, last = performance.now(), raf = 0, done = false;
    if (REDUCED) { o.onUpdate(o.to, 0); if (o.onDone) o.onDone(); return { stop: function () {} }; }
    function frame(now) {
      var dt = Math.min((now - last) / 1000, 1 / 30); last = now;
      var steps = Math.max(1, Math.ceil(dt * 240)), h = dt / steps;
      for (var i = 0; i < steps; i++) { v += (-k * (x - o.to) - c * v) * h; x += v * h; }
      if (Math.abs(x - o.to) < 0.15 && Math.abs(v) < 2) { o.onUpdate(o.to, 0); done = true; if (o.onDone) o.onDone(); return; }
      o.onUpdate(x, v);
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    return { stop: function () { if (!done) cancelAnimationFrame(raf); } };
  }
  // Where would a flick coast to? (UIScrollView-style deceleration)
  function project(vPxPerSec, rate) { rate = rate || 0.99; return (vPxPerSec / 1000) * rate / (1 - rate); }
  function rubber(d, dim) { return (1 - 1 / (d * 0.55 / dim + 1)) * dim; }

  /* ---------- sheet --------------------------------------------------------- */
  var Sheet = (function () {
    var sheet, scrim, body, y = 0, h = 600, anim = null, opener = null, isOpen = false;
    var drag = null, samples = [];

    function apply(v) {
      y = v;
      sheet.style.transform = 'translateY(' + v + 'px)';
      scrim.style.opacity = String(clamp(1 - Math.max(v, 0) / h, 0, 1));
    }
    function stop() { if (anim) { anim.stop(); anim = null; } }

    function init() {
      sheet = $('#bk-sheet'); scrim = $('#bk-scrim');
      if (!sheet || !scrim || sheet._ready) return !!sheet;
      sheet._ready = true;
      body = $('#bk-sheet-body');
      scrim.addEventListener('click', close);
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && isOpen) close(); });
      var grab = $('.bk-sheet-grab', sheet);
      grab.addEventListener('pointerdown', function (e) {
        stop(); drag = { startY: e.clientY, startPos: y }; samples = [{ t: e.timeStamp, y: e.clientY }];
        grab.setPointerCapture(e.pointerId); grab.style.cursor = 'grabbing';
      });
      grab.addEventListener('pointermove', function (e) {
        if (!drag) return;
        samples.push({ t: e.timeStamp, y: e.clientY }); if (samples.length > 6) samples.shift();
        var d = drag.startPos + (e.clientY - drag.startY);
        apply(d < 0 ? -rubber(-d, h) : d);           // follows the finger 1:1, resists when pulled up
      });
      function release(e) {
        if (!drag) return; drag = null; grab.style.cursor = '';
        var a = samples[0], b = samples[samples.length - 1], v = 0;
        if (a && b && b.t > a.t) v = (b.y - a.y) / (b.t - a.t) * 1000;
        if (y + project(v) > h * 0.5) dismiss(v); else settle(v);
      }
      grab.addEventListener('pointerup', release);
      grab.addEventListener('pointercancel', release);
      return true;
    }
    function settle(v) { stop(); anim = spring({ from: y, to: 0, velocity: v, response: 0.34, damping: Math.abs(v) > 300 ? 0.82 : 1, onUpdate: apply }); }
    function dismiss(v) {
      stop(); isOpen = false;
      anim = spring({ from: y, to: h, velocity: v || 0, response: 0.3, damping: 1, onUpdate: apply,
        onDone: function () { sheet.style.visibility = 'hidden'; scrim.classList.remove('is-on'); document.documentElement.style.overflow = ''; if (opener && opener.focus) opener.focus(); } });
    }
    function open(build, from) {
      if (!init()) return;
      opener = from || document.activeElement;
      body.textContent = ''; build(body);
      sheet.style.visibility = 'visible'; scrim.classList.add('is-on');
      document.documentElement.style.overflow = 'hidden';
      h = sheet.offsetHeight + 48; stop(); isOpen = true;
      apply(h);
      anim = spring({ from: h, to: 0, response: 0.42, damping: 1, onUpdate: apply });
      var f = $('input:not([type=hidden]), select, textarea, .bk-btn', sheet); if (f && !('ontouchstart' in window)) f.focus({ preventScroll: true });
    }
    function close() { if (isOpen) dismiss(0); }
    return { open: open, close: close };
  })();

  /* ---------- confirm-before-submit forms (cancel, close day …) ------------ */
  function initConfirmForms() {
    document.addEventListener('submit', function (e) {
      var f = e.target;
      if (!f.matches || !f.matches('form[data-confirm-title]') || f._confirmed) return;
      e.preventDefault();
      var danger = f.hasAttribute('data-danger');
      Sheet.open(function (body) {
        body.appendChild(el('h2', { text: f.getAttribute('data-confirm-title') }));
        body.appendChild(el('p', { class: 'bk-sub', text: f.getAttribute('data-confirm-body') || '' }));
        var go = el('button', { type: 'button', class: 'bk-btn bk-btn-block ' + (danger ? 'bk-btn-danger' : ''), text: f.getAttribute('data-confirm-label') || 'Confirm',
          onclick: function () { f._confirmed = true; go.disabled = true; HTMLFormElement.prototype.submit.call(f); } });
        body.appendChild(el('div', { class: 'bk-stack', style: 'margin-top:20px' }, [go,
          el('button', { type: 'button', class: 'bk-btn bk-btn-soft bk-btn-block', text: 'Not now', onclick: Sheet.close })]));
      }, document.activeElement);
    });
  }

  /* ---------- layout vars (nav / tab bar heights) ---------------------------- */
  function measure() {
    var nav = $('nav'); var tab = $('#mobile-tab-bar');
    var navH = nav ? nav.getBoundingClientRect().height : 58;
    var tabH = 0;
    if (tab && getComputedStyle(tab).display !== 'none') tabH = tab.getBoundingClientRect().height;
    document.documentElement.style.setProperty('--nav-h', Math.round(navH) + 'px');
    document.documentElement.style.setProperty('--tab-h', Math.round(tabH) + 'px');
  }

  /* ---------- the picker ------------------------------------------------------ */
  function Picker(cfg) {
    var admin = cfg.mode === 'admin';
    var S = { date: cfg.date, slots: cfg.payload.slots, days: cfg.payload.days, canBook: cfg.payload.can_book, sel: null, key: '' };
    var datesEl = $('#bk-dates'), slotsEl = $('#bk-slots'), liveEl = $('#bk-live-time'), sticky = $('.bk-sticky');
    var bar = $('#bk-bar'), barRange = $('#bk-bar-range'), barSub = $('#bk-bar-sub'), barPrice = $('#bk-bar-price'), barBtn = $('#bk-bar-btn');
    var barAnim = null, barP = 0, shownPrice = 0, priceAnim = null, timer = null, busy = false;
    var turfName = (cfg.turfName || '');

    /* dates */
    function hintFor(date) {
      var d = (S.days || []).filter(function (x) { return x.date === date; })[0];
      if (!d || !d.total) return 'none';
      if (d.free === 0) return 'none';
      return d.free / d.total <= 0.25 ? 'low' : '';
    }
    function renderDates() {
      datesEl.textContent = '';
      cfg.dates.forEach(function (d) {
        var hint = hintFor(d.date);
        var b = el('button', { type: 'button', class: 'bk-date', role: 'tab', 'data-date': d.date, 'aria-selected': d.date === S.date ? 'true' : 'false',
          'aria-label': dateLabel(d.date, true), onclick: function () { selectDate(d.date); } }, [
          el('span', { class: 'dow', text: d.dow }), el('span', { class: 'dom', text: d.dom }), el('span', { class: 'mon', text: d.mon }),
          el('span', { class: 'hint ' + hint })]);
        datesEl.appendChild(b);
      });
      scrollDateIntoView(false);
    }
    function patchDates() {
      Array.prototype.forEach.call(datesEl.children, function (b) {
        b.setAttribute('aria-selected', b.getAttribute('data-date') === S.date ? 'true' : 'false');
        var h = $('.hint', b); if (h) h.className = 'hint ' + hintFor(b.getAttribute('data-date'));
      });
    }
    function scrollDateIntoView(smooth) {
      var b = $('.bk-date[aria-selected="true"]', datesEl); if (!b) return;
      var left = b.offsetLeft - (datesEl.clientWidth - b.offsetWidth) / 2;
      datesEl.scrollTo({ left: left, behavior: smooth && !REDUCED ? 'smooth' : 'auto' });
    }

    /* slots */
    function slotLabel(s) {
      var st = s.state;
      if (admin) return s.label + ', ' + st + (s.booking ? ', ' + s.booking.name : '');
      return s.label + ', ' + inr(s.price) + ', ' + (st === 'free' ? 'available' : st === 'mine' ? 'your booking' : st === 'booked' ? 'booked' : st === 'blocked' ? 'closed' : 'unavailable');
    }
    function slotInner(btn, s) {
      btn.textContent = '';
      btn.appendChild(el('span', { class: 't', text: s.label }));
      if (admin && s.booking) btn.appendChild(el('span', { class: 'n', text: s.state === 'blocked' ? (s.booking.name || 'Closed') : s.booking.name }));
      else if (s.state === 'booked') btn.appendChild(el('span', { class: 'p', text: 'Booked' }));
      else if (s.state === 'blocked') btn.appendChild(el('span', { class: 'p', text: 'Closed' }));
      else if (s.state === 'mine') btn.appendChild(el('span', { class: 'p', text: 'Yours' }));
      else if (s.state === 'past') btn.appendChild(el('span', { class: 'p', text: admin ? 'Ended' : '—' }));
      else btn.appendChild(el('span', { class: 'p', text: inr(s.price) }));
    }
    function structKey(slots) { return slots.map(function (s) { return s.start; }).join('|'); }

    function renderSlots() {
      slotsEl.textContent = '';
      if (!S.slots.length) { slotsEl.appendChild(el('div', { class: 'bk-closed-note', text: 'No slots on this day.' })); return; }
      GROUPS.forEach(function (g) {
        var items = S.slots.map(function (s, i) { return [s, i]; }).filter(function (p) { return p[0].group === g[0]; });
        if (!items.length) return;
        var wrap = el('div', { class: 'bk-slots', role: 'group', 'aria-label': g[1] + ' slots' });
        items.forEach(function (p) {
          var s = p[0], i = p[1];
          var b = el('button', { type: 'button', class: 'bk-slot', 'data-i': i, 'data-start': s.start, 'data-state': s.state, 'aria-label': slotLabel(s),
            onclick: function () { onTap(i, b); } });
          slotInner(b, s);
          if (!admin) b.setAttribute('aria-pressed', 'false');
          wrap.appendChild(b);
        });
        slotsEl.appendChild(el('div', { class: 'bk-group' }, [el('h3', { text: g[1] }), wrap]));
      });
      S.key = structKey(S.slots);
      paintSelection();
    }
    function patchSlots(next) {
      if (structKey(next) !== S.key) { S.slots = next; renderSlots(); return; }
      next.forEach(function (s, i) {
        var old = S.slots[i], b = $('.bk-slot[data-i="' + i + '"]', slotsEl);
        if (!b) return;
        var changed = old.state !== s.state || old.price !== s.price || JSON.stringify(old.booking || null) !== JSON.stringify(s.booking || null);
        if (changed) {
          b.setAttribute('data-state', s.state); b.setAttribute('aria-label', slotLabel(s)); slotInner(b, s);
          b.classList.remove('is-changed'); void b.offsetWidth; b.classList.add('is-changed');
        }
      });
      S.slots = next;
    }

    /* selection (player) */
    function range() { return S.sel ? [Math.min(S.sel[0], S.sel[1]), Math.max(S.sel[0], S.sel[1])] : null; }
    function isFree(i) { return S.slots[i] && S.slots[i].state === 'free'; }
    function paintSelection() {
      if (admin) return;
      var r = range();
      Array.prototype.forEach.call(slotsEl.querySelectorAll('.bk-slot'), function (b) {
        var i = +b.getAttribute('data-i');
        b.setAttribute('aria-pressed', r && i >= r[0] && i <= r[1] ? 'true' : 'false');
      });
      updateBar();
    }
    function onTap(i, btn) {
      var s = S.slots[i];
      if (admin) return openAdminSheet(i, btn);
      if (!S.canBook) { toast('This turf has paused online bookings for now.'); return; }
      if (s.state === 'mine') { if (s.booking) location.href = cfg.ticketBase ? cfg.ticketBase.replace('REF', s.booking.ref) : '#'; return; }
      if (s.state !== 'free') { if (s.state === 'booked' || s.state === 'blocked') { shake(btn); buzz(10); } return; }
      var r = range(); buzz(6);
      if (!r) S.sel = [i, i];
      else if (i >= r[0] && i <= r[1]) {
        if (r[0] === r[1]) S.sel = null;
        else if (i === r[0]) S.sel = [r[0] + 1, r[1]];
        else if (i === r[1]) S.sel = [r[0], r[1] - 1];
        else S.sel = [i, i];
      } else if (i === r[0] - 1 || i === r[1] + 1) {
        var n = Math.max(r[1], i) - Math.min(r[0], i) + 1;
        if (n > cfg.maxSlots) { toast('You can book up to ' + cfg.maxSlots + ' slots at a time.'); shake(btn); return; }
        S.sel = [Math.min(r[0], i), Math.max(r[1], i)];
      } else S.sel = [i, i];
      paintSelection();
    }
    function shake(b) { b.classList.remove('is-shake'); void b.offsetWidth; b.classList.add('is-shake'); }

    /* checkout bar */
    function selSummary() {
      var r = range(); if (!r) return null;
      var a = S.slots[r[0]], z = S.slots[r[1]], total = 0;
      for (var i = r[0]; i <= r[1]; i++) total += S.slots[i].price;
      var n = r[1] - r[0] + 1;
      return { start: a.start, count: n, total: total, label: a.label + ' – ' + z.end_label, a: a, z: z };
    }
    function setBar(on) {
      if (!bar) return;
      var to = on ? 1 : 0; if (barAnim) barAnim.stop();
      if (on) bar.classList.add('is-on');
      barAnim = spring({ from: barP, to: to, response: 0.4, damping: on ? 0.82 : 1, onUpdate: function (p) {
        barP = p; bar.style.opacity = String(clamp(p, 0, 1));
        bar.style.transform = 'translateY(' + ((1 - p) * 40) + 'px) scale(' + (0.96 + 0.04 * p) + ')';
      }, onDone: function () { if (!on) bar.classList.remove('is-on'); } });
    }
    function tweenPrice(to) {
      if (priceAnim) priceAnim.stop();
      priceAnim = spring({ from: shownPrice, to: to, response: 0.3, damping: 1, onUpdate: function (v) { barPrice.textContent = inr(Math.round(v)); shownPrice = v; } });
    }
    function updateBar() {
      if (!bar) return;
      var s = selSummary();
      if (!s) { setBar(false); return; }
      barRange.textContent = s.label;
      barSub.textContent = dateLabel(S.date) + ' · ' + s.count + (s.count > 1 ? ' slots' : ' slot');
      tweenPrice(s.total);
      if (!cfg.loggedIn) { barBtn.textContent = 'Log in to book'; }
      else barBtn.textContent = 'Book';
      if (!bar.classList.contains('is-on') || barP < 0.99) setBar(true);
    }

    function openConfirm() {
      var s = selSummary(); if (!s) return;
      if (!cfg.loggedIn) { location.href = cfg.loginUrl; return; }
      if (cfg.isTurfAdmin) { toast('Turf admin accounts manage turfs — use a player account to book.'); return; }
      Sheet.open(function (body) {
        var lines = [];
        var r = range();
        for (var i = r[0]; i <= r[1]; i++) lines.push([S.slots[i].label + ' – ' + S.slots[i].end_label, inr(S.slots[i].price)]);
        body.appendChild(el('h2', { text: 'Confirm booking' }));
        body.appendChild(el('p', { class: 'bk-sub', text: turfName }));
        var rows = [el('div', { class: 'bk-sum-row' }, [el('span', { text: 'Date' }), el('b', { text: dateLabel(S.date, true) })])];
        lines.forEach(function (l) { rows.push(el('div', { class: 'bk-sum-row' }, [el('span', { text: l[0] }), el('b', { text: l[1] })])); });
        rows.push(el('div', { class: 'bk-sum-row bk-sum-total' }, [el('span', { text: 'Total' }), el('b', { text: inr(s.total) })]));
        body.appendChild(el('div', { class: 'bk-sum' }, rows));
        var go = el('button', { type: 'submit', class: 'bk-btn bk-btn-green bk-btn-block', text: 'Confirm booking · ' + inr(s.total) });
        var form = el('form', { method: 'post', action: cfg.confirmUrl, onsubmit: function () { go.disabled = true; go.textContent = 'Booking…'; } }, [
          el('input', { type: 'hidden', name: 'csrfmiddlewaretoken', value: csrf() }),
          el('input', { type: 'hidden', name: 'date', value: S.date }),
          el('input', { type: 'hidden', name: 'start', value: s.start }),
          el('input', { type: 'hidden', name: 'count', value: String(s.count) }),
          el('label', { class: 'bk-field' }, [el('span', { text: 'Note for the turf (optional)' }),
            el('input', { class: 'bk-input', name: 'note', maxlength: '200', placeholder: 'Team name, number of players…' })]),
          el('p', { class: 'bk-note', text: 'Pay at the turf. Free cancellation until ' + cfg.cancelHours + ' hours before the start.' }),
          go]);
        body.appendChild(form);
      }, barBtn);
    }

    /* admin sheet */
    function post(action, fields, kids, extra) {
      var inputs = [el('input', { type: 'hidden', name: 'csrfmiddlewaretoken', value: csrf() })];
      Object.keys(fields || {}).forEach(function (k) {
        [].concat(fields[k]).forEach(function (v) { inputs.push(el('input', { type: 'hidden', name: k, value: v })); });
      });
      return el('form', Object.assign({ method: 'post', action: action }, extra || {}), inputs.concat(kids || []));
    }
    function row(k, v, href) {
      return el('div', { class: 'bk-sum-row' }, [el('span', { text: k }), href ? el('a', { href: href, class: 'bk-num', style: 'color:var(--tint);font-weight:600', text: v }) : el('b', { text: v })]);
    }
    function openAdminSheet(i, btn) {
      var s = S.slots[i], A = cfg.actions;
      Sheet.open(function (body) {
        body.appendChild(el('h2', { text: s.label + ' – ' + s.end_label }));
        body.appendChild(el('p', { class: 'bk-sub', text: dateLabel(S.date, true) }));
        if (s.state === 'free') {
          var run = 0; for (var j = i; j < S.slots.length && S.slots[j].state === 'free' && run < cfg.maxSlots; j++) run++;
          var sel = el('select', { class: 'bk-input', name: 'count' });
          for (var n = 1; n <= run; n++) sel.appendChild(el('option', { value: String(n), text: n + (n > 1 ? ' slots' : ' slot') + ' · ' + inr(S.slots.slice(i, i + n).reduce(function (a, x) { return a + x.price; }, 0)) }));
          body.appendChild(el('h2', { class: 'bk-h2', style: 'margin-top:20px;font-size:17px', text: 'Walk-in booking' }));
          body.appendChild(post(A.walkin, { date: S.date, start: s.start }, [
            el('label', { class: 'bk-field' }, [el('span', { text: 'Name' }), el('input', { class: 'bk-input', name: 'name', required: true, maxlength: '120', placeholder: 'Player or team name' })]),
            el('label', { class: 'bk-field' }, [el('span', { text: 'Phone (optional)' }), el('input', { class: 'bk-input', name: 'phone', inputmode: 'tel', maxlength: '15' })]),
            el('label', { class: 'bk-field' }, [el('span', { text: 'Duration' }), sel]),
            el('label', { class: 'bk-check' }, [el('input', { type: 'checkbox', name: 'paid' }), 'Already paid']),
            el('button', { type: 'submit', class: 'bk-btn bk-btn-green bk-btn-block', text: 'Add walk-in' })]));
          body.appendChild(el('div', { class: 'bk-divider' }));
          body.appendChild(post(A.block, { date: S.date, start: s.start }, [
            el('label', { class: 'bk-field' }, [el('span', { text: 'Or close this slot' }), el('input', { class: 'bk-input', name: 'reason', maxlength: '120', placeholder: 'Reason — maintenance, tournament… (optional)' })]),
            el('button', { type: 'submit', class: 'bk-btn bk-btn-soft bk-btn-block', text: 'Block slot' })]));
        } else if (s.state === 'blocked') {
          body.appendChild(el('div', { class: 'bk-sum' }, [row('Status', 'Closed'), row('Reason', s.booking.name || 'Closed')]));
          body.appendChild(post(A.unblock, { ref: s.booking.ref }, [el('button', { type: 'submit', class: 'bk-btn bk-btn-green bk-btn-block', text: 'Reopen slot' })]));
        } else if (s.booking) {
          var b = s.booking, url = function (u) { return u.replace('REF', b.ref); };
          body.appendChild(el('div', { class: 'bk-sum' }, [
            row(b.source === 'WALKIN' ? 'Walk-in' : 'Player', b.name),
            b.phone ? row('Phone', b.phone, 'tel:' + b.phone) : null,
            row('Time', b.range), row('Slots', String(b.slots)), row('Amount', inr(b.amount)),
            row('Payment', b.paid ? 'Paid' : 'To collect at turf'), row('Reference', b.ref), b.note ? row('Note', b.note) : null]));
          body.appendChild(post(url(A.paid), { date: S.date }, [el('button', { type: 'submit', class: 'bk-btn bk-btn-green bk-btn-block', text: b.paid ? 'Mark as unpaid' : 'Mark as paid · ' + inr(b.amount) })]));
          var why = el('input', { class: 'bk-input', name: 'reason', maxlength: '200', placeholder: 'Reason shown to the player (optional)' });
          var cancelForm = post(url(A.cancel), {}, [el('label', { class: 'bk-field', style: 'margin-top:18px' }, [el('span', { text: 'Cancel this booking' }), why]),
            el('button', { type: 'submit', class: 'bk-btn bk-btn-danger bk-btn-block', text: 'Cancel booking & free the slot' })]);
          body.appendChild(cancelForm);
        } else {
          body.appendChild(el('p', { class: 'bk-sub', text: 'This slot has ended.' }));
        }
      }, btn);
    }

    /* data */
    function apply(data, fromPoll) {
      if (data.date !== S.date) return;
      var prevSel = range(), taken = null;
      S.days = data.days; S.canBook = data.can_book;
      patchSlots(data.slots);
      patchDates();
      if (liveEl) liveEl.textContent = 'Updated ' + data.server_time;
      if (prevSel && !admin) {
        for (var i = prevSel[0]; i <= prevSel[1]; i++) if (!isFree(i)) { taken = S.slots[i]; break; }
        if (taken) {
          S.sel = null; buzz([10, 40, 10]);
          toast(taken.label + ' was just taken — pick another slot.');
        }
        paintSelection();
      }
      if (admin && data.stats) updateStats(data.stats);
      var closed = $('#bk-paused'); if (closed) closed.hidden = S.canBook || admin;
    }
    function updateStats(st) {
      var map = { bookings: String(st.bookings), occupancy: st.occupancy + '%', revenue: inr(st.revenue), to_collect: inr(st.to_collect) };
      Object.keys(map).forEach(function (k) { var n = $('[data-stat="' + k + '"]'); if (n && n.textContent !== map[k]) n.textContent = map[k]; });
      var m = $('#bk-meter'); if (m) m.style.width = st.occupancy + '%';
      var sub = $('[data-stat="slots"]'); if (sub) sub.textContent = st.booked_slots + ' of ' + st.capacity + ' slots';
    }
    function fetchDay(date, fromPoll) {
      if (busy && fromPoll) return Promise.resolve();
      busy = true;
      return fetch(cfg.apiUrl + '?date=' + encodeURIComponent(date) + '&_=' + Date.now(), { credentials: 'same-origin', cache: 'no-store', headers: { 'Accept': 'application/json' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) { busy = false; apply(d, fromPoll); })
        .catch(function () { busy = false; });
    }
    function selectDate(date) {
      if (date === S.date) return;
      Array.prototype.forEach.call(document.querySelectorAll('[data-bk-date-input]'), function (i) { i.value = date; });
      S.date = date; S.sel = null; paintSelection(); patchDates(); scrollDateIntoView(true);
      slotsEl.style.opacity = '.45';
      try { history.replaceState(null, '', '?date=' + date); } catch (e) { /* noop */ }
      fetchDay(date, false).then(function () { slotsEl.style.opacity = ''; });
      buzz(5);
    }
    function schedule() {
      clearInterval(timer);
      timer = setInterval(function () { if (!document.hidden) fetchDay(S.date, true); }, POLL_MS);
    }

    /* boot */
    renderDates(); renderSlots(); schedule();
    document.addEventListener('visibilitychange', function () { if (!document.hidden) fetchDay(S.date, true); });
    if (barBtn) barBtn.addEventListener('click', openConfirm);
    if (sticky) {
      var onScroll = function () { sticky.classList.toggle('is-stuck', sticky.getBoundingClientRect().top <= (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--nav-h')) || 58) + 1); };
      window.addEventListener('scroll', onScroll, { passive: true }); onScroll();
    }
    if (admin) {
      var q = new URLSearchParams(location.search);
      if (q.get('date') !== S.date) { try { history.replaceState(null, '', '?date=' + S.date); } catch (e) { /* noop */ } }
    }
  }

  /* ---------- boot ---------------------------------------------------------- */
  function boot() {
    // The page wrapper keeps a transform from the page-in animation, which would trap
    // position:fixed children. Hoist the floating UI to <body> so it's viewport-fixed.
    ['bk-bar', 'bk-scrim', 'bk-sheet'].forEach(function (id) { var n = document.getElementById(id); if (n && n.parentNode !== document.body) document.body.appendChild(n); });
    measure(); window.addEventListener('resize', measure);
    initConfirmForms();
    var cfgNode = $('#bk-cfg');
    if (cfgNode) {
      var cfg = JSON.parse(cfgNode.textContent);
      var root = $('#bk-root'); if (root && root.dataset.turf) cfg.turfName = root.dataset.turf;
      if (root && root.dataset.ticket) cfg.ticketBase = root.dataset.ticket;
      Picker(cfg);
    }
    // Small, quiet delight on the ticket page.
    var tk = $('[data-bk-share]');
    if (tk) tk.addEventListener('click', function () {
      var text = tk.getAttribute('data-bk-share');
      if (navigator.share) navigator.share({ text: text }).catch(function () {});
      else window.open('https://wa.me/?text=' + encodeURIComponent(text), '_blank', 'noopener');
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
