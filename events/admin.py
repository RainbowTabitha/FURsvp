from .models import Group, Event, RSVP, Post
from django.contrib import admin

# Register your models here.
admin.site.register(Group)
admin.site.register(Event)
admin.site.register(RSVP)
admin.site.register(Post)
