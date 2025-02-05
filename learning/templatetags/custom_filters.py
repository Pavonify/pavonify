from django import template

register = template.Library()

@register.filter
def dictlookup(dictionary, key):
    """Retrieve value from dictionary by key in Django templates."""
    return dictionary.get(key, 0)
