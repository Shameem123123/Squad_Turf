import secrets
from datetime import time, timedelta
from urllib.parse import quote_plus

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Q
from django.utils import timezone


class Turf(models.Model):
    """A physical ground / arena that matches are hosted at."""

    name = models.CharField(max_length=120)
    location_name = models.CharField(max_length=200)
    slug = models.SlugField(
        unique=True,
        help_text="Used in the QR landing URL, e.g. /t/arena-malaparamba/",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ------------------------------------------------------------------
    # Slot booking (all optional). A turf only becomes bookable once the
    # site admin switches `booking_enabled` on — everything below is inert
    # until then, so existing turfs behave exactly as before.
    # ------------------------------------------------------------------
    SLOT_LENGTH_CHOICES = [
        (30, '30 minutes'), (60, '1 hour'), (90, '90 minutes'), (120, '2 hours'),
    ]

    booking_enabled = models.BooleanField(
        default=False,
        help_text="Master switch. Turn on once the turf is onboarded and its details are filled in "
                  "— only then does it appear under Book a turf.",
    )
    bookings_paused = models.BooleanField(
        default=False,
        help_text="Temporarily stop new online bookings. The turf admin can flip this too.",
    )
    description = models.TextField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    map_url = models.URLField(blank=True, help_text="Google Maps link (optional) — used for Directions.")
    cover_image_url = models.URLField(
        max_length=500, blank=True,
        help_text="Direct link to a cover photo (optional). A designed gradient is used if left blank.",
    )
    sports = models.CharField(max_length=200, blank=True, help_text="Comma separated, e.g. Football, Cricket")
    amenities = models.CharField(
        max_length=300, blank=True, help_text="Comma separated, e.g. Floodlights, Parking, Washroom"
    )
    pitch_info = models.CharField(max_length=120, blank=True, help_text="e.g. Artificial turf · 5v5 / 7v7")
    contact_phone = models.CharField(max_length=15, blank=True)

    opens_at = models.TimeField(default=time(6, 0))
    closes_at = models.TimeField(
        default=time(23, 0), help_text="Use 12:00 AM (midnight) to run until the end of the day."
    )
    slot_minutes = models.PositiveSmallIntegerField(default=60, choices=SLOT_LENGTH_CHOICES)
    max_slots_per_booking = models.PositiveSmallIntegerField(
        default=4, validators=[MinValueValidator(1), MaxValueValidator(8)]
    )
    advance_days = models.PositiveSmallIntegerField(
        default=14, validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text="How many days ahead players can book.",
    )
    cancel_before_hours = models.PositiveSmallIntegerField(
        default=4, validators=[MaxValueValidator(72)],
        help_text="Players can cancel for free until this many hours before the start.",
    )

    price_per_slot = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    peak_price_per_slot = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    peak_starts_at = models.TimeField(
        null=True, blank=True, help_text="Peak price applies from this time until closing."
    )
    weekend_is_peak = models.BooleanField(default=False, help_text="Charge the peak price all day Sat & Sun.")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.location_name})"

    # ---- booking helpers ------------------------------------------------
    @staticmethod
    def _csv(value):
        return [p.strip() for p in (value or '').split(',') if p.strip()]

    @property
    def sport_list(self):
        return self._csv(self.sports)

    @property
    def amenity_list(self):
        return self._csv(self.amenities)

    @property
    def is_bookable(self):
        return bool(self.is_active and self.booking_enabled)

    @property
    def accepts_bookings(self):
        return self.is_bookable and not self.bookings_paused

    @property
    def has_peak_pricing(self):
        return self.peak_price_per_slot is not None and bool(self.peak_starts_at or self.weekend_is_peak)

    @property
    def price_from(self):
        if self.has_peak_pricing:
            return min(self.price_per_slot, self.peak_price_per_slot)
        return self.price_per_slot

    @property
    def directions_url(self):
        if self.map_url:
            return self.map_url
        query = quote_plus(f"{self.name} {self.address or self.location_name}")
        return f"https://www.google.com/maps/search/?api=1&query={query}"

    def price_for(self, start_dt):
        """Price of the slot beginning at `start_dt` (peak/weekend aware)."""
        if not self.has_peak_pricing:
            return self.price_per_slot
        local = timezone.localtime(start_dt)
        is_peak = (self.weekend_is_peak and local.weekday() >= 5) or (
            self.peak_starts_at is not None and local.time() >= self.peak_starts_at
        )
        return self.peak_price_per_slot if is_peak else self.price_per_slot

    def clean(self):
        errors = {}
        if self.closes_at and self.opens_at:
            if self.closes_at != time(0, 0) and self.closes_at <= self.opens_at:
                errors['closes_at'] = "Closing time must be after opening time (use 12:00 AM for midnight)."
            else:
                end_min = 24 * 60 if self.closes_at == time(0, 0) else self.closes_at.hour * 60 + self.closes_at.minute
                span = end_min - (self.opens_at.hour * 60 + self.opens_at.minute)
                if self.slot_minutes and span < self.slot_minutes:
                    errors['slot_minutes'] = "A single slot is longer than the opening hours."
        has_peak_rule = bool(self.peak_starts_at or self.weekend_is_peak)
        if self.peak_price_per_slot is not None and not has_peak_rule:
            errors['peak_starts_at'] = "Set when peak pricing starts, or tick \"weekend is peak\"."
        if has_peak_rule and self.peak_price_per_slot is None:
            errors['peak_price_per_slot'] = "Enter the peak price."

        # Don't let the slot grid shift underneath bookings that already exist.
        if self.pk and not errors:
            old = Turf.objects.filter(pk=self.pk).values('slot_minutes', 'opens_at', 'closes_at').first()
            if old and (old['slot_minutes'], old['opens_at'], old['closes_at']) != (
                self.slot_minutes, self.opens_at, self.closes_at
            ):
                if Booking.objects.filter(
                    turf_id=self.pk, status=Booking.Status.CONFIRMED, end_at__gt=timezone.now()
                ).exists():
                    raise ValidationError(
                        "Opening hours and slot length can't change while upcoming bookings or blocks "
                        "exist for this turf. Cancel/clear them first, or change these once they have passed."
                    )
        if errors:
            raise ValidationError(errors)


