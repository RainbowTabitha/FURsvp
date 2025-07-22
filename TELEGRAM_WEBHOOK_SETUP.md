# Telegram Webhook Channel Setup

This guide explains how to set up Telegram channel posting for your FURsvp instance.

---

## 1. Telegram Bot Setup

1. Create a Telegram bot using [BotFather](https://t.me/BotFather) if you don't already have one.
2. Copy the bot token provided by BotFather.
3. Add the following to your `.env` file:
   ```
   TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
   ```

---

## 2. Add Bot to Your Channel

1. **Make your channel public** (it must have a username, e.g., `@yourchannel`).
2. **Add your bot as an administrator**:
   - Open your channel settings in Telegram.
   - Go to "Administrators" and add your bot by its username (e.g., `@YourBotName`).
   - The bot must have at least the "Post Messages" permission.

---

## 3. Configure the Channel in FURsvp

- In the group management UI, set the **Telegram Webhook Channel** field to your channel's username (without the `@`).
  - Example: For `t.me/myfurevents`, enter `myfurevents`.

---

## 4. How It Works

- When a new event is created for a group with a Telegram webhook channel, the bot will post an announcement to the channel.
- When someone RSVPs to a public event, the bot will post a message to the channel. If the user has a Telegram username linked in their profile, they will be pinged (e.g., `@username`).

---

## 5. Troubleshooting

- **Bot not posting?**
  - Ensure the bot is an admin in the channel.
  - Ensure the channel is public and the username is correct.
  - Check that your `.env` file has the correct bot token and the server has been restarted after changes.
- **Mentions not working?**
  - The user must have a Telegram username set in their FURsvp profile.

---

## 6. References
- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [How to add a bot to a channel](https://core.telegram.org/bots/faq#how-do-i-add-a-bot-to-a-channel) 