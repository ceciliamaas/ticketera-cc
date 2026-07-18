from django import forms
from django.forms import inlineformset_factory
from events.models import Event
from tickets.models import TicketType
from .models import Organization


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name', 'email', 'photo', 'location', 'address', 'ciudad', 'location_url']
        labels = {
            'name': 'Nombre',
            'email': 'Email',
            'photo': 'Foto',
            'location': 'Lugar',
            'address': 'Dirección',
            'ciudad': 'Ciudad',
            'location_url': 'URL del lugar (ej. Google Maps)',
        }
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
        }


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            'name',
            'location', 'address', 'ciudad', 'location_url',
            'start', 'end',
            'max_tickets', 'max_tickets_per_order',
            'apto_menores',
            'header_image', 'description',
            'is_recurring',
            'status',
        ]
        labels = {
            'name': 'Nombre',
            'slug': 'Slug (URL)',
            'status': 'Estado',
            'location': 'Lugar',
            'address': 'Dirección',
            'ciudad': 'Ciudad',
            'location_url': 'URL del lugar (ej. Google Maps)',
            'start': 'Fecha y hora de inicio',
            'end': 'Fecha y hora de fin',
            'is_recurring': 'Evento recurrente',
            'max_tickets': 'Máximo de tickets totales',
            'max_tickets_per_order': 'Máximo de tickets por orden',
            'header_image': 'Imagen de portada',
            'description': 'Descripción',
        }
        help_texts = {
            'slug': 'Dejá en blanco para generarlo automáticamente desde el nombre.',
            'status': 'Los eventos en borrador no son visibles al público.',
            'end': 'Opcional.',
            'is_recurring': 'Activar si el evento tiene múltiples funciones.',
            'location': 'Lugar donde se realiza el evento.',
            'address': 'Dirección física del lugar.',
            'ciudad': 'Ciudad donde se realiza el evento.',
            'location_url': 'Enlace al lugar (ej. Google Maps)',
            'header_image': 'Tamaño recomendado: 1666 × 500 px. Si no se carga, se usará la imagen de la organización.',
            'max_tickets': 'Límite global de tickets para este evento.',
            'max_tickets_per_order': 'Opcional. Cantidad máxima por orden de compra.',
            'apto_menores': 'Marcar si el evento es apto para menores de 18 años.',
        }
        widgets = {
            'start': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'end': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'description': forms.Textarea(attrs={'rows': 5}),
            'address': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['end'].required = False
        self.fields['max_tickets'].required = False
        self.fields['max_tickets_per_order'].required = False
        self.fields['max_tickets_per_order'].widget.attrs['placeholder'] = ''
        if not kwargs.get('instance'):
            self.initial['max_tickets_per_order'] = ''
        for field_name in ('start', 'end'):
            self.fields[field_name].input_formats = ['%Y-%m-%dT%H:%M']
        # Translate status choices
        self.fields['status'].choices = [
            ('draft', 'Borrador'),
            ('published', 'Publicado'),
        ]


class TicketTypeForm(forms.ModelForm):
    class Meta:
        model = TicketType
        fields = ['name', 'description', 'price', 'ticket_count', 'date_from', 'date_to', 'occurrence_date', 'occurrence_end']
        labels = {
            'name': 'Nombre',
            'description': 'Descripción',
            'price': 'Precio ($)',
            'ticket_count': 'Entradas disponibles',
            'date_from': 'Venta desde',
            'date_to': 'Venta hasta',
            'occurrence_date': 'Fecha de inicio de la función',
            'occurrence_end': 'Fecha de fin de la función',
        }
        help_texts = {
            'date_from': 'Opcional. Fecha desde la que se puede comprar.',
            'date_to': 'Opcional. Fecha hasta la que se puede comprar.',
            'ticket_count': 'Cantidad de entradas disponibles para este tipo. Dejá vacío para sin límite.',
            'occurrence_end': 'Opcional.',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'date_from': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'date_to': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'occurrence_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'occurrence_end': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['price'].required = False
        self.fields['ticket_count'].required = False
        self.fields['date_from'].required = False
        self.fields['date_to'].required = False
        self.fields['occurrence_date'].required = False
        self.fields['occurrence_end'].required = False
        for field_name in ('date_from', 'date_to', 'occurrence_date', 'occurrence_end'):
            self.fields[field_name].input_formats = ['%Y-%m-%dT%H:%M']


TicketTypeFormSet = inlineformset_factory(
    Event, TicketType,
    form=TicketTypeForm,
    extra=1,
    can_delete=True,
)
