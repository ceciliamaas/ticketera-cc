from django.db.models.signals import post_save
from django.dispatch import receiver

from caja.stock import ensure_stock_row, get_or_create_product_for_ticket_type
from tickets.models import TicketType


@receiver(post_save, sender=TicketType)
def ensure_event_product_for_ticket_type(sender, instance, created, **kwargs):
    product = get_or_create_product_for_ticket_type(instance, initial_quantity=instance.ticket_count)
    ensure_stock_row(product)

    # For non-recurring events, keep occurrence_date in sync with event.start
    if created and instance.event and not instance.event.is_recurring and instance.event.start:
        if instance.occurrence_date != instance.event.start:
            TicketType.objects.filter(pk=instance.pk).update(occurrence_date=instance.event.start)
