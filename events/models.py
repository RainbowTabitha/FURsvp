from django.db import models
from django.contrib.auth.models import User
from datetime import time
from django.core.exceptions import ValidationError
from django.urls import reverse

class Group(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

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
