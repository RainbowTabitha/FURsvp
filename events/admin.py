from .models import Group, Event, RSVP, Post
from django.contrib import admin
from users.models import GroupRole
from django.db import transaction

class GroupRoleInline(admin.TabularInline):
    model = GroupRole
    extra = 1

class RSVPInline(admin.TabularInline):
    model = RSVP
    extra = 0
    readonly_fields = ('user', 'event', 'timestamp')
    can_delete = False

class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'date', 'start_time', 'end_time', 'group', 'organizer', 'status')
    list_filter = ('status', 'date', 'group')
    search_fields = ('title', 'description', 'group__name', 'organizer__username')
    inlines = [RSVPInline]
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('group', 'organizer').prefetch_related('rsvps')
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    
    def delete_queryset(self, request, queryset):
        """Override to handle bulk deletion with proper cascade"""
        with transaction.atomic():
            for event in queryset:
                # Delete related RSVPs first
                event.rsvps.all().delete()
                # Delete the event
                event.delete()

class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'website', 'contact_email', 'telegram_channel')
    search_fields = ('name', 'description')
    inlines = [GroupRoleInline]
    
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('events', 'group_roles')
    
    def delete_queryset(self, request, queryset):
        """Override to handle bulk deletion with proper cascade"""
        with transaction.atomic():
            for group in queryset:
                # Delete related events and their RSVPs
                for event in group.event_set.all():
                    event.rsvps.all().delete()
                    event.delete()
                # Delete related group roles
                group.group_roles.all().delete()
                # Delete the group
                group.delete()

class RSVPAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'status', 'timestamp')
    list_filter = ('status', 'timestamp')
    search_fields = ('user__username', 'event__title')
    readonly_fields = ('timestamp',)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'event')

class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'published')
    list_filter = ('published',)
    search_fields = ('title', 'content')
    readonly_fields = ('published',)

# Register your models here.
admin.site.register(Group, GroupAdmin)
admin.site.register(Event, EventAdmin)
admin.site.register(RSVP, RSVPAdmin)
admin.site.register(Post, PostAdmin)
