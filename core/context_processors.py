"""Template context shared by every page."""
from . import booking_logic as bl
from .models import PushSubscription
from .notifications import active_for


def unread_notifications(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    return {
        'unread_notification_count': active_for(user).filter(is_read=False).count(),
        'has_push_subscription': PushSubscription.objects.filter(user=user).exists(),
    }


def turf_admin_context(request):
    """Lets the navigation show the turf console to turf managers (an account type
    only the site admin can create) and the player navigation to everyone else."""
    if not request.user.is_authenticated:
        return {}
    turfs = bl.managed_turfs(request.user)
    return {'is_turf_admin': bool(turfs), 'managed_turfs': turfs}
