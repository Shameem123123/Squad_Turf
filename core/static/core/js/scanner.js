/* Turf manager ticket scanner.
 * Camera + BarcodeDetector (Chrome/Edge/Android) reads the QR on a ticket; the server
 * checks its signature. Manual entry of the booking reference works in every browser. */
(function () {
  'use strict';
  var cfgNode = document.getElementById('scan-cfg');
  if (!cfgNode) return;
  var cfg = JSON.parse(cfgNode.textContent);

  var video = document.getElementById('scan-video');
  var msg = document.getElementById('scan-msg');
  var out = document.getElementById('scan-result');
  var manual = document.getElementById('scan-manual');
  var stream = null, detector = null, scanning = false, lastCode = '', lastAt = 0, raf = 0;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function inr(n) { return '₹' + Number(n).toLocaleString('en-IN'); }
  function buzz(p) { try { navigator.vibrate && navigator.vibrate(p); } catch (e) { /* noop */ } }

  function post(url, data) {
    var body = new URLSearchParams(data);
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), Accept: 'application/json' }, body: body,
    }).then(function (r) {
      var type = r.headers.get('content-type') || '';
      if (r.status === 403 || r.redirected || type.indexOf('json') < 0) throw new Error('session');
      return r.json().then(function (j) { j._status = r.status; return j; });
    });
  }

  /* ---- result card ------------------------------------------------------------ */
  var TONE = { ok: 'is-ok', used: 'is-warn', early: 'is-warn' };
  function show(res) {
    out.textContent = '';
    out.hidden = false;
    out.className = 'st-result ' + (TONE[res.state] || 'is-bad');
    var verdict = el('div', 'verdict');
    verdict.appendChild(el('i', null, res.state === 'ok' ? '✓' : (TONE[res.state] ? '!' : '×')));
    verdict.appendChild(el('span', null, res.message));
    out.appendChild(verdict);

    var b = res.booking;
    if (b) {
      var sum = el('div', 'st-sum');
      [['Name', b.name], ['Time', b.day + ', ' + b.range], ['Slots', String(b.slots)],
       ['Payment', b.paid ? 'Paid' : inr(b.amount) + ' to collect'], ['Reference', b.ref]]
        .forEach(function (r) {
          var row = el('div', 'st-sum-row');
          row.appendChild(el('span', null, r[0]));
          row.appendChild(el('b', null, r[1]));
          sum.appendChild(row);
        });
      out.appendChild(sum);

      if (res.admit) {
        var box = el('div', 'st-stack');
        if (!b.paid) box.appendChild(button('Collect ' + inr(b.amount) + ' & admit', 'st-btn st-btn-block', function () { admit(b.ref, true); }));
        box.appendChild(button(b.paid ? 'Admit' : 'Admit without payment', b.paid ? 'st-btn st-btn-block' : 'st-btn st-btn-soft st-btn-block', function () { admit(b.ref, false); }));
        out.appendChild(box);
      }
    }
    var next = button('Scan next', 'st-btn st-btn-outline st-btn-block', resume);
    next.style.marginTop = '10px';
    out.appendChild(next);
    buzz(res.state === 'ok' ? 30 : [60, 40, 60]);
    out.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function button(label, cls, fn) {
    var b = el('button', cls, label);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }
  function fail(e) {
    show({ state: 'invalid', message: e.message === 'session' ? 'Session expired. Reload and log in.' : 'Network problem. Try again.' });
  }

  /* ---- verify & admit ------------------------------------------------------------- */
  function verify(code, isManual) {
    pause();
    window.StProgress && window.StProgress.start();
    post(cfg.verifyUrl, { code: code, manual: isManual ? '1' : '0' })
      .then(show).catch(fail)
      .finally(function () { window.StProgress && window.StProgress.done(); });
  }
  function admit(ref, collect) {
    window.StProgress && window.StProgress.start();
    post(cfg.admitUrl, { ref: ref, collect: collect ? '1' : '0' })
      .then(function (res) {
        if (res.ok) {
          out.textContent = '';
          out.className = 'st-result is-ok';
          var v = el('div', 'verdict');
          v.appendChild(el('i', null, '✓'));
          v.appendChild(el('span', null, 'Admitted'));
          out.appendChild(v);
          var next = button('Scan next', 'st-btn st-btn-block', resume);
          next.style.marginTop = '14px';
          out.appendChild(next);
          buzz(30);
        } else { show(res); }
      }).catch(fail)
      .finally(function () { window.StProgress && window.StProgress.done(); });
  }

  /* ---- camera loop ----------------------------------------------------------------- */
  function say(text) { msg.textContent = text; msg.hidden = !text; }

  function tick() {
    if (!scanning) return;
    detector.detect(video).then(function (codes) {
      var now = Date.now();
      if (codes.length) {
        var v = codes[0].rawValue;
        if (v && (v !== lastCode || now - lastAt > 4000)) {
          lastCode = v; lastAt = now;
          return verify(v, false);
        }
      }
      raf = setTimeout(function () { requestAnimationFrame(tick); }, 150);
    }).catch(function () { raf = setTimeout(function () { requestAnimationFrame(tick); }, 400); });
  }
  function pause() { scanning = false; clearTimeout(raf); }
  function resume() {
    out.hidden = true;
    if (!stream) return start();
    scanning = true;
    tick();
  }

  function start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) {
      return say('Camera needs a secure (https) connection. Enter the code below instead.');
    }
    if (!('BarcodeDetector' in window)) {
      return say("This browser can't read QR codes. Use Chrome on Android, or enter the code below.");
    }
    detector = new window.BarcodeDetector({ formats: ['qr_code'] });
    say('Starting camera…');
    navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
      .then(function (s) {
        stream = s;
        video.srcObject = s;
        return video.play();
      })
      .then(function () { say(''); scanning = true; tick(); })
      .catch(function () { say('Camera blocked. Allow camera access, or enter the code below.'); });
  }
  function stop() {
    pause();
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null;
  }

  manual.addEventListener('submit', function (e) {
    e.preventDefault();
    var input = manual.elements.code;
    if (input.value.trim()) { verify(input.value.trim(), true); input.value = ''; }
  });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stop(); else if (out.hidden) start();
  });
  window.addEventListener('pagehide', stop);
  start();
})();
