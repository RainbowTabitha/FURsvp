from django import template
from django.utils.safestring import mark_safe
import re
import base64
import requests
from urllib.parse import urlparse

register = template.Library()

@register.filter
def process_description_images(html_content):
    """
    Process HTML content and convert image URLs to base64 format.
    This ensures images are embedded directly in the HTML.
    """
    if not html_content:
        return ""
    
    # Pattern to find img tags with src attributes
    img_pattern = r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>'
    
    def convert_image_to_base64(match):
        img_tag = match.group(0)
        src_url = match.group(1)
        
        # Skip if already base64
        if src_url.startswith('data:image'):
            return img_tag
        
        # Skip if it's a relative URL or local file
        parsed_url = urlparse(src_url)
        if not parsed_url.scheme or parsed_url.scheme in ['file', 'data']:
            return img_tag
        
        try:
            # Fetch the image
            response = requests.get(src_url, timeout=10)
            if response.status_code == 200:
                # Get content type
                content_type = response.headers.get('content-type', 'image/jpeg')
                if not content_type.startswith('image/'):
                    content_type = 'image/jpeg'
                
                # Convert to base64
                image_data = base64.b64encode(response.content).decode('utf-8')
                base64_url = f"data:{content_type};base64,{image_data}"
                
                # Replace the src attribute
                new_img_tag = re.sub(r'src=["\'][^"\']+["\']', f'src="{base64_url}"', img_tag)
                return new_img_tag
            else:
                return img_tag
        except Exception as e:
            # If conversion fails, return original
            print(f"Failed to convert image {src_url} to base64: {e}")
            return img_tag
    
    # Process all images in the HTML
    processed_html = re.sub(img_pattern, convert_image_to_base64, html_content)
    
    return mark_safe(processed_html) 