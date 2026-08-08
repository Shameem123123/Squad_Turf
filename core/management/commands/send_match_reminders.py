"""Sends each host a heads-up ~30 minutes before their match kicks off,
telling them how many players are confirmed — so a last-minute drop-out
is visible before everyone's already at the turf.

Run this on a schedule (it's idempotent — safe to run often):

    */5 * * * * cd /path/to/squadturf && python manage.py send_match_reminders

No Celery/Redis required — a plain cron entry is enough for this scale.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import JoinRequest, Match, Notification
from core.notifications import notify

REMINDER_WINDOW_START = timedelta(minutes=25)
REMINDER_WINDOW_END = timedelta(minutes=35)


class Command(BaseCommand):
    help = "Notify hosts ~30 minutes before kickoff with their confirmed headcount."

    def handle(self, *args, **options):
        now = timezone.now()
        window_start = now + REMINDER_WINDOW_START
        window_end = now + REMINDER_WINDOW_END

        due_matches = Match.objects.filter(
            status__in=[Match.Status.OPEN, Match.Status.FILLED],
            reminder_sent=False,
            match_time__gte=window_start,
            match_time__lte=window_end,
        ).select_related('turf', 'host')

        sent = 0
        for match in due_matches:
            accepted_count = JoinRequest.objects.filter(
                match=match, status=JoinRequest.Status.ACCEPTED
            ).count()

            if accepted_count > 0:
                message = (
                    f"Kickoff in ~30 min at {match.turf.name}: {accepted_count} "
                    f"player{'s' if accepted_count != 1 else ''} confirmed. "
                    f"Ready to play?"
                )
            else:
                message = (
                    f"Kickoff in ~30 min at {match.turf.name} and no one's "
                    f"confirmed yet — might be worth a nudge."
                )

            notify(match.host, Notification.Verb.REMINDER, message, match=match)
            match.reminder_sent = True
            match.save(update_fields=['reminder_sent'])
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} pre-match reminder(s)."))