class Profile(models.Model):
    """Extra, app-specific info attached to every registered user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile'
    )
    phone = models.CharField(max_length=15, unique=True)
    is_available_for_alerts = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.phone})"

    @property
    def display_name(self):
        return self.user.first_name or self.user.username

    def average_rating(self):
        # Only ratings from matches the person actually showed up to count
        # toward their play rating — a no-show carries a fixed 0 that isn't
        # a judgment on how they played, so it's excluded here and reflected
        # in reliability_pct() instead.
        avg = Rating.objects.filter(
            rated_user=self.user, showed_up=True
        ).aggregate(Avg('stars'))['stars__avg']
        return round(avg, 1) if avg is not None else None

    def rating_count(self):
        return Rating.objects.filter(rated_user=self.user, showed_up=True).count()

    def reliability_pct(self):
        """% of rated appearances where the user actually showed up."""
        qs = Rating.objects.filter(rated_user=self.user)
        total = qs.count()
        if not total:
            return None
        showed = qs.filter(showed_up=True).count()
        return round(showed / total * 100)

    def initials(self):
        name = self.display_name.strip()
        parts = [p for p in name.split(' ') if p]
        if not parts:
            return '?'
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class Match(models.Model):
    """A request for players posted by a host, tied to a turf & time."""

    class MatchType(models.TextChoices):
        URGENT = 'URGENT', 'Urgent / Playing Now'
        SCHEDULED = 'SCHEDULED', 'Scheduled / Later'

    class CostModel(models.TextChoices):
        FREE = 'FREE', 'Free / Host Sponsored'
        SPLIT = 'SPLIT', 'Split Cost'

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open for Players'
        FILLED = 'FILLED', 'Slots Filled'
        CANCELLED = 'CANCELLED', 'Cancelled'

    host = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hosted_matches'
    )
    turf = models.ForeignKey(Turf, on_delete=models.CASCADE, related_name='matches')
    match_type = models.CharField(
        max_length=15, choices=MatchType.choices, default=MatchType.URGENT
    )
    cost_model = models.CharField(
        max_length=10, choices=CostModel.choices, default=CostModel.SPLIT
    )
    per_head_amount = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    players_needed = models.PositiveIntegerField(default=1)
    match_time = models.DateTimeField()
    note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    reminder_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['match_time']

    def __str__(self):
        return f"{self.turf.name} — {self.players_needed} needed ({self.status})"

    @property
    def is_urgent(self):
        return self.match_type == self.MatchType.URGENT

    @property
    def cost_display(self):
        if self.cost_model == self.CostModel.FREE:
            return 'Free'
        return f"₹{self.per_head_amount:g}/head"


class JoinRequest(models.Model):
    """A player's request to join a specific match."""

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='requests')
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='join_requests'
    )
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['match', 'player'], name='unique_match_player_request')
        ]

    def __str__(self):
        return f"{self.player.username} -> Match #{self.match_id} ({self.status})"


