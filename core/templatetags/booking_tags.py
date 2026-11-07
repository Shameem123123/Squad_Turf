from decimal import Decimal

from django import template
from django.urls import reverse
from django.utils import timezone

from .. import booking_logic as bl
from ..models import Turf

register = template.Library()


@register.filter
def inr(value):
    try:
        value = Decimal(value)
    except Exception:
        return value
    return f"₹{int(value):,}" if value == value.to_integral_value() else f"₹{value:,.2f}"


@register.filter
def cover_hue(slug):
    """Stable hue (green→teal→blue) per turf so every cover feels distinct."""
    return 118 + (sum(ord(c) * (i + 3) for i, c in enumerate(str(slug))) % 100)


@register.filter
def bk_time(dt):
    return bl.fmt_time(dt)


@register.filter
def bk_range(booking):
    return bl.fmt_range(booking.start_at, booking.end_at)


@register.filter
def bk_day(dt):
    return bl.fmt_day(dt, long=True)


@register.filter
def bk_date_iso(dt):
    return timezone.localtime(dt).date().isoformat()


@register.filter
def bk_mins(minutes):
    h, m = divmod(int(minutes), 60)
    return f"{h} hr {m} min" if h and m else (f"{h} hr" if h else f"{m} min")


@register.filter
def bk_clock(t):
    return t.strftime('%I:%M %p').lstrip('0') if t else ''


@register.simple_tag(takes_context=True)
def notification_link(context, note):
    """Where a notification should open for *this* viewer."""
    user = context['request'].user
    b = note.booking
    if b:
        if b.user_id == user.id:
            return reverse('booking_detail', args=[b.reference])
        return f"{reverse('manage_schedule', args=[b.turf.slug])}?date={bk_date_iso(b.start_at)}"
    return None


@register.inclusion_tag('core/booking/_strip.html')
def bookable_strip():
    turfs = list(Turf.objects.filter(is_active=True, booking_enabled=True)[:6])
    return {'cards': [{'turf': t, 'free_today': bl.free_slots_today(t)} for t in turfs]}
