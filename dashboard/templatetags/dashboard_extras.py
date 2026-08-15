from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Look up a value in a dict by key (used in the gradebook)."""
    if mapping is None:
        return None
    return mapping.get(key)


@register.filter
def index(seq, i):
    """Index into a list by a numeric key (used to show MCQ option text)."""
    try:
        return seq[int(i)]
    except (TypeError, ValueError, IndexError):
        return None
