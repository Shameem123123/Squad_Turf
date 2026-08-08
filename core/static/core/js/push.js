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

  window.SquadTurfPush = {
    subscribe: subscribeToPush,
    messageFor: function (reason) {
      return REASON_MESSAGES[reason] || "Couldn't enable notifications. Please try again.";
    },
  };
})();
