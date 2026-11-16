# Originalmente esta migración eliminaba los campos mp_* de Organization y la 0007
# los volvía a crear, lo que borraba las conexiones de MercadoPago ya existentes.
# Ahora es un no-op para preservar tokens y datos de conexión.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0005_add_ciudad'),
    ]

    operations = []
