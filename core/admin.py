from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from .forms import PHONE_RE
from .models import (
    Booking, JoinRequest, Match, Notification, OTP, Profile, PushSubscription,
    Rating, SiteSettings, Turf, TurfManager,
)


@admin.register(Turf)
class TurfAdmin(admin.ModelAdmin):
    list_display = ('name', 'location_name', 'slug', 'is_active', 'booking_status', 'price_per_slot',
                    'turf_admin_count', 'created_at')
    list_filter = ('is_active', 'booking_enabled')
    search_fields = ('name', 'location_name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('turf_admins_panel',)
    actions = ['enable_booking', 'disable_booking']
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'location_name', 'is_active')}),
        ('Listing details', {
            'description': 'What players see on the booking page.',
            'fields': ('description', 'address', 'map_url', 'cover_image_url', 'sports', 'amenities',
                       'pitch_info', 'contact_phone'),
        }),
        ('Booking setup', {
            'description': '1) Fill in the details  2) Create the turf admin account below / under '
                           '"Turf admin accounts"  3) Tick "Booking enabled" to go live.',
            'fields': ('booking_enabled', 'bookings_paused', 'opens_at', 'closes_at', 'slot_minutes',
                       'max_slots_per_booking', 'advance_days', 'cancel_before_hours'),
        }),
        ('Pricing (per slot)', {
            'fields': ('price_per_slot', 'peak_price_per_slot', 'peak_starts_at', 'weekend_is_peak'),
        }),
        ('Turf admin accounts', {'fields': ('turf_admins_panel',)}),
    )

    @admin.display(description='Booking', ordering='booking_enabled')
    def booking_status(self, obj):
        if not obj.booking_enabled:
            return '— off'
        return 'Paused' if obj.bookings_paused else 'Live'

    @admin.display(description='Turf admins')
    def turf_admin_count(self, obj):
        return obj.managers.count()

    @admin.display(description='Accounts')
    def turf_admins_panel(self, obj):
        if not obj.pk:
            return 'Save the turf first, then create its turf admin account.'
        add = reverse('admin:core_turfmanager_add') + f'?turf={obj.pk}'
        rows = format_html_join(
            '', '<li>{} · {}</li>',
            ((m.user.first_name or m.user.username, getattr(getattr(m.user, 'profile', None), 'phone', ''))
             for m in obj.managers.select_related('user', 'user__profile')),
        )
        console = ''
        if obj.booking_enabled:
            console = format_html(' &nbsp;·&nbsp; <a href="{}">Open console</a>', reverse('manage_schedule', args=[obj.slug]))
        return format_html('<ul style="margin:0 0 8px 16px">{}</ul><a class="button" href="{}">+ Create turf admin account</a>{}',
                           rows or format_html('<li>None yet</li>'), add, console)

    @admin.action(description='Switch online booking ON for selected turfs')
    def enable_booking(self, request, queryset):
        n = queryset.update(booking_enabled=True)
        self.message_user(request, f'Booking enabled for {n} turf(s).')

    @admin.action(description='Switch online booking OFF for selected turfs')
    def disable_booking(self, request, queryset):
        n = queryset.update(booking_enabled=False)
        self.message_user(request, f'Booking disabled for {n} turf(s). Existing bookings are kept.')


class TurfManagerCreateForm(forms.ModelForm):
    """Creates the turf admin's login in one step: name + phone + password."""
    name = forms.CharField(max_length=60, required=False, label='Contact name',
                           help_text='The person at the turf. Not needed if the phone already belongs to an existing turf admin.')
    phone = forms.CharField(max_length=15, label='Login phone number')
    password = forms.CharField(widget=forms.PasswordInput(render_value=False), required=False, min_length=8,
                               help_text='Share this with the turf yourself. They can change it from their console.')

    class Meta:
        model = TurfManager
        fields = ('turf',)

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError('Enter a valid phone number.')
        return phone

    def clean(self):
        data = super().clean()
        phone, turf = data.get('phone'), data.get('turf')
        if not phone or not turf:
            return data
        profile = Profile.objects.select_related('user').filter(phone=phone).first()
        if profile:
            if not TurfManager.objects.filter(user=profile.user).exists():
                raise forms.ValidationError(
                    'That number belongs to a regular player account. A turf admin must be a separate '
                    'account — use a different number.')
            if TurfManager.objects.filter(user=profile.user, turf=turf).exists():
                raise forms.ValidationError('That turf admin already manages this turf.')
            self.existing_user = profile.user
        else:
            if not data.get('name'):
                self.add_error('name', 'Required for a new account.')
            if not data.get('password'):
                self.add_error('password', 'Required for a new account (min 8 characters).')
        return data


@admin.register(TurfManager)
class TurfManagerAdmin(admin.ModelAdmin):
    list_display = ('turf', 'admin_name', 'admin_phone', 'created_at')
    list_filter = ('turf',)
    search_fields = ('turf__name', 'user__first_name', 'user__profile__phone')
    list_select_related = ('turf', 'user', 'user__profile')

    @admin.display(description='Turf admin')
    def admin_name(self, obj):
        return obj.user.first_name or obj.user.username

    @admin.display(description='Phone')
    def admin_phone(self, obj):
        return getattr(getattr(obj.user, 'profile', None), 'phone', '')

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = TurfManagerCreateForm
            kwargs.pop('fields', None)
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        return ('turf', 'name', 'phone', 'password') if obj is None else ('turf', 'user')

    def get_readonly_fields(self, request, obj=None):
        return ('user',) if obj else ()

    def get_changeform_initial_data(self, request):
        return {'turf': request.GET.get('turf')}

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        User = get_user_model()
        user = getattr(form, 'existing_user', None)
        if user is None:
            name, base, n = form.cleaned_data['name'].strip(), None, 1
            base = ('turf_' + name.lower().replace(' ', '_'))[:140]
            username = base
            while User.objects.filter(username=username).exists():
                username, n = f'{base}_{n}', n + 1
            user = User.objects.create_user(username=username, first_name=name,
                                            password=form.cleaned_data['password'])
            # no match-alert spam for a business account
            Profile.objects.create(user=user, phone=form.cleaned_data['phone'], is_available_for_alerts=False)
            messages.info(request, f'Account created. They log in with {form.cleaned_data["phone"]} and the password you set.')
        obj.user = user
        super().save_model(request, obj, form, change)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('reference', 'turf', 'who', 'start_at', 'slot_count', 'amount', 'source', 'status', 'payment_status')
    list_filter = ('status', 'source', 'payment_status', 'turf')
    search_fields = ('reference', 'guest_name', 'guest_phone', 'user__first_name', 'user__profile__phone')
    date_hierarchy = 'start_at'
    list_select_related = ('turf', 'user')
    actions = ['cancel_selected']
    readonly_fields = [f.name for f in Booking._meta.fields]

    def has_add_permission(self, request):
        return False  # bookings are made through the app so slots/prices stay consistent

    @admin.display(description='Customer')
    def who(self, obj):
        return obj.customer_name

    @admin.action(description='Cancel selected bookings (frees the slots, notifies players)')
    def cancel_selected(self, request, queryset):
        from . import booking_logic as bl
        done = 0
        for b in queryset.filter(status=Booking.Status.CONFIRMED):
            bl.cancel_booking(b, Booking.CancelledBy.TURF, 'Cancelled by SquadTurf')
            if not b.is_blocked:
                bl.notify_booking_cancelled(b, Booking.CancelledBy.TURF, 'Cancelled by SquadTurf')
            done += 1
        self.message_user(request, f'{done} booking(s) cancelled.')


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
