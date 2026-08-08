from django.contrib import admin

from .models import (
    JoinRequest, Match, Notification, OTP, Profile, PushSubscription,
    Rating, SiteSettings, Turf,
)


@admin.register(Turf)
class TurfAdmin(admin.ModelAdmin):
    list_display = ('name', 'location_name', 'slug', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'location_name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'is_available_for_alerts', 'created_at')
    search_fields = ('user__username', 'user__first_name', 'phone')


class JoinRequestInline(admin.TabularInline):
    model = JoinRequest
    extra = 0
    readonly_fields = ('player', 'status', 'created_at')
    can_delete = False


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        'turf', 'host', 'match_type', 'cost_model', 'players_needed',
        'match_time', 'status', 'reminder_sent', 'created_at',
    )
    list_filter = ('match_type', 'cost_model', 'status', 'reminder_sent')
    search_fields = ('turf__name', 'host__username', 'host__first_name')
    inlines = [JoinRequestInline]


@admin.register(JoinRequest)
class JoinRequestAdmin(admin.ModelAdmin):
    list_display = ('match', 'player', 'status', 'created_at')
    list_filter = ('status',)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('match', 'rater', 'rated_user', 'stars', 'showed_up', 'created_at')
    list_filter = ('stars', 'showed_up')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'verb', 'message', 'is_read', 'created_at')
    list_filter = ('verb', 'is_read')
    search_fields = ('recipient__username', 'message')


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'endpoint', 'user_agent', 'created_at')
    search_fields = ('user__username',)


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ('phone', 'purpose', 'is_used', 'attempts', 'expires_at', 'created_at')
    list_filter = ('purpose', 'is_used')
    search_fields = ('phone',)
    readonly_fields = ('code_hash',)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('otp_required',)

    def has_add_permission(self, request):
        # singleton — only ever one row, created lazily by SiteSettings.load()
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
