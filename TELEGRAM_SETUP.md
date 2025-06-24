# Telegram Authentication Setup Guide

This guide will help you set up Telegram authentication for your FURsvp application.

## Prerequisites

1. A Telegram account
2. Access to @BotFather on Telegram

## Step 1: Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Start a conversation with BotFather
3. Send the command `/newbot`
4. Follow the prompts:
   - Enter a display name for your bot (e.g., "FURsvp Bot")
   - Enter a username for your bot (must end with 'bot', e.g., "fursvp_bot")
5. BotFather will provide you with:
   - A bot token (keep this secret!)
   - A bot username

## Step 2: Configure Environment Variables

1. Create a `.env` file in your project root (if it doesn't exist)
2. Add the following variables:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_BOT_USERNAME=your_bot_username_here
```

**Important:** Never commit your `.env` file to version control!

## Step 3: Install Dependencies

Run the following command to install the required packages:

```bash
pip install -r requirements.txt
```

## Step 4: Run Database Migrations

```bash
python manage.py makemigrations users
python manage.py migrate
```

## Step 5: Test the Setup

1. Start your Django development server:
   ```bash
   python manage.py runserver
   ```

2. Visit your login page and you should see a "Login with Telegram" option

3. Test the Telegram login functionality

## Features

### Login with Telegram
- Users can log in using their Telegram account
- New users are automatically created when they first log in with Telegram
- Existing users can link their Telegram account to their existing profile

### Account Linking
- Users can link their existing FURsvp account to their Telegram account
- Users can unlink their Telegram account from their profile
- Prevents multiple users from linking the same Telegram account

### Security
- All Telegram authentication data is cryptographically verified
- Bot tokens are stored securely using environment variables
- Authentication data has a 24-hour expiration

## Troubleshooting

### Common Issues

1. **"Invalid bot token" error**
   - Make sure your bot token is correct
   - Check that the environment variable is properly set

2. **"Bot not found" error**
   - Verify your bot username is correct
   - Make sure your bot is active

3. **Authentication fails**
   - Check that your bot token and username match
   - Ensure the bot is not blocked by users

### Security Notes

- Keep your bot token secret and never share it publicly
- Use environment variables for all sensitive configuration
- Regularly rotate your bot token if needed
- Monitor your bot's usage for any suspicious activity

## Production Deployment

For production deployment:

1. Set `DEBUG=False` in your environment variables
2. Use a strong, unique `SECRET_KEY`
3. Configure your web server to handle HTTPS (required for Telegram widgets)
4. Set up proper logging and monitoring
5. Consider using a process manager like systemd or supervisor

## Support

If you encounter issues:

1. Check the Django logs for error messages
2. Verify your bot configuration with @BotFather
3. Test with a simple Telegram bot first
4. Ensure your domain is accessible and uses HTTPS

## Additional Resources

- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [Telegram Login Widget Documentation](https://core.telegram.org/widgets/login)
- [Django Authentication Documentation](https://docs.djangoproject.com/en/stable/topics/auth/) 