from django import forms

from .models import Turf


class TurfSettingsForm(forms.ModelForm):
    """What a turf admin may edit themselves. Opening hours, slot length and
    the master booking switch stay with the site admin."""

    class Meta:
        model = Turf
        fields = [
            'description', 'amenities', 'cover_image_url', 'contact_phone',
            'price_per_slot', 'peak_price_per_slot', 'peak_starts_at', 'weekend_is_peak',
            'bookings_paused',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Tell players what makes this turf great'}),
            'amenities': forms.TextInput(attrs={'placeholder': 'Floodlights, Parking, Washroom'}),
            'cover_image_url': forms.URLInput(attrs={'placeholder': 'https://…'}),
            'contact_phone': forms.TextInput(attrs={'inputmode': 'tel'}),
            'price_per_slot': forms.NumberInput(attrs={'inputmode': 'decimal', 'min': 0, 'step': '1'}),
            'peak_price_per_slot': forms.NumberInput(attrs={'inputmode': 'decimal', 'min': 0, 'step': '1'}),
            'peak_starts_at': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        }
        labels = {
            'price_per_slot': 'Standard price per slot (₹)',
            'peak_price_per_slot': 'Peak price per slot (₹)',
            'peak_starts_at': 'Peak starts at',
            'weekend_is_peak': 'Saturday & Sunday are peak all day',
            'bookings_paused': 'Pause online bookings',
            'cover_image_url': 'Cover photo link',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'bk-input'
        self.fields['peak_starts_at'].input_formats = ['%H:%M', '%H:%M:%S']
