import os
import requests

def post_to_telegram_channel(channel, message, parse_mode=None):
    """
    Post a message to a Telegram channel using the Telegram Bot API.
    Args:
        channel (str): The Telegram channel name (without @) or chat ID.
        message (str): The message to send.
        parse_mode (str, optional): Telegram parse mode (e.g., 'Markdown').
    Returns:
        response: The response object from requests.post
    """
    if not channel or not message:
        return None
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": channel, "text": message}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return response
    except Exception as e:
        # Optionally log the error
        return None 