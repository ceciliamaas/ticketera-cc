from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from user_profile.views import my_ticket_view, profile_view, delete_account_view

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url='/static/img/favicon.png', permanent=True)),
    path('admin/', admin.site.urls),
    path('mi-cuenta/', include('allauth.urls')),
    path('mi-cuenta/', include('caja.urls')),
    path('mi-cuenta/', include('user_profile.urls')),
    path('ckeditor5/', include('django_ckeditor_5.urls')),
    path('room_booking/', include('room_booking.urls')),
    path('dashboard/', include('organizations.urls')),

    # Named public-facing URLs — must come BEFORE the catch-all event slug pattern
    path('mis-entradas/proximos-eventos/', my_ticket_view, name='my_ticket'),
    path('mis-entradas/eventos-anteriores/', my_ticket_view, {'event_slug': 'eventos-anteriores'}, name='my_ticket_past'),
    path('mi-perfil/', profile_view, name='profile'),
    path('mi-perfil/eliminar/', delete_account_view, name='delete_account'),

    path('', include('tickets.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
