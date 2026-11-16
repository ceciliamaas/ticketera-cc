from django.db import migrations, models

MP_FIELDS = [
    ('mp_access_token', models.CharField(blank=True, help_text='Seller access token (obtained via OAuth)', max_length=500)),
    ('mp_marketplace_fee_pct', models.DecimalField(decimal_places=2, default=0, help_text='Marketplace fee percentage (e.g. 5.00 = 5%). Leave at 0 to charge no fee.', max_digits=5)),
    ('mp_nickname', models.CharField(blank=True, help_text='Seller MP alias/nickname (e.g. JUAN.PEREZ)', max_length=200)),
    ('mp_public_key', models.CharField(blank=True, help_text='Seller public key', max_length=500)),
    ('mp_refresh_token', models.CharField(blank=True, help_text='Token to refresh the access token', max_length=500)),
    ('mp_token_expires_at', models.DateTimeField(blank=True, help_text='When the access token expires', null=True)),
    ('mp_user_id', models.CharField(blank=True, help_text='Seller MercadoPago user ID', max_length=100)),
]


def add_missing_columns(apps, schema_editor):
    """Agrega solo las columnas mp_* que falten; nunca toca las existentes (conserva las conexiones)."""
    Organization = apps.get_model('organizations', 'Organization')
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        existing = {
            c.name for c in connection.introspection.get_table_description(cursor, Organization._meta.db_table)
        }
    for name, field in MP_FIELDS:
        if name in existing:
            continue
        field = field.clone()
        field.set_attributes_from_name(name)
        field.model = Organization
        schema_editor.add_field(Organization, field)


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0006_remove_mercadopago'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Estado: 0003 ya definió todos los campos salvo mp_nickname (y 0006 ya no los quita).
            state_operations=[
                migrations.AddField(
                    model_name='organization',
                    name='mp_nickname',
                    field=dict(MP_FIELDS)['mp_nickname'],
                ),
            ],
            database_operations=[
                migrations.RunPython(add_missing_columns, migrations.RunPython.noop),
            ],
        ),
    ]
