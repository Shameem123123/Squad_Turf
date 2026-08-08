from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def relative_day(value):
    """Today/Tomorrow/Yesterday + time for nearby dates; a full date for
    anything further out. Matches the dashboards' "no clutter" date rule.
    """
    if not value:
        return ''
    local_now = timezone.localtime(timezone.now())
    local_value = timezone.localtime(value)
    delta_days = (local_value.date() - local_now.date()).days
    time_str = local_value.strftime('%I:%M %p').lstrip('0')

    if delta_days == 0:
        return f"Today, {time_str}"
    if delta_days == 1:
        return f"Tomorrow, {time_str}"
    if delta_days == -1:
        return f"Yesterday, {time_str}"
    return local_value.strftime('%d %b %Y, %I:%M %p').lstrip('0')


@register.filter
def day_bucket(value):
    """Returns 'today' / 'tomorrow' / 'other' for a datetime, used to
    tag match cards for the client-side day-bubble filter."""
    if not value:
        return 'other'
    local_now = timezone.localtime(timezone.now())
    local_value = timezone.localtime(value)
    delta_days = (local_value.date() - local_now.date()).days
    if delta_days == 0:
        return 'today'
    if delta_days == 1:
        return 'tomorrow'
    return 'other'


@register.filter
def stars_range(value):
    """[1..5] range for rendering star icons regardless of input type."""
    return range(1, 6)
