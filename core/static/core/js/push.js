// SquadTurf — Web Push subscription helper.
// Called from base.html for logged-in users. Handles: registering the
// service worker, asking for notification permission, subscribing with
// the server's VAPID public key, and POSTing the subscription so the
// backend can reach this device even when no tab is open.

(function () {
  function urlBase64ToUint8Array(base64String) {
    var padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var rawData = window.atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  function getCookie(name) {
    var match = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return match ? match.pop() : '';
  }

  var REASON_MESSAGES = {
    unsupported: "Push notifications aren't supported in this browser.",
    denied: "Notification permission was blocked. Enable it in your browser's site settings and try again.",
    not_configured: 'Push isn\u2019t configured on the server yet.',
    subscribe_failed: "Couldn't set up notifications on this device. Please try again.",
    server_failed: "Saved locally, but the server didn't confirm the subscription. Please try again.",
  };

  async function subscribeToPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      return { ok: false, reason: 'unsupported' };
    }

    var permission;
    try {
      permission = await Notification.requestPermission();
    } catch (e) {
      return { ok: false, reason: 'denied' };
    }
    if (permission !== 'granted') {
      return { ok: false, reason: 'denied' };
    }

    var registration;
    try {
      registration = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
    } catch (e) {
      return { ok: false, reason: 'subscribe_failed' };
    }

    var keyData;
    try {
      var keyResp = await fetch('/push/vapid-public-key/');
      keyData = await keyResp.json();
    } catch (e) {
      return { ok: false, reason: 'not_configured' };
    }
    if (!keyData.publicKey) {
      return { ok: false, reason: 'not_configured' };
    }

    var subscription;
    try {
      var existing = await registration.pushManager.getSubscription();
      subscription = existing || await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(keyData.publicKey),
      });
    } catch (e) {
      return { ok: false, reason: 'subscribe_failed' };
    }

    try {
      var saveResp = await fetch('/push/subscribe/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify(subscription.toJSON()),
      });
      if (!saveResp.ok) {
        return { ok: false, reason: 'server_failed' };
      }
    } catch (e) {
      return { ok: false, reason: 'server_failed' };
    }

    return { ok: true };
  }

  // ---- The whistle -------------------------------------------------------
  // Every event type has its own whistle *audio file* under
  // /static/core/audio/ (see AUDIO_FILES below). To try a different sound,
  // just replace the file — keep the same filename and it's picked up
  // automatically, no code changes needed. See
  // static/core/audio/README.txt for exact filenames + tips.
  //
  // If a file is missing or fails to load, playWhistle() falls back to a
  // whistle synthesized live with the Web Audio API, so sound never breaks:
  //   - a bright sawtooth+square tone pair (the "brass" of a pea whistle)
  //   - band-pass filtered around ~2.6-3.4kHz, where real whistles sit
  //   - a fast ~13-16Hz pitch warble (the rolling "pea" trill)
  //   - a snappy attack/decay envelope so each blast has a real "puff"
  // Patterns below string multiple blasts/gaps together per event type —
  // e.g. a cancelled match gets two slight whistles then one long one.

  var AUDIO_FILES = {
    NEW_MATCH: '/static/core/audio/new_match.wav',
    JOIN_REQUEST: '/static/core/audio/join_request.wav',
    REQUEST_ACCEPTED: '/static/core/audio/request_accepted.wav',
    REQUEST_DECLINED: '/static/core/audio/request_declined.wav',
    PLAYER_LEFT: '/static/core/audio/player_left.wav',
    MATCH_FILLED: '/static/core/audio/match_filled.wav',
    MATCH_CANCELLED: '/static/core/audio/match_cancelled.wav',
    REMINDER: '/static/core/audio/reminder.wav',
    KICKOFF: '/static/core/audio/new_match.wav',
    DEFAULT: '/static/core/audio/default.wav',
  };

  // One <audio> element per file, created lazily and reused so repeated
  // notifications don't re-fetch the file every time.
  var audioElCache = {};
  function getAudioEl(verb) {
    var src = AUDIO_FILES[verb] || AUDIO_FILES.DEFAULT;
    if (!audioElCache[src]) {
      var el = new Audio(src);
      el.preload = 'auto';
      el.volume = 0.9;
      audioElCache[src] = el;
    }
    return audioElCache[src];
  }

  function playRealFile(verb) {
    return new Promise(function (resolve, reject) {
      try {
        var el = getAudioEl(verb);
        el.currentTime = 0;
        var p = el.play();
        if (p && p.then) {
          p.then(resolve).catch(reject);
        } else {
          resolve();
        }
      } catch (e) {
        reject(e);
      }
    });
  }

  var audioCtx = null;
  function getCtx() {
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!audioCtx) {
      try { audioCtx = new AC(); } catch (e) { return null; }
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(function () { /* needs a user gesture first — fine */ });
    }
    return audioCtx;
  }

  function blast(ctx, startTime, duration, opts) {
    opts = opts || {};
    var baseFreq = opts.freq || 3000;
    var bend = opts.bend || 0;
    var volume = opts.volume != null ? opts.volume : 0.75;
    var warbleRate = opts.warbleRate != null ? opts.warbleRate : 14;
    var warbleDepth = opts.warbleDepth != null ? opts.warbleDepth : 85;
    var stopAt = startTime + duration + 0.03;

    var osc = ctx.createOscillator();
    osc.type = 'sawtooth';
    var osc2 = ctx.createOscillator();
    osc2.type = 'square';

    var filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.value = baseFreq;
    filter.Q.value = 6.5;

    var gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, startTime);
    gain.gain.exponentialRampToValueAtTime(Math.max(volume, 0.001), startTime + 0.014);
    gain.gain.setValueAtTime(volume, startTime + Math.max(duration - 0.045, 0.016));
    gain.gain.exponentialRampToValueAtTime(0.0001, stopAt);

    var lfo = ctx.createOscillator();
    lfo.type = 'sine';
    lfo.frequency.value = warbleRate;
    var lfoGain = ctx.createGain();
    lfoGain.gain.value = warbleDepth;
    lfo.connect(lfoGain);
    lfoGain.connect(osc.frequency);
    lfoGain.connect(osc2.frequency);

    osc.frequency.setValueAtTime(baseFreq, startTime);
    osc2.frequency.setValueAtTime(baseFreq * 1.01, startTime);
    if (bend) {
      osc.frequency.linearRampToValueAtTime(baseFreq + bend, stopAt);
      osc2.frequency.linearRampToValueAtTime(baseFreq * 1.01 + bend, stopAt);
    }

    osc.connect(filter);
    osc2.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);

    osc.start(startTime); osc.stop(stopAt);
    osc2.start(startTime); osc2.stop(stopAt);
    lfo.start(startTime); lfo.stop(stopAt);
  }

  // Each entry is a sequence of blasts. `gap` is the silence (seconds)
  // after that particular blast before the next one starts.
  var PATTERNS = {
    // One-time "kick off" landing sting — short, sharp, rising.
    KICKOFF: [
      { freq: 3000, duration: 0.2, bend: 260, volume: 0.7 },
    ],
    // Someone wants to join your match: one clean, medium call.
    JOIN_REQUEST: [
      { freq: 2900, duration: 0.22, bend: 70, volume: 0.75 },
    ],
    // Your request got accepted: one long, confident, rising blast.
    REQUEST_ACCEPTED: [
      { freq: 2850, duration: 0.62, bend: 420, volume: 0.8 },
    ],
    // Declined: one short, low, falling blast — deliberately duller.
    REQUEST_DECLINED: [
      { freq: 2550, duration: 0.2, bend: -320, volume: 0.62 },
    ],
    // A player dropped out: short, neutral, slightly falling.
    PLAYER_LEFT: [
      { freq: 2650, duration: 0.18, bend: -150, volume: 0.62 },
    ],
    // Match filled up: three quick ascending blasts — celebratory.
    MATCH_FILLED: [
      { freq: 2850, duration: 0.11, bend: 40, volume: 0.72, gap: 0.06 },
      { freq: 3050, duration: 0.11, bend: 40, volume: 0.76, gap: 0.06 },
      { freq: 3350, duration: 0.18, bend: 120, volume: 0.85 },
    ],
    // Cancelled: two slight whistles, then one long whistle. As specific
    // and "matchday" as it gets — this is how referees call off play.
    MATCH_CANCELLED: [
      { freq: 2750, duration: 0.11, bend: 0, volume: 0.55, warbleRate: 12, gap: 0.1 },
      { freq: 2750, duration: 0.11, bend: 0, volume: 0.55, warbleRate: 12, gap: 0.24 },
      { freq: 2650, duration: 0.7, bend: -180, volume: 0.8, warbleRate: 13 },
    ],
    // Pre-match reminder: single, softer, medium-length call.
    REMINDER: [
      { freq: 2800, duration: 0.3, bend: 60, volume: 0.55 },
    ],
    // New match posted nearby / generic fallback: a crisp double-tap.
    DEFAULT: [
      { freq: 3000, duration: 0.1, bend: 0, volume: 0.68, gap: 0.075 },
      { freq: 3250, duration: 0.14, bend: 60, volume: 0.75 },
    ],
  };
  PATTERNS.NEW_MATCH = PATTERNS.DEFAULT;

  var fallbackAudio = null;
  function playFallback() {
    try {
      if (!fallbackAudio) {
        fallbackAudio = new Audio('/static/core/audio/whistle.wav');
        fallbackAudio.volume = 0.85;
      }
      fallbackAudio.currentTime = 0;
      var p = fallbackAudio.play();
      if (p && p.catch) p.catch(function () { /* autoplay blocked until first gesture — fine */ });
    } catch (e) { /* ignore */ }
  }

  function playSynthesized(verb) {
    var ctx = getCtx();
    if (!ctx) {
      playFallback();
      return;
    }
    try {
      var pattern = PATTERNS[verb] || PATTERNS.DEFAULT;
      var t = ctx.currentTime + 0.015;
      pattern.forEach(function (note) {
        blast(ctx, t, note.duration, note);
        t += note.duration + (note.gap || 0.03);
      });
    } catch (e) {
      playFallback();
    }
  }

  // Real audio file first (this is what picks up manually swapped-in
  // sounds); if it's missing/blocked/fails, fall back to the live synth
  // so a broken/missing file never means silence.
  function playWhistle(verb) {
    playRealFile(verb).catch(function () {
      playSynthesized(verb);
    });
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', function (event) {
      if (event.data && event.data.type === 'squadturf-push') {
        playWhistle(event.data.verb);
      }
    });
  }

  window.SquadTurfPush = {
    subscribe: subscribeToPush,
    playWhistle: playWhistle,
    messageFor: function (reason) {
      return REASON_MESSAGES[reason] || "Couldn't enable notifications. Please try again.";
    },
  };
})();
