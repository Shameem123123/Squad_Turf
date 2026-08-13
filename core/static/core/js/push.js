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

  // ---- Notification sound -------------------------------------------------
  // Deliberately ONE sound for every event type — matching a normal phone's
  // "usual notification tone" instead of a distinct jingle per verb. This is
  // only ever used as an in-page fallback for the moment a system push
  // notification's own sound gets suppressed by the browser (see the
  // hasFocus() guard around playNotificationSound() below); it is never
  // meant to layer on top of the system sound, only substitute for it.
  //
  // If the bundled file is missing or fails to load, playNotificationSound()
  // falls back to a single short tone synthesized live with the Web Audio
  // API, so sound never breaks silently.

  var DEFAULT_AUDIO_SRC = '/static/core/audio/default.wav';

  // One <audio> element, created lazily and reused so repeated notifications
  // don't re-fetch the file every time.
  var defaultAudioEl = null;
  function getAudioEl() {
    if (!defaultAudioEl) {
      defaultAudioEl = new Audio(DEFAULT_AUDIO_SRC);
      defaultAudioEl.preload = 'auto';
      defaultAudioEl.volume = 0.9;
    }
    return defaultAudioEl;
  }

  function playRealFile() {
    return new Promise(function (resolve, reject) {
      try {
        var el = getAudioEl();
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

  // A single short, neutral "blip" — the same tone every time, regardless
  // of event type. This is a generic stand-in for a phone's default
  // notification tone, not a distinct sound per verb.
  function playTone(ctx, startTime) {
    var duration = 0.16;
    var stopAt = startTime + duration + 0.03;

    var osc = ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, startTime);

    var gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, startTime);
    gain.gain.exponentialRampToValueAtTime(0.5, startTime + 0.012);
    gain.gain.setValueAtTime(0.5, startTime + duration - 0.05);
    gain.gain.exponentialRampToValueAtTime(0.0001, stopAt);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(startTime);
    osc.stop(stopAt);
  }

  var fallbackAudio = null;
  function playFallback() {
    try {
      if (!fallbackAudio) {
        fallbackAudio = new Audio(DEFAULT_AUDIO_SRC);
        fallbackAudio.volume = 0.85;
      }
      fallbackAudio.currentTime = 0;
      var p = fallbackAudio.play();
      if (p && p.catch) p.catch(function () { /* autoplay blocked until first gesture — fine */ });
    } catch (e) { /* ignore */ }
  }

  function playSynthesized() {
    var ctx = getCtx();
    if (!ctx) {
      playFallback();
      return;
    }
    try {
      playTone(ctx, ctx.currentTime + 0.015);
    } catch (e) {
      playFallback();
    }
  }

  // Real audio file first (this is what picks up a manually swapped-in
  // sound); if it's missing/blocked/fails, fall back to the live synth
  // so a broken/missing file never means silence.
  function playSound() {
    playRealFile().catch(function () {
      playSynthesized();
    });
  }

  // ---- Avoiding the double-notification-sound bug ------------------------
  // A system push notification (shown by the service worker) already plays
  // the device's own "usual notification sound" on its own — that's the
  // ONE sound a push should ever produce. The only gap is that most
  // browsers mute/suppress that system sound while the tab that owns the
  // page is focused in the foreground. So: only play this in-page sound
  // when the tab is actually focused (i.e. the case the system sound would
  // otherwise skip), and never in the background/closed-tab case where the
  // system notification is already handling it — that combination is what
  // used to cause two sounds to fire together.
  //
  // A short cooldown lock also guards against the push relay (below) and
  // live.js's poller both reacting to the same underlying event and each
  // trying to play a sound moments apart.
  var lastPlayedAt = 0;
  var SOUND_COOLDOWN_MS = 1500;
  function playNotificationSound() {
    if (!document.hasFocus() || document.hidden) return;
    var now = Date.now();
    if (now - lastPlayedAt < SOUND_COOLDOWN_MS) return;
    lastPlayedAt = now;
    playSound();
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', function (event) {
      if (event.data && event.data.type === 'squadturf-push') {
        playNotificationSound();
      }
    });
  }

  window.SquadTurfPush = {
    subscribe: subscribeToPush,
    playNotificationSound: playNotificationSound,
    messageFor: function (reason) {
      return REASON_MESSAGES[reason] || "Couldn't enable notifications. Please try again.";
    },
  };
})();
