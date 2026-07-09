from django.contrib import admin
from django.contrib.auth.models import User

# User is managed under "Organizaciones y Usuarios" via UserProxy in organizations/admin.py
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

