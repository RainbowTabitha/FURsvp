from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Template filter to get an item from a dictionary by key."""
    return dictionary.get(key, []) 

@register.simple_tag
def make_date_key(year, month, day):
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}" 