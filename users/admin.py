from django.contrib import admin
from .models import Profile, GroupRole
from events.models import Group

class GroupRoleInline(admin.TabularInline):
    model = GroupRole
    extra = 1

class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'display_name', 'discord_username', 'telegram_username')

admin.site.register(Profile, ProfileAdmin)

class GroupAdmin(admin.ModelAdmin):
    inlines = [GroupRoleInline]
    list_display = ('name', 'description', 'website', 'contact_email', 'telegram_channel')

admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)

from django.contrib.auth.models import User
class UserAdmin(admin.ModelAdmin):
    inlines = [GroupRoleInline]
    list_display = ('username', 'email', 'is_staff', 'is_superuser')

admin.site.unregister(User)
admin.site.register(User, UserAdmin) 