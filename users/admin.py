from django.contrib import admin
from .models import Profile, GroupRole

# Register your models here.
admin.site.register(Profile)

@admin.register(GroupRole)
class GroupRoleAdmin(admin.ModelAdmin):
    list_display = ('user', 'group', 'role_name', 'role_level', 'is_active', 'assigned_at')
    list_filter = ('role_level', 'is_active', 'group', 'assigned_at')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'group__name', 'role_name')
    ordering = ('group', 'role_level', 'assigned_at')
    list_editable = ('role_level', 'is_active')
    
    fieldsets = (
        ('Role Information', {
            'fields': ('user', 'group', 'role_name', 'role_level')
        }),
        ('Assignment Details', {
            'fields': ('assigned_by', 'assigned_at', 'is_active'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('assigned_at',)
    
    def save_model(self, request, obj, form, change):
        if not change:  # Only set assigned_by on creation
            obj.assigned_by = request.user
        super().save_model(request, obj, form, change)
