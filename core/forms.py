import re

from django import forms

from .models import Match, Turf

PHONE_RE = re.compile(r'^[6-9]\d{9}$')

INPUT_CLASSES = (
    'w-full rounded-xl border border-ink-900/15 px-3.5 py-2.5 text-sm text-ink-900 '
    'placeholder:text-ink-500/60 focus:border-pitch-600 focus:ring-2 focus:ring-pitch-600/20 '
    'transition-shadow bg-white'
)


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


class MatchForm(forms.ModelForm):
    EMERGENCY_OFFSET_CHOICES = [
        (15, 'In 15 minutes'),
        (30, 'In 30 minutes'),
        (60, 'In 1 hour'),
    ]

    emergency_time_offset = forms.ChoiceField(
        choices=EMERGENCY_OFFSET_CHOICES, required=False, initial=15,
        widget=forms.Select(attrs={'class': INPUT_CLASSES}),
    )
    match_time_scheduled = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': INPUT_CLASSES}),
    )

    class Meta:
        model = Match
        fields = [
            'turf', 'match_type', 'cost_model', 'players_needed',
            'per_head_amount', 'note',
        ]
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
