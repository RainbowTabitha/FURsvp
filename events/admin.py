from .models import Group, Event, RSVP
from django.contrib import admin

# Register your models here.
admin.site.register(Group)
admin.site.register(Event)
admin.site.register(RSVP)
