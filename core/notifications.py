"""Helpers for creating in-app notifications and dispatching Web Push
messages. Kept in one place so every view that needs to notify someone
goes through the same two calls: notify() and (inside it) push().
"""
import json
import logging

from django.conf import settings
from django.urls import reverse

from .models import Notification, PushSubscription

logger = logging.getLogger(__name__)

try:
    from pywebpush import WebPushException, webpush
    PUSH_AVAILABLE = True
except ImportError:  # pywebpush not installed yet — degrade gracefully
    PUSH_AVAILABLE = False


def notify(recipient, verb, message, match=None, request=None):
    """Create an in-app Notification and, if the recipient has push
    subscriptions, fan the same message out as a Web Push notification.
    Safe to call even if push isn't configured — it just skips that part.
    """
    note = Notification.objects.create(
        recipient=recipient, verb=verb, message=message, match=match
    )

    url = '/'
    if match:
        try:
            url = reverse('match_detail', args=[match.id])
        except Exception:
            url = '/'

    send_push_to_user(recipient, title='SquadTurf', body=message, url=url)
    return note


def send_push_to_user(user, title, body, url='/'):
    """Push `title`/`body` to every device the user has subscribed on.
    Dead subscriptions (410/404 from the push service) are cleaned up.
    """
    if not PUSH_AVAILABLE:
        return
    if not getattr(settings, 'VAPID_PRIVATE_KEY', None):
        return  # push not configured — nothing to do

    subscriptions = PushSubscription.objects.filter(user=user)
    if not subscriptions:
        return

    payload = json.dumps({'title': title, 'body': body, 'url': url})

    for sub in subscriptions:
        subscription_info = {
            'endpoint': sub.endpoint,
            'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
            )
        except WebPushException as exc:
            status = getattr(exc.response, 'status_code', None)
            if status in (404, 410):
                sub.delete()  # subscription expired / browser unsubscribed
            else:
                logger.warning("Web push failed for %s: %s", user, exc)
