from django.db.models.signals import post_save, post_delete, post_migrate
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.db import connection
from django.apps import apps
from .models import Event, RSVP, Group, PlatformStats

@receiver(post_save, sender=Event)
def increment_event_stats(sender, instance, created, **kwargs):
    """Increment cumulative event count when a new event is created"""
    if created:
        PlatformStats.increment_events()

@receiver(post_save, sender=RSVP)
def increment_rsvp_stats(sender, instance, created, **kwargs):
    """Increment cumulative RSVP count when a new RSVP is created"""
    if created:
        PlatformStats.increment_rsvps()

@receiver(post_save, sender=User)
def increment_user_stats(sender, instance, created, **kwargs):
    """Increment cumulative user count when a new user is created"""
    if created:
        PlatformStats.increment_users()

@receiver(post_save, sender=Group)
def increment_group_stats(sender, instance, created, **kwargs):
    """Increment cumulative group count when a new group is created"""
    if created:
        PlatformStats.increment_groups()

@receiver(post_delete, sender=User)
def decrement_user_stats(sender, instance, **kwargs):
    """Decrement cumulative user count when a user is deleted"""
    try:
        # Only decrement if we're not in a transaction that might be rolled back
        if not connection.in_atomic_block:
            PlatformStats.decrement_users()
    except Exception as e:
        # Silently fail if there's an issue - don't prevent user deletion
        print(f"Warning: Could not decrement user stats: {e}")
        pass

@receiver(post_delete, sender=Group)
def decrement_group_stats(sender, instance, **kwargs):
    """Decrement cumulative group count when a group is deleted"""
    try:
        # Only decrement if we're not in a transaction that might be rolled back
        if not connection.in_atomic_block:
            PlatformStats.decrement_groups()
    except Exception as e:
        # Silently fail if there's an issue - don't prevent group deletion
        print(f"Warning: Could not decrement group stats: {e}")
        pass


def initialize_platform_stats():
    """Initialize platform stats when the app starts"""
    try:
        # Check if database is ready
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        # Sync platform stats with current data
        PlatformStats.sync_with_current_data()
    except Exception:
        # Database might not be ready yet, this is normal during startup
        pass 