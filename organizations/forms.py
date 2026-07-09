from django import forms
from events.models import Event


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            'name', 'slug', 'status',
            'location', 'location_url',
            'start', 'is_recurring',
            'max_tickets', 'max_tickets_per_order',
            'header_image', 'description',
        ]
        widgets = {
            'start': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'end': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'description': forms.Textarea(attrs={'rows': 4}),
            'title': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['slug'].help_text = 'Leave blank to auto-generate from name.'
        self.fields['end'].required = False
        for field_name in ('start', 'end'):
            self.fields[field_name].input_formats = ['%Y-%m-%dT%H:%M']
