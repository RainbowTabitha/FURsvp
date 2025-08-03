from users.models import Notification
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string

def create_notification(user, message, link=None, event_name=None):
    """
    Creates a new notification for the specified user and sends an email.
    """
    # Create the notification
    notification = Notification.objects.create(user=user, message=message, link=link, event_name=event_name)
    
    # Send email notification if email settings are configured and user has email notifications enabled
    if hasattr(settings, 'EMAIL_HOST') and settings.EMAIL_HOST and user.profile.email_notifications:
        try:
            # Prepare email content
            subject = f"FURsvp Notification: {message[:50]}..."
            if event_name:
                subject = f"FURsvp Event Update: {event_name}"
            
            # Create email body
            email_body = f"""
Hello {user.get_full_name() or user.username},

{message}

"""
            if link:
                email_body += f"View details: {link}\n\n"
            
            email_body += """
Best regards,
The FURsvp Team

---
You can manage your notification preferences in your account settings.
"""
            
            # Send the email
            send_mail(
                subject=subject,
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,  # Don't fail if email sending fails
            )
        except Exception as e:
            # Email sending failed, but we don't want to log this as an error
            # since fail_silently=True means this is expected behavior
            pass
    
    return notification

def approve_all_logged_in_users():
    from users.models import Profile
    users = User.objects.exclude(last_login=None)
    for user in users:
        if hasattr(user, 'profile') and not user.profile.is_verified:
            user.profile.is_verified = True
            user.profile.save()