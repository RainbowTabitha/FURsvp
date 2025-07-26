import os
import requests
import subprocess

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

def get_git_version():
    """
    Get the current git version information.
    Returns:
        dict: Dictionary containing git version information or None if error
    """
    try:
        # Get the git repository root directory
        git_root = subprocess.check_output(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=os.getcwd(),
            stderr=subprocess.PIPE,
            universal_newlines=True
        ).strip()
        
        # Get the current commit hash
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=git_root,
            stderr=subprocess.PIPE,
            universal_newlines=True
        ).strip()
        
        # Get the current branch name
        branch_name = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=git_root,
            stderr=subprocess.PIPE,
            universal_newlines=True
        ).strip()
        
        # Get the latest tag if available
        try:
            latest_tag = subprocess.check_output(
                ['git', 'describe', '--tags', '--abbrev=0'],
                cwd=git_root,
                stderr=subprocess.PIPE,
                universal_newlines=True
            ).strip()
        except subprocess.CalledProcessError:
            latest_tag = None
        
        # Check if there are uncommitted changes
        try:
            subprocess.check_output(
                ['git', 'diff-index', '--quiet', 'HEAD', '--'],
                cwd=git_root,
                stderr=subprocess.PIPE
            )
            has_uncommitted = False
        except subprocess.CalledProcessError:
            has_uncommitted = True
        
        return {
            'commit_hash': commit_hash,
            'branch_name': branch_name,
            'latest_tag': latest_tag,
            'has_uncommitted': has_uncommitted
        }
        
    except (subprocess.CalledProcessError, FileNotFoundError, Exception):
        # Return None if git is not available or there's an error
        return None 