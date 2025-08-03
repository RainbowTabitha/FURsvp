from django.contrib import admin
from .models import Profile, GroupRole, AuditLog, Notification, BannedUser, GroupDelegation
from events.models import Group, Event, RSVP
from django.db import transaction
from django.db.utils import IntegrityError
from django.db import connection
from django.db.models.signals import post_delete
from django.dispatch import receiver

class GroupRoleInline(admin.TabularInline):
    model = GroupRole
    extra = 1

class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'display_name', 'discord_username', 'telegram_username', 'telegram_id')
    search_fields = ('user__username', 'user__email', 'display_name', 'discord_username', 'telegram_username')
    fields = ('user', 'display_name', 'discord_username', 'telegram_username', 'telegram_id', 'profile_picture_base64', 'can_post_blog')
    readonly_fields = ('user',)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    
    def delete_queryset(self, request, queryset):
        """Override to handle bulk deletion with proper cascade"""
        with transaction.atomic():
            # Delete related objects first
            for profile in queryset:
                # Delete related notifications
                Notification.objects.filter(user=profile.user).delete()
                # Delete related audit logs
                AuditLog.objects.filter(user=profile.user).delete()
                AuditLog.objects.filter(target_user=profile.user).delete()
                # Delete related group roles
                GroupRole.objects.filter(user=profile.user).delete()
                # Delete related banned user entries
                BannedUser.objects.filter(user=profile.user).delete()
                # Delete related group delegations
                GroupDelegation.objects.filter(organizer=profile.user).delete()
                GroupDelegation.objects.filter(delegated_user=profile.user).delete()
                # Delete the profile
                profile.delete()

admin.site.register(Profile, ProfileAdmin)

from django.contrib.auth.models import User
class UserAdmin(admin.ModelAdmin):
    inlines = [GroupRoleInline]
    list_display = ('username', 'email', 'is_staff', 'is_superuser')
    
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('group_roles', 'profile')
    
    def delete_queryset(self, request, queryset):
        """Override to handle bulk deletion with proper cascade"""
        with transaction.atomic():
            for user in queryset:
                try:
                    # Temporarily disconnect the post_delete signal to prevent conflicts
                    post_delete.disconnect(receiver=None, sender=User, dispatch_uid='events.signals.decrement_user_stats')
                    
                    # Delete related notifications
                    Notification.objects.filter(user=user).delete()
                    
                    # Delete related audit logs
                    AuditLog.objects.filter(user=user).delete()
                    AuditLog.objects.filter(target_user=user).delete()
                    
                    # Delete related group roles
                    GroupRole.objects.filter(user=user).delete()
                    
                    # Delete related banned user entries
                    BannedUser.objects.filter(user=user).delete()
                    BannedUser.objects.filter(banned_by=user).delete()
                    BannedUser.objects.filter(organizer=user).delete()
                    
                    # Delete related group delegations
                    GroupDelegation.objects.filter(organizer=user).delete()
                    GroupDelegation.objects.filter(delegated_user=user).delete()
                    
                    # Delete related RSVPs
                    RSVP.objects.filter(user=user).delete()
                    
                    # Delete events where user is organizer (and their RSVPs)
                    for event in Event.objects.filter(organizer=user):
                        event.rsvps.all().delete()
                        event.delete()
                    
                    # Check for any remaining foreign key relationships
                    with connection.cursor() as cursor:
                        # Get all tables that might reference this user
                        cursor.execute("""
                            SELECT name FROM sqlite_master 
                            WHERE type='table' AND name LIKE '%user%'
                        """)
                        tables = cursor.fetchall()
                        
                        for table in tables:
                            table_name = table[0]
                            try:
                                cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE user_id = {user.id}")
                                count = cursor.fetchone()[0]
                                if count > 0:
                                    print(f"Warning: {count} records in {table_name} reference user {user.username}")
                            except:
                                pass
                    
                    # Delete the user (this will cascade to profile)
                    user.delete()
                    
                    # Manually decrement user stats after successful deletion
                    try:
                        from events.models import PlatformStats
                        PlatformStats.decrement_users()
                    except Exception as e:
                        print(f"Warning: Could not decrement user stats: {e}")
                        
                except IntegrityError as e:
                    # Log the specific integrity error
                    print(f"IntegrityError preventing deletion of {user.username}: {e}")
                    raise
                except Exception as e:
                    print(f"Error deleting user {user.username}: {e}")
                    raise
                finally:
                    # Reconnect the signal
                    try:
                        from events.signals import decrement_user_stats
                        post_delete.connect(decrement_user_stats, sender=User, dispatch_uid='events.signals.decrement_user_stats')
                    except:
                        pass

admin.site.unregister(User)
admin.site.register(User, UserAdmin)

class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'target_user', 'group', 'event', 'timestamp', 'ip_address')
    list_filter = ('action', 'timestamp', 'group', 'event')
    search_fields = ('user__username', 'target_user__username', 'description', 'group__name', 'event__title')
    readonly_fields = ('user', 'action', 'description', 'target_user', 'group', 'event', 'ip_address', 'user_agent', 'timestamp', 'additional_data')
    ordering = ('-timestamp',)
    list_per_page = 50
    
    def has_add_permission(self, request):
        return False  # Prevent manual creation of audit logs
    
    def has_change_permission(self, request, obj=None):
        return False  # Prevent editing of audit logs
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser  # Only superusers can delete audit logs

admin.site.register(AuditLog, AuditLogAdmin)

class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'message', 'is_read', 'timestamp', 'event_name')
    list_filter = ('is_read', 'timestamp')
    search_fields = ('user__username', 'message', 'event_name')
    readonly_fields = ('user', 'message', 'timestamp', 'link', 'event_name')
    ordering = ('-timestamp',)
    list_per_page = 50
    
    def has_add_permission(self, request):
        return False  # Prevent manual creation of notifications
    
    def has_change_permission(self, request, obj=None):
        return False  # Prevent editing of notifications
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

admin.site.register(Notification, NotificationAdmin)

class BannedUserAdmin(admin.ModelAdmin):
    list_display = ('user', 'group', 'banned_by', 'reason', 'banned_at')
    list_filter = ('banned_at', 'group')
    search_fields = ('user__username', 'group__name', 'reason')
    readonly_fields = ('banned_at',)
    ordering = ('-banned_at',)

admin.site.register(BannedUser, BannedUserAdmin)

class GroupDelegationAdmin(admin.ModelAdmin):
    list_display = ('organizer', 'delegated_user', 'group')
    list_filter = ('group',)
    search_fields = ('organizer__username', 'delegated_user__username', 'group__name')

admin.site.register(GroupDelegation, GroupDelegationAdmin) 