from django import template
import re

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Template filter to get an item from a dictionary by key."""
    return dictionary.get(key, []) 

@register.simple_tag
def make_date_key(year, month, day):
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

@register.filter
def urlize(text):
    """Convert plain text URLs to clickable HTML links, but only if the text doesn't contain HTML tags."""
    if not text:
        return text
    
    # Check if the text contains HTML tags - if so, return as-is to preserve TinyMCE formatting
    if re.search(r'<[^>]+>', text):
        return text
    
    # URL pattern that matches http, https, www, and common TLDs
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+|www\.[^\s<>"{}|\\^`\[\]]+'
    
    def replace_url(match):
        url = match.group(0)
        # Add http:// if the URL starts with www
        if url.startswith('www.'):
            url = 'http://' + url
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="text-primary">{match.group(0)}</a>'
    
    return re.sub(url_pattern, replace_url, text) 