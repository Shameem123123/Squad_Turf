"""Creating in-app notifications and delivering Web Push.

Everything that needs to tell someone something goes through ``notify()``.
In-app notifications live for ``NOTIFICATION_TTL`` (one week) and are then
removed, so the list stays short and relevant.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connections, transaction
from django.urls import reverse
from django.utils import timezone

from .models import Notification, PushSubscription

logger = logging.getLogger(__name__)

try:
    from pywebpush import WebPushException, webpush
    PUSH_AVAILABLE = True
except ImportError:  # pywebpush not installed — degrade gracefully
    PUSH_AVAILABLE = False

NOTIFICATION_TTL = timedelta(days=7)
PUSH_TTL_SECONDS = 3600        # keep trying for an hour if the device is asleep/offline
PURGE_EVERY_SECONDS = 3600     # opportunistic clean-up, at most once an hour per process

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='push')


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def cutoff():
    return timezone.now() - NOTIFICATION_TTL


def active_for(user):
    """This person's notifications that haven't expired yet."""
    return Notification.objects.filter(recipient=user, created_at__gte=cutoff())


def purge_expired(user=None):
    """Delete notifications older than a week. Returns how many were removed."""
    qs = Notification.objects.filter(created_at__lt=cutoff())
    if user is not None:
        qs = qs.filter(recipient=user)
    return qs.delete()[0]


def _purge_occasionally():
    if cache.add('notifications-purged', 1, PURGE_EVERY_SECONDS):
        try:
            purge_expired()
        except Exception:  # housekeeping must never break a request
            logger.exception("Notification purge failed")


# ---------------------------------------------------------------------------
# Creating + delivering
# ---------------------------------------------------------------------------

def notify(recipient, verb, message, match=None, request=None, booking=None, url=None):
    """Create an in-app Notification and fan the same message out as Web Push.
    Safe to call even if push isn't configured."""
    note = Notification.objects.create(
        recipient=recipient, verb=verb, message=message, match=match, booking=booking
    )
    url = url or _default_url(match)
    payload = json.dumps({'title': 'SquadTurf', 'body': message, 'url': url, 'verb': verb})
    transaction.on_commit(lambda: _dispatch(recipient.pk, payload))
    _purge_occasionally()
    return note


def notify_many(recipients, verb, message, match=None, url=None):
    """Same message to many people with one INSERT (e.g. a new match broadcast)."""
    users = list(recipients)
    if not users:
        return 0
    Notification.objects.bulk_create(
        [Notification(recipient=u, verb=verb, message=message, match=match) for u in users]
    )
    payload = json.dumps({
        'title': 'SquadTurf', 'body': message, 'url': url or _default_url(match), 'verb': verb,
    })
    for user in users:
        transaction.on_commit(lambda uid=user.pk: _dispatch(uid, payload))
    _purge_occasionally()
    return len(users)


def _default_url(match):
    if match is not None:
        return reverse('match_detail', args=[match.id])
    return '/'


def _dispatch(user_id, payload):
    if not PUSH_AVAILABLE or not getattr(settings, 'VAPID_PRIVATE_KEY', None):
        return
    if getattr(settings, 'PUSH_ASYNC', True):
        _executor.submit(_deliver_in_thread, user_id, payload)
    else:
        _deliver(user_id, payload)


def _deliver_in_thread(user_id, payload):
    try:
        _deliver(user_id, payload)
    finally:
        connections.close_all()  # worker threads own their DB connections


def _deliver(user_id, payload):
    """Push `payload` to every device the user subscribed on. Dead
    subscriptions (404/410 from the push service) are cleaned up."""
    for sub in PushSubscription.objects.filter(user_id=user_id):
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
                ttl=PUSH_TTL_SECONDS,
                headers={'Urgency': 'high'},
            )
        except WebPushException as exc:
            status = getattr(exc.response, 'status_code', None)
            if status in (404, 410):
                sub.delete()
            else:
                logger.warning("Web push failed for user %s: %s", user_id, exc)
        except Exception:
            logger.exception("Unexpected push failure for user %s", user_id)