class Rating(models.Model):
    """Post-match feedback exchanged between host and player."""

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='ratings')
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='given_ratings'
    )
    rated_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_ratings'
    )
    # 0 is only valid when showed_up=False (a no-show can't be given a play
    # rating); 1-5 is only valid when showed_up=True. See clean()/the check
    # constraint below, which both enforce this pairing.
    stars = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    showed_up = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'rater', 'rated_user'], name='unique_match_rating'
            ),
            models.CheckConstraint(
                check=(
                    Q(showed_up=True, stars__gte=1, stars__lte=5)
                    | Q(showed_up=False, stars=0)
                ),
                name='stars_zero_iff_no_show',
            ),
        ]

    def clean(self):
        if self.showed_up and self.stars == 0:
            raise ValidationError("Pick a 1-5 star rating for a player who showed up.")
        if not self.showed_up and self.stars != 0:
            raise ValidationError("A player who didn't show up can't be given a play rating.")

    def save(self, *args, **kwargs):
        # A no-show never carries a play rating, regardless of what a
        # caller passes in — belt-and-braces alongside the check constraint.
        if not self.showed_up:
            self.stars = 0
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if not self.showed_up:
            return f"{self.rater.username} rated {self.rated_user.username}: did not show up"
        return f"{self.rater.username} rated {self.rated_user.username}: {self.stars}★"


class Notification(models.Model):
    """An in-app + push notification delivered to a single user."""

    class Verb(models.TextChoices):
        JOIN_REQUEST = 'JOIN_REQUEST', 'New join request'
        REQUEST_ACCEPTED = 'REQUEST_ACCEPTED', 'Request accepted'
        REQUEST_DECLINED = 'REQUEST_DECLINED', 'Request declined'
        PLAYER_LEFT = 'PLAYER_LEFT', 'Player stepped down'
        MATCH_CANCELLED = 'MATCH_CANCELLED', 'Match cancelled'
        MATCH_FILLED = 'MATCH_FILLED', 'Match filled'
        REMINDER = 'REMINDER', 'Pre-match reminder'
        NEW_MATCH = 'NEW_MATCH', 'New match posted'
        BOOKING_CONFIRMED = 'BOOKING_CONFIRMED', 'Booking confirmed'
        NEW_BOOKING = 'NEW_BOOKING', 'New booking'
        BOOKING_CANCELLED = 'BOOKING_CANCELLED', 'Booking cancelled'
        BOOKING_REMINDER = 'BOOKING_REMINDER', 'Booking reminder'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications'
    )
    verb = models.CharField(max_length=20, choices=Verb.choices)
    message = models.CharField(max_length=255)
    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True
    )
    booking = models.ForeignKey(
        'Booking', on_delete=models.CASCADE, related_name='notifications', null=True, blank=True
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"To {self.recipient.username}: {self.message}"


class PushSubscription(models.Model):
    """A browser's Web Push subscription for a user, used to deliver
    notifications even when SquadTurf isn't open in a tab."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions'
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Push subscription for {self.user.username}"


class SiteSettings(models.Model):
    """A single-row table of site-wide toggles, editable from /admin/."""

    otp_required = models.BooleanField(
        default=True,
        help_text="If off, signup/login skip OTP verification entirely — "
                   "handy for testing multiple accounts quickly.",
    )

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def __str__(self):
        return "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class OTP(models.Model):
    """A short-lived one-time code sent to a phone number for signup or
    login. The code itself is never stored in plain text."""

    class Purpose(models.TextChoices):
        SIGNUP = 'SIGNUP', 'Signup'
        LOGIN = 'LOGIN', 'Login'

    phone = models.CharField(max_length=15, db_index=True)
    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP for {self.phone} ({self.purpose})"


# ---------------------------------------------------------------------------
# Turf slot booking
# ---------------------------------------------------------------------------

class TurfManager(models.Model):
    """Links a *turf admin* account to a turf it runs. Only the site admin can
    create these (in /admin/) — there is no self-serve route to becoming one,
    so a turf only gets a console after it has been onboarded by hand."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='turf_manager_links'
    )
    turf = models.ForeignKey(Turf, on_delete=models.CASCADE, related_name='managers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['turf__name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'turf'], name='unique_turf_manager')
        ]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} manages {self.turf.name}"


_REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L — easy to read out over a call


class Booking(models.Model):
    """One reservation of a contiguous run of slots at a turf. A booking also
    doubles as a *block* (maintenance / closed) or a *walk-in* entered by the
    turf admin, so everything that occupies time lives in a single table."""

    class Status(models.TextChoices):
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class Source(models.TextChoices):
        ONLINE = 'ONLINE', 'Online'
        WALKIN = 'WALKIN', 'Walk-in'
        BLOCKED = 'BLOCKED', 'Blocked'

    class Payment(models.TextChoices):
        PENDING = 'PENDING', 'Pay at turf'
        PAID = 'PAID', 'Paid'

    class CancelledBy(models.TextChoices):
        PLAYER = 'PLAYER', 'Player'
        TURF = 'TURF', 'Turf'

    reference = models.CharField(max_length=12, unique=True, editable=False)
    turf = models.ForeignKey(Turf, on_delete=models.PROTECT, related_name='bookings')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='turf_bookings',
    )
    guest_name = models.CharField(max_length=120, blank=True)
    guest_phone = models.CharField(max_length=15, blank=True)

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.ONLINE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    payment_status = models.CharField(max_length=10, choices=Payment.choices, default=Payment.PENDING)

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    slot_count = models.PositiveSmallIntegerField(default=1)
    amount = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True)

    cancelled_by = models.CharField(max_length=10, choices=CancelledBy.choices, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    reminder_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_at']
        indexes = [
            models.Index(fields=['turf', 'start_at']),
            models.Index(fields=['user', 'start_at']),
        ]

    def __str__(self):
        return f"{self.reference} · {self.turf.name} · {timezone.localtime(self.start_at):%d %b %H:%M}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self.new_reference()
        super().save(*args, **kwargs)

    @classmethod
    def new_reference(cls):
        while True:
            ref = 'ST' + ''.join(secrets.choice(_REF_ALPHABET) for _ in range(6))
            if not cls.objects.filter(reference=ref).exists():
                return ref

    # ---- display helpers ----------------------------------------------
    @property
    def is_blocked(self):
        return self.source == self.Source.BLOCKED

    @property
    def customer_name(self):
        if self.source == self.Source.ONLINE and self.user_id:
            return self.user.first_name or self.user.username
        if self.guest_name:
            return self.guest_name
        return 'Blocked' if self.is_blocked else ('Player' if self.source == self.Source.ONLINE else 'Walk-in')

    @property
    def customer_phone(self):
        if self.source == self.Source.ONLINE and self.user_id:
            profile = getattr(self.user, 'profile', None)
            return profile.phone if profile else ''
        return self.guest_phone

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELLED

    @property
    def has_ended(self):
        return self.end_at <= timezone.now()

    @property
    def is_upcoming(self):
        return self.status == self.Status.CONFIRMED and self.end_at > timezone.now()

    @property
    def in_progress(self):
        now = timezone.now()
        return self.status == self.Status.CONFIRMED and self.start_at <= now < self.end_at

    @property
    def cancel_deadline(self):
        return self.start_at - timedelta(hours=self.turf.cancel_before_hours)

    @property
    def player_can_cancel(self):
        return (
            self.status == self.Status.CONFIRMED
            and self.source == self.Source.ONLINE
            and timezone.now() < self.cancel_deadline
        )

    @property
    def duration_minutes(self):
        return int((self.end_at - self.start_at).total_seconds() // 60)


class BookingSlot(models.Model):
    """One row per slot a confirmed booking occupies. The unique constraint is
    the hard guarantee that two people can never hold the same slot — even if
    two requests race each other. Rows are deleted when a booking is cancelled,
    which is what frees the slot again."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='slots')
    turf = models.ForeignKey(Turf, on_delete=models.CASCADE, related_name='booked_slots')
    start_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['turf', 'start_at'], name='unique_turf_slot'),
        ]

    def __str__(self):
        return f"{self.turf.name} @ {timezone.localtime(self.start_at):%d %b %H:%M}"
