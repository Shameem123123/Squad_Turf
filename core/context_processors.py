from .models import Notification


def unread_notifications(request):
    if not request.user.is_authenticated:
        return {}
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return {'unread_notification_count': count}
