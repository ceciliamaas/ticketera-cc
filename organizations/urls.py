from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_home, name='dashboard_home'),
    path('new/', views.dashboard_org_create, name='dashboard_org_create'),
    # Superuser global views
    path('su/events/', views.dashboard_su_events, name='dashboard_su_events'),
    path('su/members/', views.dashboard_su_members, name='dashboard_su_members'),
    path('su/settings/', views.dashboard_su_settings, name='dashboard_su_settings'),
    path('o/<slug:org_slug>/', views.dashboard_event_list, name='dashboard_event_list'),
    path('o/<slug:org_slug>/events/new/', views.dashboard_event_create, name='dashboard_event_create'),
    path('o/<slug:org_slug>/events/<int:event_id>/edit/', views.dashboard_event_edit, name='dashboard_event_edit'),
    path('o/<slug:org_slug>/events/<int:event_id>/reservas/', views.dashboard_event_reservas, name='dashboard_event_reservas'),
    path('o/<slug:org_slug>/events/<int:event_id>/delete/', views.dashboard_event_delete, name='dashboard_event_delete'),
    path('o/<slug:org_slug>/events/<int:event_id>/ticket-types/<int:tt_id>/delete/', views.dashboard_ticket_type_delete, name='dashboard_ticket_type_delete'),
    path('o/<slug:org_slug>/events/<int:event_id>/cancel/', views.dashboard_event_cancel, name='dashboard_event_cancel'),
    path('o/<slug:org_slug>/events/<int:event_id>/set-status/', views.dashboard_event_set_status, name='dashboard_event_set_status'),
    path('o/<slug:org_slug>/events/<int:event_id>/publish/', views.dashboard_event_publish, name='dashboard_event_publish'),
    path('o/<slug:org_slug>/events/<int:event_id>/unpublish/', views.dashboard_event_unpublish, name='dashboard_event_unpublish'),
    path('o/<slug:org_slug>/members/', views.dashboard_members, name='dashboard_members'),
    path('o/<slug:org_slug>/members/add/', views.dashboard_member_add, name='dashboard_member_add'),
    path('o/<slug:org_slug>/members/<int:membership_id>/remove/', views.dashboard_member_remove, name='dashboard_member_remove'),
    path('o/<slug:org_slug>/invitations/<int:invitation_id>/cancel/', views.dashboard_invitation_cancel, name='dashboard_invitation_cancel'),
    # Organisation settings
    path('o/<slug:org_slug>/settings/', views.dashboard_org_edit, name='dashboard_org_edit'),
    # MercadoPago Marketplace OAuth
    path('o/<slug:org_slug>/mercadopago/', views.dashboard_mp_connect, name='dashboard_mp_connect'),
    path('o/<slug:org_slug>/mercadopago/connect/', views.dashboard_mp_oauth_start, name='dashboard_mp_oauth_start'),
    path('o/<slug:org_slug>/mercadopago/disconnect/', views.dashboard_mp_disconnect, name='dashboard_mp_disconnect'),
    path('mp/callback/', views.dashboard_mp_callback, name='dashboard_mp_callback'),
]
