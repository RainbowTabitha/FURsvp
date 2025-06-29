from django.core.cache import cache
from django.conf import settings

def banner_settings(request):
    """Context processor to make banner settings available in all templates"""
    try:
        # Get banner settings from cache instead of session
        banner_enabled = cache.get('banner_enabled', False)
        banner_text = cache.get('banner_text', '')
        banner_type = cache.get('banner_type', 'info')
        
        # Validate banner type
        valid_types = ['info', 'warning', 'success', 'danger']
        if banner_type not in valid_types:
            banner_type = 'info'
        
        # Add Telegram settings
        telegram_login_enabled = getattr(settings, 'TELEGRAM_LOGIN_ENABLED', False)
        telegram_bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', '')
        
        return {
            'banner_enabled': bool(banner_enabled),
            'banner_text': str(banner_text),
            'banner_type': str(banner_type),
            'telegram_login_enabled': telegram_login_enabled,
            'telegram_bot_username': telegram_bot_username,
        }
    except Exception:
        # Return default values if there's any error
        return {
            'banner_enabled': False,
            'banner_text': '',
            'banner_type': 'info',
            'telegram_login_enabled': False,
            'telegram_bot_username': '',
        } 