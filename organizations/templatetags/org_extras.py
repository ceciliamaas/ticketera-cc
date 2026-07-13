from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Return dictionary[key] or None."""
    if dictionary is None:
        return None
    return dictionary.get(key)
