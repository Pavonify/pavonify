from django import template

register = template.Library()

@register.filter
def dictlookup(dictionary, key):
    """Retrieve value from dictionary by key in Django templates."""
    return dictionary.get(key, 0)


@register.filter
def get_attr(obj, attr_name):
    """Get attribute of an object by name in templates."""
    return getattr(obj, attr_name, 0)
