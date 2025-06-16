from users.models import Notification

def create_notification(user, message, link=None):
    """
    Creates a new notification for the specified user.
    """
    Notification.objects.create(user=user, message=message, link=link) 