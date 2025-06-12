from django.db import models
from django.contrib.auth.models import User

class Group(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

class Event(models.Model):
    title = models.CharField(max_length=200)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    description = models.TextField(blank=True)
    organizer = models.ForeignKey(User, on_delete=models.CASCADE)
    def __str__(self):
        return self.title

class RSVP(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='rsvps')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rsvps', null=True, blank=True)
    name = models.CharField(max_length=100, null=True, blank=True)  # Keep for backward compatibility
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('attending', 'Attending'),
        ('maybe', 'Maybe'),
        ('not_attending', 'Not Attending')
    ], null=True, blank=True)

    class Meta:
        unique_together = ['event', 'user']
        ordering = ['-timestamp']

    def __str__(self):
        if self.user:
            return f"{self.user.username} - {self.event.title}"
        return f"{self.name} - {self.event.title}"

    def remove(self):
        self.delete()
