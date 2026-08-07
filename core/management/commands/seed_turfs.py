from django.core.management.base import BaseCommand
from django.utils.text import slugify

from core.models import Turf

SAMPLE_TURFS = [
    ("Arena Malaparamba", "Malaparamba, Kozhikode"),
    ("Green Turf West Hill", "West Hill, Kozhikode"),
    ("Kicksters Football Park", "Kannur Road, Kozhikode"),
    ("Victory Sports Arena", "Mavoor Road, Kozhikode"),
]


class Command(BaseCommand):
    help = "Seed the database with a handful of sample turfs."

    def handle(self, *args, **options):
        created_count = 0
        for name, location in SAMPLE_TURFS:
            slug = slugify(name)
            _, created = Turf.objects.get_or_create(
                slug=slug, defaults={'name': name, 'location_name': location}
            )
            if created:
                created_count += 1
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created_count} new turf(s). {Turf.objects.count()} total."
        ))
