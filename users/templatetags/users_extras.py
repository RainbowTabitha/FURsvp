from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def get_avatar_sized_html(profile, size):
    return profile.get_avatar_html(size=size) 