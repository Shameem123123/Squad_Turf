import re
from datetime import datetime

from django import forms

from .models import Match, Turf

PHONE_RE = re.compile(r'^[6-9]\d{9}$')

INPUT_CLASSES = (
    'w-full rounded-xl border border-ink-900/15 px-3.5 py-2.5 text-sm text-ink-900 '
    'placeholder:text-ink-500/60 focus:border-pitch-600 focus:ring-2 focus:ring-pitch-600/20 '
    'transition-shadow bg-white'
)


def _half_hour_slots():
    """('06:00', '6:00 AM'), ('06:30', '6:30 AM'), ... across a full day."""
    slots = []
    for hour in range(24):
        for minute in (0, 30):
            value = f"{hour:02d}:{minute:02d}"
            label = datetime(2000, 1, 1, hour, minute).strftime('%I:%M %p').lstrip('0')
            slots.append((value, label))
    return slots


TIME_SLOT_CHOICES = _half_hour_slots()


def next_half_hour_slot(from_dt):
    """The next :00/:30 slot value at or after `from_dt` (local time), e.g.
    14:07 -> '14:30'. Used as a sensible default kickoff time."""
    minute = 30 if from_dt.minute < 30 else 0
    hour = from_dt.hour if from_dt.minute < 30 else (from_dt.hour + 1) % 24
    return f"{hour:02d}:{minute:02d}"


class SignupForm(forms.Form):
    name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. John Doe', 'autofocus': True, 'class': INPUT_CLASSES}),
    )
    phone = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. 9876543210', 'inputmode': 'numeric', 'class': INPUT_CLASSES}),
    )

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError("Please enter your name.")
        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number.")
        return phone


class LoginForm(forms.Form):
    phone = forms.CharField(
        max_length=15,
        widget=forms.TextInput(
            attrs={'placeholder': 'e.g. 9876543210', 'inputmode': 'numeric', 'autofocus': True, 'class': INPUT_CLASSES}
        ),
    )

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError("Enter a valid 10-digit mobile number.")
        return phone


class OtpForm(forms.Form):
    code = forms.CharField(
        max_length=6, min_length=6,
        widget=forms.TextInput(attrs={
            'placeholder': '••••••', 'inputmode': 'numeric', 'autocomplete': 'one-time-code',
            'autofocus': True, 'class': INPUT_CLASSES + ' text-center tracking-[0.5em] font-mono text-lg',
        }),
    )

    def clean_code(self):
        code = self.cleaned_data['code'].strip()
        if not code.isdigit():
            raise forms.ValidationError("Enter the 6-digit code.")
        return code


class MatchForm(forms.ModelForm):
    DATE_CHOICES = [
        ('TODAY', 'Today'),
        ('TOMORROW', 'Tomorrow'),
    ]

    match_date_choice = forms.ChoiceField(
        choices=DATE_CHOICES, required=False, initial='TODAY',
        label='Which day',
        widget=forms.RadioSelect(attrs={'class': 'peer sr-only'}),
    )
    match_time_slot = forms.ChoiceField(
        choices=TIME_SLOT_CHOICES, required=False,
        label='Kickoff time',
        widget=forms.Select(attrs={'class': INPUT_CLASSES}),
    )

    class Meta:
        model = Match
        fields = [
            'turf', 'match_type', 'cost_model', 'players_needed',
            'per_head_amount', 'note',
        ]
        labels = {
            'turf': 'Ground',
            'match_type': 'When',
            'cost_model': 'Who pays',
            'players_needed': 'Players still needed',
            'per_head_amount': 'Amount per player (₹)',
            'note': 'Note for players',
        }
        widgets = {
            'turf': forms.Select(attrs={'class': INPUT_CLASSES}),
            'match_type': forms.Select(attrs={'class': INPUT_CLASSES, 'id': 'id_match_type'}),
            'cost_model': forms.Select(attrs={'class': INPUT_CLASSES, 'id': 'id_cost_model'}),
            'note': forms.TextInput(
                attrs={'placeholder': 'e.g. Bring extra shoes, 7-a-side match', 'class': INPUT_CLASSES}
            ),
            'players_needed': forms.NumberInput(attrs={'min': 1, 'max': 22, 'class': INPUT_CLASSES}),
            'per_head_amount': forms.NumberInput(
                attrs={'min': 0, 'step': '0.01', 'placeholder': 'e.g. 100', 'class': INPUT_CLASSES}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['turf'].queryset = Turf.objects.filter(is_active=True)
        self.fields['turf'].empty_label = None
        if not self.initial.get('match_time_slot'):
            from django.utils import timezone as _tz
            self.fields['match_time_slot'].initial = next_half_hour_slot(_tz.localtime(_tz.now()))


class ProfileEditForm(forms.Form):
    name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': INPUT_CLASSES}),
    )
    is_available_for_alerts = forms.BooleanField(
        required=False,
        label='Notify me about new matches and requests',
    )
