from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    # Jeśli słownik jest pusty (None), zwróć None i nie rób nic więcej
    if dictionary is None:
        return None
    # Spróbuj pobrać wartość; jeśli to nie jest słownik, też zwróć None
    try:
        return dictionary.get(key)
    except AttributeError:
        return None