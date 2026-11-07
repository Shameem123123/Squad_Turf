"""Switch booking ON for the sample turfs with realistic details, so you can
see the whole flow immediately.

    python manage.py seed_booking_demo              # fill in details + enable booking
    python manage.py seed_booking_demo --manager    # ...and create a demo turf admin login

Safe to re-run. For real turfs, use /admin/ instead (see README).
"""
from datetime import time

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.models import Profile, Turf, TurfManager

DEMO = [
    dict(sports='Football, Cricket', pitch_info='Artificial turf · 5v5 / 7v7', amenities='Floodlights, Parking, Washroom, Drinking water',
         description='A well-kept 7-a-side turf with bright floodlights and quick drainage — play right through the monsoon.',
         price_per_slot=800, peak_price_per_slot=1200, peak_starts_at=time(18, 0), weekend_is_peak=False),
    dict(sports='Football', pitch_info='Artificial turf · 5v5', amenities='Floodlights, Changing room, Cafeteria',
         description='Compact 5-a-side pitch ideal for quick evening games with the squad.',
         price_per_slot=1000, peak_price_per_slot=1400, peak_starts_at=time(18, 0), weekend_is_peak=True),
    dict(sports='Cricket, Football', pitch_info='Full-size net practice + 7v7', amenities='Floodlights, Parking, Seating',
         description='Spacious ground with cricket nets and a 7v7 pitch under lights.',
         price_per_slot=900, peak_price_per_slot=None, peak_starts_at=None, weekend_is_peak=False),
    dict(sports='Football, Box cricket', pitch_info='Enclosed turf · 6v6', amenities='Floodlights, Washroom, Parking',
         description='Fully enclosed turf — the ball stays in play and so does the energy.',
         price_per_slot=700, peak_price_per_slot=1000, peak_starts_at=time(19, 0), weekend_is_peak=True),
]


class Command(BaseCommand):
    help = "Enable booking with sample details on the seeded turfs."

    def add_arguments(self, parser):
        parser.add_argument('--manager', action='store_true', help='Also create a demo turf admin account.')

    def handle(self, *args, **opts):
        if not Turf.objects.exists():
            call_command('seed_turfs')
        turfs = list(Turf.objects.filter(is_active=True)[:len(DEMO)])
        for turf, d in zip(turfs, DEMO):
            for k, v in d.items():
                setattr(turf, k, v)
            turf.booking_enabled = True
            turf.opens_at, turf.closes_at = time(6, 0), time(0, 0)
            turf.contact_phone = turf.contact_phone or '9847000000'
            turf.save()
            self.stdout.write(f"  ✓ {turf.name} — booking enabled")
        if opts['manager'] and turfs:
            User = get_user_model()
            phone, pw = '9000000099', 'turfadmin123'
            profile = Profile.objects.filter(phone=phone).first()
            if profile:
                user = profile.user
            else:
                user = User.objects.create_user(username='demo_turf_admin', first_name='Demo Turf Admin', password=pw)
                Profile.objects.create(user=user, phone=phone, is_available_for_alerts=False)
            TurfManager.objects.get_or_create(user=user, turf=turfs[0])
            self.stdout.write(self.style.WARNING(
                f"\nDemo turf admin for {turfs[0].name}: phone {phone} / password {pw}\n"
                "Delete this account before going live."))
        self.stdout.write(self.style.SUCCESS("Done."))
