"""Deletes notifications older than a week. Optional — the app also does this
by itself roughly once an hour — but handy as a cron job:

    0 3 * * * cd /path/to/squadturf && python manage.py purge_notifications
"""
from django.core.management.base import BaseCommand

from core.notifications import NOTIFICATION_TTL, purge_expired


class Command(BaseCommand):
    help = "Remove in-app notifications older than 7 days."

    def handle(self, *args, **options):
        removed = purge_expired()
        self.stdout.write(self.style.SUCCESS(
            f"Removed {removed} notification(s) older than {NOTIFICATION_TTL.days} days."
        ))
