from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg


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

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.location_name})"


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
        avg = Rating.objects.filter(rated_user=self.user).aggregate(Avg('stars'))['stars__avg']
        return round(avg, 1) if avg is not None else None

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
    stars = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    showed_up = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'rater', 'rated_user'], name='unique_match_rating'
            )
        ]

    def __str__(self):
        return f"{self.rater.username} rated {self.rated_user.username}: {self.stars}★"
