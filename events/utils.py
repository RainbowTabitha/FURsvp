import os
import requests

def post_to_telegram_channel(channel, message):
    """
    Post a message to a Telegram channel using the Telegram Bot API.
    Args:
        channel (str): The Telegram channel name (without @).
        message (str): The message to send.
    Returns:
        response: The response object from requests.post
    """
    if not channel or not message:
        return None
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": channel, "text": message}
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return response
    except Exception as e:
        # Optionally log the error
        return None 