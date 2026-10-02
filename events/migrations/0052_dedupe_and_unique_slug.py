from django.db import migrations, models


def dedupe_slugs(apps, schema_editor):
    Event = apps.get_model('events', 'Event')
    seen = set()
    # Deterministic order so re-running (if ever) is stable.
    for event in Event.objects.exclude(slug__isnull=True).exclude(slug='').order_by('id'):
        if event.slug not in seen:
            seen.add(event.slug)
            continue
        # Collision: find a free suffixed slug for this later-created event.
        base_slug = event.slug
        counter = 2
        new_slug = f'{base_slug}-{counter}'
        while new_slug in seen or Event.objects.filter(slug=new_slug).exists():
            counter += 1
            new_slug = f'{base_slug}-{counter}'
        event.slug = new_slug
        event.save(update_fields=['slug'])
        seen.add(new_slug)


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0051_add_apto_menores'),
    ]

    operations = [
        migrations.RunPython(dedupe_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='event',
            name='slug',
            field=models.SlugField(blank=True, help_text='URL-friendly identifier for the event', max_length=100, null=True, unique=True),
        ),
    ]
