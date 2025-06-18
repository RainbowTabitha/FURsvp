from django.db import models
from django.contrib.auth.models import User
from datetime import time
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import strip_tags
import re

class Group(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, help_text="Description of the group and its activities")
    logo_base64 = models.TextField(blank=True, null=True, help_text="Group logo as base64 string")
    website = models.URLField(blank=True, null=True, help_text="Group's website URL")
    contact_email = models.EmailField(blank=True, null=True, help_text="Primary contact email for the group")
    telegram_channel = models.CharField(max_length=100, blank=True, null=True, help_text="Telegram channel username (without @)")
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('group_detail', args=[str(self.id)])
    
    def get_leadership(self):
        """Get all leadership roles for this group, ordered by hierarchy"""
        from users.models import GroupRole
        return GroupRole.objects.filter(group=self, is_active=True).order_by('role_level', 'assigned_at')
    
    def get_role_members(self, role_level):
        """Get all members with a specific role level or higher"""
        from users.models import GroupRole
        # Map role levels to role names
        role_mapping = {
            1: ['founder'],
            2: ['founder', 'admin'],
            3: ['founder', 'admin', 'moderator'],
            4: ['founder', 'admin', 'moderator', 'event_manager'],
            5: ['founder', 'admin', 'moderator', 'event_manager', 'helper'],
        }
        role_names = role_mapping.get(role_level, [])
        return User.objects.filter(group_roles__group=self, group_roles__role_name__in=role_names, group_roles__is_active=True)
    
    def get_role_members_by_name(self, role_name):
        """Get all members with a specific role name"""
        from users.models import GroupRole
        return User.objects.filter(group_roles__group=self, group_roles__role_name__iexact=role_name, group_roles__is_active=True)
    
    def get_top_leadership(self):
        """Get top level leadership (level 1-2)"""
        return self.get_role_members(2)
    
    def get_management(self):
        """Get management level (level 1-3)"""
        return self.get_role_members(3)
    
    def get_event_managers(self):
        """Get users who can manage events (level 1-4)"""
        return self.get_role_members(4)
    
    def user_has_role_level(self, user, max_level):
        """Check if a user has a role at or above a specific level"""
        from users.models import GroupRole
        # Map role levels to role names
        role_mapping = {
            1: ['founder'],
            2: ['founder', 'admin'],
            3: ['founder', 'admin', 'moderator'],
            4: ['founder', 'admin', 'moderator', 'event_manager'],
            5: ['founder', 'admin', 'moderator', 'event_manager', 'helper'],
        }
        role_names = role_mapping.get(max_level, [])
        return GroupRole.objects.filter(user=user, group=self, role_name__in=role_names, is_active=True).exists()
    
    def user_has_role_name(self, user, role_name):
        """Check if a user has a specific role name"""
        from users.models import GroupRole
        return GroupRole.objects.filter(user=user, group=self, role_name__iexact=role_name, is_active=True).exists()
    
    def user_can_manage_events(self, user):
        """Check if a user can manage events in this group"""
        return self.user_has_role_level(user, 4)
    
    def user_can_manage_group(self, user):
        """Check if a user can manage group settings"""
        return self.user_has_role_level(user, 2)
    
    # Legacy methods for backward compatibility
    def get_organizers(self):
        """Legacy method - returns users who can manage events"""
        return self.get_event_managers()
    
    def get_assistants(self):
        """Legacy method - returns all active role members"""
        return User.objects.filter(group_roles__group=self, group_roles__is_active=True)
    
    def get_founders(self):
        """Get all founders of this group"""
        return self.get_role_members(1)
    
    def get_admins(self):
        """Get all administrators of this group"""
        return self.get_role_members(2)
    
    def get_moderators(self):
        """Get all moderators of this group"""
        return self.get_role_members(3)
    
    def get_coordinators(self):
        """Get all event coordinators of this group"""
        return self.get_role_members(4)
    
    def get_helpers(self):
        """Get all helpers of this group"""
        return self.get_role_members(5)
    
    def get_upcoming_events(self):
        """Get upcoming events for this group"""
        from django.utils import timezone
        from datetime import datetime
        now = timezone.now()
        return self.event_set.filter(
            models.Q(date__gt=now.date()) | 
            (models.Q(date=now.date()) & models.Q(end_time__gt=now.time())),
            status='active'
        ).order_by('date', 'start_time')
    
    def get_past_events(self):
        """Get past events for this group"""
        from django.utils import timezone
        from datetime import datetime
        now = timezone.now()
        return self.event_set.filter(
            models.Q(date__lt=now.date()) | 
            (models.Q(date=now.date()) & models.Q(end_time__lt=now.time())),
            status='active'
        ).order_by('-date', '-start_time')

class Event(models.Model):
    title = models.CharField(max_length=200)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True, default=time(0, 0, 0))
    end_time = models.TimeField(null=True, blank=True, default=time(0, 0, 0))
    description = models.TextField(blank=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)
    organizer = models.ForeignKey(User, on_delete=models.CASCADE)
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        help_text="Current status of the event"
    )
    AGE_CHOICES = [
        ('none', 'All ages'),
        ('adult', '18+ (Adult)'),
        ('mature', '21+ (Mature)'),
    ]
    age_restriction = models.CharField(
        max_length=10,
        choices=AGE_CHOICES,
        default='none',
        help_text="Age restriction for the event"
    )
    capacity = models.IntegerField(null=True, blank=True, help_text="Maximum number of attendees. Leave blank for no limit.")
    waitlist_enabled = models.BooleanField(default=False, help_text="Enable a waitlist if capacity is reached.")
    
    def clean(self):
        if self.waitlist_enabled and self.capacity is None:
            raise ValidationError({
                'waitlist_enabled': 'Capacity must be set when waitlist is enabled.',
                'capacity': 'Capacity must be set when waitlist is enabled.'
            })
    
    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('event_detail', args=[str(self.id)])

class RSVP(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='rsvps')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rsvps', null=True, blank=True)
    name = models.CharField(max_length=100, null=True, blank=True)  # Keep for backward compatibility
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('confirmed', 'Confirmed'),
        ('waitlisted', 'Waitlisted'),
        ('maybe', 'Maybe'),
        ('not_attending', 'Not Attending')
    ], default='confirmed', null=True, blank=True)

    class Meta:
        unique_together = ['event', 'user']
        ordering = ['timestamp'] # Order by timestamp for waitlist purposes

    def __str__(self):
        if self.user:
            return f"{self.user.username} - {self.event.title}"
        return f"{self.name} - {self.event.title}"

    def remove(self):
        self.delete()

class Post(models.Model):
    title = models.CharField(max_length=300)
    content = models.TextField()
    published = models.DateTimeField()
    original_link = models.URLField(blank=True, null=True)
    guid = models.CharField(max_length=255, unique=True, blank=True, null=True)

    def __str__(self):
        return self.title

    def get_excerpt(self, length=200):
        # Remove <img> tags
        text = re.sub(r'<img[^>]*>', '', self.content)
        # Strip other HTML tags
        text = strip_tags(text)
        # Truncate
        if len(text) > length:
            return text[:length] + '…'
        return text
