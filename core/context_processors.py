from django.db.models import Q

from .models import JoinRequest, Match, Notification, PushSubscription


def unread_notifications(request):
    if not request.user.is_authenticated:
        return {}
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    has_push_subscription = PushSubscription.objects.filter(user=request.user).exists()

    # Same signature formula as views.live_status() — lets live.js know,
    # on first paint, what "no change yet" looks like before its first poll.
    latest_match_id = Match.objects.order_by('-id').values_list('id', flat=True).first() or 0
    latest_notif_id = Notification.objects.filter(recipient=request.user).order_by('-id') \
        .values_list('id', flat=True).first() or 0
    latest_join_id = JoinRequest.objects.filter(
        Q(match__host=request.user) | Q(player=request.user)
    ).order_by('-id').values_list('id', flat=True).first() or 0
    live_sig = f"{latest_match_id}-{latest_notif_id}-{latest_join_id}"

    return {
        'unread_notification_count': count,
        'live_sig': live_sig,
        'has_push_subscription': has_push_subscription,
    }


def turf_admin_context(request):
    """Tells base.html whether the signed-in person is a *turf admin* (a second
    account type that only the site admin can create) so it can show the
    console navigation instead of the player navigation."""
    if not request.user.is_authenticated:
        return {}
    from django.urls import reverse
    from .booking_logic import managed_turfs
    turfs = managed_turfs(request.user)
    return {
        'is_turf_admin': bool(turfs),
        'managed_turfs': turfs,
        'console_url': reverse('manage_home'),
    }
