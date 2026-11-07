"""Reminds players ~1 hour before a booked slot. Idempotent — run it often:

    */5 * * * * cd /path/to/squadturf && python manage.py send_booking_reminders
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from core import booking_logic as bl
from core.models import Booking, Notification
from core.notifications import notify


class Command(BaseCommand):
    help = "Notify players about bookings starting within the next hour."

    def handle(self, *args, **options):
        now = timezone.now()
        due = Booking.objects.filter(
            status=Booking.Status.CONFIRMED, source=Booking.Source.ONLINE, reminder_sent=False,
            user__isnull=False, start_at__gt=now, start_at__lte=now + timedelta(hours=1),
        ).select_related('turf', 'user')
        sent = 0
        for b in due:
            notify(
                b.user, Notification.Verb.BOOKING_REMINDER,
                f"Game on soon! {b.turf.name} · {bl.fmt_range(b.start_at, b.end_at)}. Ref {b.reference}.",
                booking=b, url=reverse('booking_detail', args=[b.reference]),
            )
            b.reminder_sent = True
            b.save(update_fields=['reminder_sent'])
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} booking reminder(s)."))
