from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.views import LoginView, PasswordResetView, PasswordResetDoneView, PasswordResetConfirmView, PasswordResetCompleteView
from .forms import UserRegisterForm, UserProfileForm, UserGroupManagementForm, UserPermissionForm, AssistantAssignmentForm, UserPublicProfileForm, UserPasswordChangeForm
from events.models import Group, RSVP, Event
from events.forms import GroupForm, RenameGroupForm
from .models import Profile, GroupDelegation, BannedUser, Notification, GroupRole, AuditLog
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q
from django.db import models, transaction
import json
from django.core.serializers.json import DjangoJSONEncoder
from .utils import create_notification
from django.contrib.auth import get_user_model
from urllib.parse import urlparse
import base64
import binascii
from django.core.files.base import ContentFile
from PIL import Image
import io
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.conf import settings
from django.urls import reverse
from django.core.cache import cache
from users.forms import TOTPDeviceForm
from django_otp.plugins.otp_totp.models import TOTPDevice
import secrets
import qrcode
from io import BytesIO
import urllib.parse
from urllib.parse import quote
from django.utils.http import url_has_allowed_host_and_scheme
from .forms import BlueskyBlogPostForm
from django.contrib.auth.decorators import login_required, permission_required
import os
from atproto import Client, models as atproto_models
import uuid
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.views import PasswordResetView
from django.urls import reverse_lazy

# Create your views here.

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.save()
            if not hasattr(user, 'profile'):
                Profile.objects.create(user=user)
            profile = user.profile
            # Generate verification token
            token = uuid.uuid4().hex
            profile.verification_token = token
            profile.is_verified = False
            profile.save()
            # Send verification email
            verification_link = request.build_absolute_uri(f"/users/verify/{token}/")
            send_mail(
                'Verify your email address',
                f'Welcome to FURsvp! Please verify your email by clicking this link: {verification_link}',
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            messages.info(request, 'A verification email has been sent to your address. Please verify to activate your account.')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})

def registration_success(request):
    return render(request, 'users/registration_success.html')

def pending_approval(request):
    return render(request, 'users/pending_approval.html')

def verify_email(request, token):
    profile = get_object_or_404(Profile, verification_token=token)
    if profile.is_verified:
        messages.info(request, 'Your email is already verified.')
    else:
        profile.is_verified = True
        profile.verification_token = None
        profile.save()
        messages.success(request, 'Your email has been verified! You can now log in.')
    return redirect('login')

@login_required
def profile(request):
    
    user_events = request.user.event_set.all().order_by('date')
    
    # Initialize forms for GET requests or if no specific POST action is taken
    profile_form = UserPublicProfileForm(instance=request.user.profile)
    assistant_assignment_form = AssistantAssignmentForm(organizer_profile=request.user.profile)
    existing_assignments = GroupDelegation.objects.filter(organizer=request.user).order_by('group__name', 'delegated_user__username')
    password_change_form = UserPasswordChangeForm(user=request.user)

    banned_users_in_groups = []
    organizer_groups = Group.objects.filter(group_roles__user=request.user)
    banned_users_in_groups = BannedUser.objects.filter(group__in=organizer_groups).select_related('user__profile', 'group', 'banned_by').order_by('group__name', 'user__username')

    device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()

    if request.method == 'POST':
        if 'submit_pfp_changes' in request.POST: # Handle profile picture upload
            base64_image_string = request.POST.get('profile_picture_base64')

            # --- Security Validation ---
            if base64_image_string:
                try:
                    # 1. Check file size
                    if len(base64_image_string) > 8 * 1024 * 1024: # Approx 8MB limit
                        messages.error(request, "Image file size is too large. Please upload an image under 1MB.")
                        return redirect('profile')

                    # 2. Decode and check file type
                    format, imgstr = base64_image_string.split(';base64,') 
                    ext = format.split('/')[-1]
                    if ext.lower() not in ['jpeg', 'jpg', 'png', 'gif']:
                        messages.error(request, "Invalid file type. Please upload a JPG, PNG, or GIF image.")
                        return redirect('profile')
                    
                    # 3. Verify it's a valid image and resanitize it
                    image_data = base64.b64decode(imgstr)
                    image_stream = io.BytesIO(image_data)
                    pil_image = Image.open(image_stream)
                    pil_image.verify()  # Verify that it is, in fact, an image

                    # Re-open the image after verify(), since verify() leaves the image unusable
                    image_stream.seek(0)
                    pil_image = Image.open(image_stream)

                    # Re-save to a clean buffer to strip any malicious metadata
                    sanitized_buffer = io.BytesIO()
                    pil_image.save(sanitized_buffer, format=pil_image.format)
                    sanitized_base64_string = base64.b64encode(sanitized_buffer.getvalue()).decode('utf-8')
                    request.user.profile.profile_picture_base64 = f"data:image/{ext};base64,{sanitized_base64_string}"
                    
                    create_notification(request.user, 'Your profile picture has been updated.', link='/users/profile/')
                
                except Exception as e:
                    messages.error(request, "There was an error processing your image. It may be corrupt or an unsupported format.")
                    return redirect('profile')

            else:  # Clear existing image
                request.user.profile.profile_picture_base64 = None
                create_notification(request.user, 'Your profile picture has been removed.', link='/users/profile/')
            
            request.user.profile.save()
            return redirect('profile')
        
        elif 'submit_profile_changes' in request.POST: # Handle general profile settings update
            # Create a mutable copy of request.POST
            post_data = request.POST.copy()

            # If profile picture is not being updated via the modal, ensure its value is preserved
            if 'profile_picture_base64' not in post_data and request.user.profile.profile_picture_base64:
                post_data['profile_picture_base64'] = request.user.profile.profile_picture_base64
            profile_form = UserPublicProfileForm(post_data, instance=request.user.profile)
            if profile_form.is_valid():
                # Handle clear profile picture
                if profile_form.cleaned_data.get('clear_profile_picture'):
                    request.user.profile.profile_picture_base64 = None
                    request.user.profile.save()
                    create_notification(request.user, 'Your profile picture has been removed.', link='/users/profile/')
                
                # Save profile settings
                profile = profile_form.save()
                return redirect('profile')
            else:
                messages.error(request, f'Error updating profile settings: {profile_form.errors}', extra_tags='admin_notification')
        
        elif 'submit_password_changes' in request.POST: # Handle password change
            password_change_form = UserPasswordChangeForm(user=request.user, data=request.POST)
            if password_change_form.is_valid():
                password_change_form.save()
                create_notification(request.user, 'Your password has been updated successfully.', link='/users/profile/')
                return redirect('profile') # Redirect to clear the POST data and display message
            else:
                messages.error(request, f'Error changing password: {password_change_form.errors}', extra_tags='admin_notification')

        elif 'submit_notification_changes' in request.POST: # Handle notification settings
            # Update email notification preference
            email_notifications = request.POST.get('email_notifications') == 'on'
            request.user.profile.email_notifications = email_notifications
            request.user.profile.save()
            
            status = 'enabled' if email_notifications else 'disabled'
            create_notification(request.user, f'Email notifications have been {status}.', link='/users/profile/')
            messages.success(request, f'Notification settings updated successfully. Email notifications are now {status}.')
            return redirect('profile')

        elif 'create_assignment_submit' in request.POST: # Handle creating assistant assignment
            # Allow if user is a leader of any group
            if GroupRole.objects.filter(user=request.user).exists():
                assistant_assignment_form = AssistantAssignmentForm(request.POST, organizer_profile=request.user.profile)
                if assistant_assignment_form.is_valid():
                    assignment = assistant_assignment_form.save(commit=False)
                    assignment.organizer = request.user
                    try:
                        assignment.save()
                        create_notification(request.user, f'You have assigned {assignment.delegated_user.username} as an assistant for {assignment.group.name}.', link='/users/profile/')
                        create_notification(assignment.delegated_user, f'You have been assigned as an assistant for {assignment.group.name}.', link='/users/profile/')
                        return redirect('profile')
                    except Exception as e:
                        messages.error(request, f'Error creating assistant assignment: {e}', extra_tags='admin_notification')
                else:
                    messages.error(request, f'Error creating assistant assignment: {assistant_assignment_form.errors}', extra_tags='admin_notification')
            else:
                messages.error(request, 'You are not authorized to create assistant assignments.', extra_tags='admin_notification')

        elif 'delete_assignment_submit' in request.POST: # Handle deleting assistant assignment
            if GroupRole.objects.filter(user=request.user).exists():
                assignment_id = request.POST.get('assignment_id')
                if assignment_id:
                    try:
                        assignment_to_delete = GroupDelegation.objects.get(id=assignment_id, organizer=request.user)
                        delegated_user_name = assignment_to_delete.delegated_user.username
                        group_name = assignment_to_delete.group.name
                        assignment_to_delete.delete()
                        create_notification(request.user, f'You have removed {delegated_user_name} as an assistant for {group_name}.', link='/users/profile/')
                        create_notification(assignment_to_delete.delegated_user, f'Your assistant role for {group_name} has been removed.', link='/users/profile/')
                    except GroupDelegation.DoesNotExist:
                        messages.error(request, 'Assistant assignment not found or you do not have permission to delete it.', extra_tags='admin_notification')
                return redirect('profile')
            else:
                messages.error(request, 'You are not authorized to delete assistant assignments.', extra_tags='admin_notification')

        elif 'delete_account' in request.POST:
            user = request.user
            with transaction.atomic():
                RSVP.objects.filter(user=user).delete()
                GroupRole.objects.filter(user=user).delete()
                GroupDelegation.objects.filter(organizer=user).delete()
                GroupDelegation.objects.filter(delegated_user=user).delete()
                BannedUser.objects.filter(user=user).delete()
                BannedUser.objects.filter(banned_by=user).delete()
                BannedUser.objects.filter(organizer=user).delete()
                Notification.objects.filter(user=user).delete()
                Profile.objects.filter(user=user).delete()
                user.delete()
            messages.success(request, "Fur-well! May your tail always be fluffy and your conventions drama-free! 🐾")
            return redirect('home')

    context = {
        'user_events': user_events,
        'profile': request.user.profile,
        'assistant_assignment_form': assistant_assignment_form,
        'existing_assignments': existing_assignments,
        'profile_form': profile_form,
        'password_change_form': password_change_form,
        'banned_users_in_groups': banned_users_in_groups,
        'device': device,
        'telegram_bot_username': settings.TELEGRAM_BOT_USERNAME,
        'telegram_login_enabled': settings.TELEGRAM_LOGIN_ENABLED,
    }
    return render(request, 'users/profile.html', context)

@login_required
@require_POST
def ban_user(request, user_id):
    target_user = get_object_or_404(get_user_model(), id=user_id)
    action = request.POST.get('action', 'ban')
    ban_type = request.POST.get('ban_type')
    group_id = request.POST.get('group_id')
    reason = request.POST.get('reason', '')

    # --- Permission Checks ---
    is_admin = request.user.is_superuser
    is_group_leader = False
    group = None

    if group_id:
        try:
            group = Group.objects.get(id=group_id)
            is_group_leader = GroupRole.objects.filter(user=request.user, group=group).exists()
        except Group.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Group not found.'}, status=404)

    can_ban_sitewide = is_admin
    can_ban_group = is_admin or is_group_leader

    if request.user == target_user:
        return JsonResponse({'status': 'error', 'message': 'You cannot ban yourself.'}, status=400)

    # --- Ban/Unban Logic ---
    try:
        if action == 'unban':
            if ban_type == 'sitewide':
                if not can_ban_sitewide:
                    return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)
                BannedUser.objects.filter(user=target_user, group__isnull=True).delete()
                
                # Log the unban action
                AuditLog.log_action(
                    user=request.user,
                    action='user_unbanned',
                    description=f'Unbanned {target_user.username} from site-wide access',
                    target_user=target_user,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    additional_data={
                        'ban_type': 'sitewide',
                        'reason': 'Unbanned from admin panel'
                    }
                )
                
                return JsonResponse({'status': 'success', 'message': f'{target_user.profile.get_display_name()} has been unbanned from the site.'})
            
            elif ban_type == 'group' and group:
                if not can_ban_group:
                    return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)
                BannedUser.objects.filter(user=target_user, group=group).delete()
                
                # Log the unban action
                AuditLog.log_action(
                    user=request.user,
                    action='user_unbanned',
                    description=f'Unbanned {target_user.username} from group {group.name}',
                    target_user=target_user,
                    group=group,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    additional_data={
                        'ban_type': 'group',
                        'group_name': group.name,
                        'reason': 'Unbanned from admin panel'
                    }
                )
                
                return JsonResponse({'status': 'success', 'message': f'{target_user.profile.get_display_name()} has been unbanned from {group.name}.'})

        elif action == 'ban':
            if ban_type == 'sitewide':
                if not can_ban_sitewide:
                    return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)
                banned_entry, created = BannedUser.objects.get_or_create(user=target_user, group=None, defaults={'banned_by': request.user, 'reason': reason or 'Banned from admin panel.'})
                
                if created:
                    # Log the ban action
                    AuditLog.log_action(
                        user=request.user,
                        action='user_banned',
                        description=f'Banned {target_user.username} from site-wide access',
                        target_user=target_user,
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        additional_data={
                            'ban_type': 'sitewide',
                            'reason': reason or 'Banned from admin panel',
                            'banned_by': request.user.username
                        }
                    )
                
                return JsonResponse({'status': 'success', 'message': f'{target_user.profile.get_display_name()} has been banned from the site.'})

            elif ban_type == 'group' and group:
                if not can_ban_group:
                    return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)
                banned_entry, created = BannedUser.objects.get_or_create(user=target_user, group=group, defaults={'banned_by': request.user, 'reason': reason or 'Banned from group.'})
                
                if created:
                    # Log the ban action
                    AuditLog.log_action(
                        user=request.user,
                        action='user_banned',
                        description=f'Banned {target_user.username} from group {group.name}',
                        target_user=target_user,
                        group=group,
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        additional_data={
                            'ban_type': 'group',
                            'group_name': group.name,
                            'reason': reason or 'Banned from group',
                            'banned_by': request.user.username
                        }
                    )
                
                return JsonResponse({'status': 'success', 'message': f'{target_user.profile.get_display_name()} has been banned from {group.name}.'})

        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=500)

@login_required
@user_passes_test(lambda u: u.is_superuser or (hasattr(u, 'profile') and getattr(u.profile, 'can_post_blog', False)))
def administration(request):
    # Helper function to build redirect URL with current state
    def build_redirect_url(tab=None, page=None, search=None, user_filter=None, action_filter=None):
        """Build redirect URL preserving current state parameters"""
        params = {}
        
        # Preserve current tab if not specified
        if tab is None:
            tab = request.GET.get('tab', 'users')
        params['tab'] = tab
        
        # Preserve current pagination based on tab
        if tab == 'users':
            if page is None:
                page = request.GET.get('user_page', 1)
            params['user_page'] = page
        elif tab == 'groups':
            if page is None:
                page = request.GET.get('group_page', 1)
            params['group_page'] = page
        elif tab == 'audit':
            if page is None:
                page = request.GET.get('audit_page', 1)
            params['audit_page'] = page
        elif tab == 'blog':
            if page is None:
                page = request.GET.get('blog_page', 1)
            params['blog_page'] = page
        
        # Preserve search parameters based on tab
        if tab == 'users':
            if search is None:
                search = request.GET.get('user_search', '')
            if search:
                params['user_search'] = search
        elif tab == 'groups':
            if search is None:
                search = request.GET.get('group_search', '')
            if search:
                params['group_search'] = search
        elif tab == 'audit':
            if search is None:
                search = request.GET.get('audit_search', '')
            if search:
                params['audit_search'] = search
            if user_filter is None:
                user_filter = request.GET.get('audit_user_filter', '')
            if user_filter:
                params['audit_user_filter'] = user_filter
            if action_filter is None:
                action_filter = request.GET.get('audit_action_filter', '')
            if action_filter:
                params['audit_action_filter'] = action_filter
        
        # Build URL with parameters
        url = reverse('administration')
        if params:
            query_string = '&'.join([f'{k}={v}' for k, v in params.items() if v])
            if query_string:
                url += '?' + query_string
        return url

    # Get search parameters
    user_search = request.GET.get('user_search', '').strip()
    group_search = request.GET.get('group_search', '').strip()
    
    # Get all users including superusers with search and pagination
    # Staff members first (sorted alphabetically), then regular users (sorted alphabetically)
    all_users = User.objects.all().prefetch_related('profile').order_by('-is_superuser', 'profile__display_name', 'username')
    
    # Apply user search filter if provided
    if user_search:
        all_users = all_users.filter(
            Q(username__icontains=user_search) | 
            Q(email__icontains=user_search) |
            Q(profile__display_name__icontains=user_search)
        )
    
    user_paginator = Paginator(all_users, 10)
    user_page = request.GET.get('user_page', 1)
    try:
        user_page = int(user_page)
        if user_page < 1:
            user_page = 1
    except (TypeError, ValueError):
        user_page = 1
    try:
        users_to_promote = user_paginator.page(user_page)
    except (PageNotAnInteger, EmptyPage):
        users_to_promote = user_paginator.page(1)

    # Get all groups with search and pagination
    all_groups = Group.objects.all().order_by('name')
    
    # Apply group search filter if provided
    if group_search:
        all_groups = all_groups.filter(name__icontains=group_search)
    
    group_paginator = Paginator(all_groups, 10)
    group_page = request.GET.get('group_page', 1)
    try:
        group_page = int(group_page)
        if group_page < 1:
            group_page = 1
    except (TypeError, ValueError):
        group_page = 1
    try:
        paginated_groups = group_paginator.page(group_page)
    except (PageNotAnInteger, EmptyPage):
        paginated_groups = group_paginator.page(1)

    group_form = GroupForm()
    rename_group_forms = {group.id: RenameGroupForm(instance=group) for group in all_groups}
    user_profile_forms = {user_obj.id: UserGroupManagementForm(user_obj, prefix=f'profile_{user_obj.id}') for user_obj in all_users}
    user_permission_forms = {user_obj.id: UserPermissionForm(user_obj, prefix=f'permission_{user_obj.id}') for user_obj in all_users}
    all_banned_users = BannedUser.objects.all().select_related('user', 'group', 'banned_by', 'organizer').order_by('-banned_at')

    # Get audit log entries with filtering
    audit_search = request.GET.get('audit_search', '').strip()
    audit_user_filter = request.GET.get('audit_user_filter', '').strip()
    audit_action_filter = request.GET.get('audit_action_filter', '').strip()
    
    audit_logs = AuditLog.objects.all().select_related('user', 'target_user', 'group', 'event').order_by('-timestamp')
    
    # Apply audit log filters
    if audit_search:
        audit_logs = audit_logs.filter(
            Q(description__icontains=audit_search) |
            Q(user__username__icontains=audit_search) |
            Q(target_user__username__icontains=audit_search) |
            Q(group__name__icontains=audit_search) |
            Q(event__title__icontains=audit_search)
        )
    
    if audit_user_filter:
        audit_logs = audit_logs.filter(
            Q(user__username__icontains=audit_user_filter) |
            Q(target_user__username__icontains=audit_user_filter)
        )
    
    if audit_action_filter:
        audit_logs = audit_logs.filter(action=audit_action_filter)
    
    # Paginate audit logs
    audit_paginator = Paginator(audit_logs, 20)
    audit_page = request.GET.get('audit_page', 1)
    try:
        audit_page = int(audit_page)
        if audit_page < 1:
            audit_page = 1
    except (TypeError, ValueError):
        audit_page = 1
    try:
        paginated_audit_logs = audit_paginator.page(audit_page)
    except (PageNotAnInteger, EmptyPage):
        paginated_audit_logs = audit_paginator.page(1)

    bluesky_posts = []
    bluesky_posts_page = []
    bluesky_posts_paginator = None
    if hasattr(request.user, 'profile') and getattr(request.user.profile, 'can_post_blog', False):
        try:
            bsky_handle = os.environ.get('BLUESKY_HANDLE')
            bsky_app_password = os.environ.get('BLUESKY_APP_PASSWORD')
            if bsky_handle and bsky_app_password:
                client = Client()
                client.login(bsky_handle, bsky_app_password)
                feed = client.get_author_feed(bsky_handle, limit=30)
                bluesky_posts = feed.feed
                blog_page = request.GET.get('blog_page', 1)
                bluesky_posts_paginator = Paginator(bluesky_posts, 5)
                try:
                    bluesky_posts_page = bluesky_posts_paginator.page(blog_page)
                except (PageNotAnInteger, EmptyPage):
                    bluesky_posts_page = bluesky_posts_paginator.page(1)
        except Exception as e:
            messages.error(request, f'Error fetching Bluesky posts: {e}')

    if request.method == 'POST':
        if 'promote_users_submit' in request.POST:
            success_count = 0
            error_count = 0
            
            # Only process users that have form data submitted
            for user_obj in users_to_promote:
                form_prefix = f'profile_{user_obj.id}'
                permission_prefix = f'permission_{user_obj.id}'
                form_field_name = f'{form_prefix}-admin_groups'
                permission_field_name = f'{permission_prefix}-is_superuser'
                
                # Check if this user's form data was actually submitted
                if form_field_name in request.POST or permission_field_name in request.POST:
                    try:
                        user_obj.profile.refresh_from_db()
                        profile_form = UserGroupManagementForm(user_obj, request.POST, prefix=form_prefix)
                        permission_form = UserPermissionForm(user_obj, request.POST, prefix=permission_prefix)
                        
                        profile_valid = profile_form.is_valid()
                        permission_valid = permission_form.is_valid()
                        
                        if profile_valid and permission_valid:
                            # Get current state before saving
                            old_groups = list(user_obj.group_roles.all().values_list('group__name', flat=True))
                            old_is_superuser = user_obj.is_superuser
                            old_can_post_blog = user_obj.profile.can_post_blog if hasattr(user_obj, 'profile') else False
                            
                            # Save the forms
                            profile_form.save()
                            permission_form.save()
                            
                            # Get state after saving
                            new_groups = list(user_obj.group_roles.all().values_list('group__name', flat=True))
                            new_is_superuser = user_obj.is_superuser
                            new_can_post_blog = user_obj.profile.can_post_blog if hasattr(user_obj, 'profile') else False
                            
                            # Log changes if anything changed
                            changes = []
                            if old_groups != new_groups:
                                changes.append(f'Groups: {old_groups} → {new_groups}')
                            if old_is_superuser != new_is_superuser:
                                changes.append(f'Admin: {old_is_superuser} → {new_is_superuser}')
                            if old_can_post_blog != new_can_post_blog:
                                changes.append(f'Blog: {old_can_post_blog} → {new_can_post_blog}')
                            
                            if changes:
                                AuditLog.log_action(
                                    user=request.user,
                                    action='user_profile_updated',
                                    description=f'Updated permissions for user {user_obj.username}',
                                    target_user=user_obj,
                                    ip_address=request.META.get('REMOTE_ADDR'),
                                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                                    additional_data={
                                        'old_data': {
                                            'admin_groups': old_groups,
                                            'is_superuser': old_is_superuser,
                                            'can_post_blog': old_can_post_blog
                                        },
                                        'new_data': {
                                            'admin_groups': new_groups,
                                            'is_superuser': new_is_superuser,
                                            'can_post_blog': new_can_post_blog
                                        },
                                        'changes': '; '.join(changes)
                                    }
                                )
                                success_count += 1
                            else:
                                # No changes, but forms were valid
                                success_count += 1
                        else:
                            error_count += 1
                            messages.error(request, f'Invalid form data for {user_obj.username}: {profile_form.errors}', extra_tags='admin_notification')
                    except Exception as e:
                        error_count += 1
                        messages.error(request, f'Error updating groups for {user_obj.username}: {str(e)}', extra_tags='admin_notification')

            if success_count > 0:
                messages.success(request, f'Successfully processed {success_count} user group assignments.', extra_tags='admin_notification')
            if error_count > 0:
                messages.error(request, f'Failed to process {error_count} user group assignments.', extra_tags='admin_notification')

            # Preserve current state
            return redirect(build_redirect_url(tab='users'))
        
        elif 'create_group_submit' in request.POST:
            # Only process group creation, ignore any user profile data
            group_name = request.POST.get('new_group_name', '').strip()
            if group_name:
                try:
                    # Check if group already exists
                    if Group.objects.filter(name=group_name).exists():
                        messages.error(request, f'A group named "{group_name}" already exists.', extra_tags='admin_notification')
                    else:
                        new_group = Group.objects.create(name=group_name)
                        create_notification(request.user, f'You have created a new group: {new_group.name}.', link='/administration')
                        messages.success(request, f'Group "{new_group.name}" created successfully.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error creating group: {str(e)}', extra_tags='admin_notification')
            else:
                messages.error(request, 'Group name is required.', extra_tags='admin_notification')
            # Preserve current state
            return redirect(build_redirect_url(tab='groups'))
        
        elif any(f'rename_group_{group.id}' in request.POST for group in all_groups):
            for group in all_groups:
                if f'rename_group_{group.id}' in request.POST:
                    # Get the new name from the rename field
                    new_name = request.POST.get(f'rename_{group.id}', '').strip()
                    if new_name:
                        try:
                            old_name = group.name
                            group.name = new_name
                            group.save()
                            create_notification(request.user, f'You have renamed the group to "{group.name}".', link='/administration')
                            
                            # Log the group rename
                            AuditLog.log_action(
                                user=request.user,
                                action='group_renamed',
                                description=f'Renamed group from "{old_name}" to "{group.name}"',
                                group=group,
                                ip_address=request.META.get('REMOTE_ADDR'),
                                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                                additional_data={
                                    'old_name': old_name,
                                    'new_name': group.name
                                }
                            )
                            messages.success(request, f'Group renamed successfully from "{old_name}" to "{group.name}".', extra_tags='admin_notification')
                        except Exception as e:
                            messages.error(request, f'Error renaming group: {str(e)}', extra_tags='admin_notification')
                    else:
                        messages.error(request, 'Group name cannot be empty.', extra_tags='admin_notification')
                    # Preserve current state
                    return redirect(build_redirect_url(tab='groups'))
                    break
        
        elif 'delete_group_submit' in request.POST:
            group_id = request.POST.get('group_id')
            if group_id:
                try:
                    group_to_delete = Group.objects.get(id=group_id)
                    group_name = group_to_delete.name
                    
                    # Check for related data before deletion
                    
                    event_count = Event.objects.filter(group=group_to_delete).count()
                    role_count = GroupRole.objects.filter(group=group_to_delete).count()
                    delegation_count = GroupDelegation.objects.filter(group=group_to_delete).count()
                    ban_count = BannedUser.objects.filter(group=group_to_delete).count()
                    
                    # Log the group deletion before deleting
                    AuditLog.log_action(
                        user=request.user,
                        action='group_deleted',
                        description=f'Deleted group: {group_name} (Events: {event_count}, Roles: {role_count}, Delegations: {delegation_count}, Bans: {ban_count})',
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        additional_data={
                            'group_name': group_name,
                            'group_id': group_id,
                            'event_count': event_count,
                            'role_count': role_count,
                            'delegation_count': delegation_count,
                            'ban_count': ban_count
                        }
                    )
                    
                    # Delete the group (this will cascade delete related records)
                    group_to_delete.delete()
                    
                    # Create success message with details
                    related_items = []
                    if event_count > 0:
                        related_items.append(f"{event_count} event(s)")
                    if role_count > 0:
                        related_items.append(f"{role_count} member(s)")
                    if delegation_count > 0:
                        related_items.append(f"{delegation_count} delegation(s)")
                    if ban_count > 0:
                        related_items.append(f"{ban_count} ban(s)")
                    
                    if related_items:
                        message = f'Successfully deleted group "{group_name}" and all related data: {", ".join(related_items)}.'
                    else:
                        message = f'Successfully deleted group "{group_name}".'
                    
                    messages.success(request, message, extra_tags='admin_notification')
                    create_notification(request.user, f'You have deleted the group "{group_name}".', link='/administration')
                    
                except Group.DoesNotExist:
                    messages.error(request, 'Group not found.', extra_tags='admin_notification')
                except Exception as e:
                    # Provide more specific error information
                    error_msg = str(e)
                    if 'FOREIGN KEY constraint failed' in error_msg:
                        messages.error(request, f'Cannot delete group "{group_name}": It has related data that cannot be automatically removed. Please contact an administrator.', extra_tags='admin_notification')
                    else:
                        messages.error(request, f'Error deleting group: {error_msg}', extra_tags='admin_notification')
                # Preserve current state
                return redirect(build_redirect_url(tab='groups'))

        elif 'add_users_to_group' in request.POST:
            group_id = request.POST.get('add_user_group_id')
            selected_users = request.POST.getlist('selected_users')
            
            if group_id and selected_users:
                try:
                    group = Group.objects.get(id=group_id)
                    added_count = 0
                    already_member_count = 0
                    
                    for user_id in selected_users:
                        try:
                            user = User.objects.get(id=user_id)
                            # Check if user is already in the group
                            if not GroupRole.objects.filter(user=user, group=group).exists():
                                GroupRole.objects.create(user=user, group=group)
                                added_count += 1
                            else:
                                already_member_count += 1
                        except User.DoesNotExist:
                            continue
                    
                    if added_count > 0:
                        messages.success(request, f'Successfully added {added_count} user(s) to group "{group.name}".', extra_tags='admin_notification')
                    if already_member_count > 0:
                        messages.info(request, f'{already_member_count} user(s) were already members of the group.', extra_tags='admin_notification')
                    
                except Group.DoesNotExist:
                    messages.error(request, 'Group not found.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error adding users to group: {str(e)}', extra_tags='admin_notification')
            else:
                messages.error(request, 'Please select a group and at least one user.', extra_tags='admin_notification')
            # Preserve current state
            return redirect(build_redirect_url(tab='groups'))

        elif 'send_bulk_notification' in request.POST:
            message = request.POST.get('notification_message')
            link = request.POST.get('notification_link', None)
            if not message:
                messages.error(request, 'Notification message is required.')
                return redirect(build_redirect_url(tab='notify'))
            UserModel = get_user_model()
            users = UserModel.objects.all()
            admin_name = request.user.profile.get_display_name() if hasattr(request.user, 'profile') else request.user.username
            full_message = f"{admin_name}: {message}"
            for user in users:
                Notification.objects.create(user=user, message=full_message, link=link)
            
            # Log the bulk notification
            AuditLog.log_action(
                user=request.user,
                action='bulk_notification_sent',
                description=f'Sent bulk notification to {users.count()} users: {message[:100]}{"..." if len(message) > 100 else ""}',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                additional_data={
                    'message': message,
                    'link': link,
                    'recipient_count': users.count()
                }
            )
            
            messages.success(request, f'Notification sent to {users.count()} users.')
            # Preserve current state
            return redirect(build_redirect_url(tab='notify'))

        elif request.POST.get('action') == 'update_banner':
            try:                
                # Store banner settings in cache instead of session
                banner_enabled = 'banner_enabled' in request.POST
                banner_text = request.POST.get('banner_text', '').strip()
                banner_type = request.POST.get('banner_type', 'info')
                
                # Validate banner type
                valid_types = ['info', 'warning', 'success', 'danger']
                if banner_type not in valid_types:
                    banner_type = 'info'
                
                # Store in cache (with no timeout - persistent until manually cleared)
                cache.set('banner_enabled', banner_enabled, timeout=None)
                cache.set('banner_text', banner_text, timeout=None)
                cache.set('banner_type', banner_type, timeout=None)
                
                # Clear banner cache if disabled
                if not banner_enabled:
                    cache.delete('banner_enabled')
                    cache.delete('banner_text')
                    cache.delete('banner_type')
                
                # Log the banner update
                if banner_enabled and banner_text:
                    AuditLog.log_action(
                        user=request.user,
                        action='banner_updated',
                        description=f'Updated site banner with {banner_type} style: {banner_text[:100]}{"..." if len(banner_text) > 100 else ""}',
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        additional_data={
                            'banner_text': banner_text,
                            'banner_type': banner_type,
                            'banner_enabled': banner_enabled
                        }
                    )
                    messages.success(request, f'Site banner has been updated and is now visible with {banner_type} style.')
                elif not banner_enabled:
                    AuditLog.log_action(
                        user=request.user,
                        action='banner_disabled',
                        description='Disabled site banner',
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        additional_data={
                            'banner_enabled': banner_enabled
                        }
                    )
                    messages.success(request, 'Site banner has been disabled.')
                else:
                    messages.warning(request, 'Banner is enabled but no text was provided.')
                
            except Exception as e:
                messages.error(request, f'Error updating banner: {str(e)}')
            
            # Preserve current state
            return redirect(build_redirect_url(tab='banner'))

        elif 'update_permissions' in request.POST:
            # Handle user permission updates
            success_count = 0
            error_count = 0
            
            for user_obj in all_users:
                staff_field = f'staff_{user_obj.id}'
                blog_field = f'blog_{user_obj.id}'
                
                if staff_field in request.POST or blog_field in request.POST:
                    try:
                        # Update staff status
                        new_staff_status = staff_field in request.POST
                        if user_obj.is_superuser != new_staff_status:
                            user_obj.is_superuser = new_staff_status
                            user_obj.is_staff = new_staff_status  # Staff should also be staff
                            user_obj.save()
                            
                            # Log the change
                            AuditLog.log_action(
                                user=request.user,
                                action='user_profile_updated',
                                description=f'Updated staff status for user {user_obj.username} to {new_staff_status}',
                                target_user=user_obj,
                                ip_address=request.META.get('REMOTE_ADDR'),
                                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                                additional_data={
                                    'old_staff_status': not new_staff_status,
                                    'new_staff_status': new_staff_status
                                }
                            )
                        
                        # Update blog posting permission
                        new_blog_status = blog_field in request.POST
                        if user_obj.profile.can_post_blog != new_blog_status:
                            user_obj.profile.can_post_blog = new_blog_status
                            user_obj.profile.save()
                            
                            # Log the change
                            AuditLog.log_action(
                                user=request.user,
                                action='user_profile_updated',
                                description=f'Updated blog posting permission for user {user_obj.username} to {new_blog_status}',
                                target_user=user_obj,
                                ip_address=request.META.get('REMOTE_ADDR'),
                                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                                additional_data={
                                    'old_blog_status': not new_blog_status,
                                    'new_blog_status': new_blog_status
                                }
                            )
                        
                        success_count += 1
                    except Exception as e:
                        error_count += 1
                        messages.error(request, f'Error updating permissions for {user_obj.username}: {str(e)}', extra_tags='admin_notification')
            
            if success_count > 0:
                messages.success(request, f'Successfully updated permissions for {success_count} user(s).', extra_tags='admin_notification')
            if error_count > 0:
                messages.error(request, f'Failed to update permissions for {error_count} user(s).', extra_tags='admin_notification')
            
            return redirect(build_redirect_url(tab='users'))

        elif 'update_groups' in request.POST:
            # Handle user group updates
            success_count = 0
            error_count = 0
            
            for user_obj in all_users:
                groups_field = f'groups_{user_obj.id}'
                
                if groups_field in request.POST:
                    try:
                        selected_group_ids = request.POST.getlist(groups_field)
                        
                        # Get current groups
                        current_groups = set(user_obj.group_roles.all().values_list('group_id', flat=True))
                        new_groups = set(int(gid) for gid in selected_group_ids if gid.isdigit())
                        
                        # Find groups to add and remove
                        groups_to_add = new_groups - current_groups
                        groups_to_remove = current_groups - new_groups
                        
                        # Remove groups
                        if groups_to_remove:
                            GroupRole.objects.filter(user=user_obj, group_id__in=groups_to_remove).delete()
                        
                        # Add groups
                        for group_id in groups_to_add:
                            try:
                                group = Group.objects.get(id=group_id)
                                GroupRole.objects.create(user=user_obj, group=group)
                            except Group.DoesNotExist:
                                continue
                        
                        if groups_to_add or groups_to_remove:
                            # Log the change
                            AuditLog.log_action(
                                user=request.user,
                                action='user_profile_updated',
                                description=f'Updated groups for user {user_obj.username}',
                                target_user=user_obj,
                                ip_address=request.META.get('REMOTE_ADDR'),
                                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                                additional_data={
                                    'groups_added': list(groups_to_add),
                                    'groups_removed': list(groups_to_remove)
                                }
                            )
                        
                        success_count += 1
                    except Exception as e:
                        error_count += 1
                        messages.error(request, f'Error updating groups for {user_obj.username}: {str(e)}', extra_tags='admin_notification')
            
            if success_count > 0:
                messages.success(request, f'Successfully updated groups for {success_count} user(s).', extra_tags='admin_notification')
            if error_count > 0:
                messages.error(request, f'Failed to update groups for {error_count} user(s).', extra_tags='admin_notification')
            
            return redirect(build_redirect_url(tab='users'))

        elif 'ban_user_submit' in request.POST:
            # Handle user banning
            user_id = request.POST.get('ban_user_id')
            reason = request.POST.get('ban_reason', '').strip()
            
            if user_id and reason:
                try:
                    user_to_ban = User.objects.get(id=user_id)
                    
                    # Check if user is already banned
                    if BannedUser.objects.filter(user=user_to_ban, group__isnull=True).exists():
                        messages.error(request, f'User {user_to_ban.username} is already banned.', extra_tags='admin_notification')
                    else:
                        # Create site-wide ban
                        BannedUser.objects.create(
                            user=user_to_ban,
                            group=None,  # Site-wide ban
                            banned_by=request.user,
                            organizer=request.user,
                            reason=reason
                        )
                        
                        # Log the ban
                        AuditLog.log_action(
                            user=request.user,
                            action='user_banned',
                            description=f'Banned user {user_to_ban.username} site-wide: {reason}',
                            target_user=user_to_ban,
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', ''),
                            additional_data={
                                'reason': reason,
                                'ban_type': 'site_wide'
                            }
                        )
                        
                        messages.success(request, f'User {user_to_ban.username} has been banned site-wide.', extra_tags='admin_notification')
                except User.DoesNotExist:
                    messages.error(request, 'User not found.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error banning user: {str(e)}', extra_tags='admin_notification')
            else:
                messages.error(request, 'User and reason are required.', extra_tags='admin_notification')
            
            return redirect(build_redirect_url(tab='bans'))

        elif 'unban_user_submit' in request.POST:
            # Handle user unbanning
            user_id = request.POST.get('unban_user_id')
            
            if user_id:
                try:
                    user_to_unban = User.objects.get(id=user_id)
                    ban_entry = BannedUser.objects.filter(user=user_to_unban, group__isnull=True).first()
                    
                    if ban_entry:
                        ban_entry.delete()
                        
                        # Log the unban
                        AuditLog.log_action(
                            user=request.user,
                            action='user_unbanned',
                            description=f'Unbanned user {user_to_unban.username} from site-wide ban',
                            target_user=user_to_unban,
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', ''),
                            additional_data={
                                'ban_type': 'site_wide'
                            }
                        )
                        
                        messages.success(request, f'User {user_to_unban.username} has been unbanned.', extra_tags='admin_notification')
                    else:
                        messages.error(request, f'User {user_to_unban.username} is not banned.', extra_tags='admin_notification')
                except User.DoesNotExist:
                    messages.error(request, 'User not found.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error unbanning user: {str(e)}', extra_tags='admin_notification')
            else:
                messages.error(request, 'User ID is required.', extra_tags='admin_notification')
            
            return redirect(build_redirect_url(tab='bans'))

        elif 'send_notification' in request.POST:
            # Handle notification sending
            recipients = request.POST.get('notification_recipients')
            message = request.POST.get('notification_message', '').strip()
            link = request.POST.get('notification_link', '').strip()
            
            if recipients and message:
                try:
                    users_to_notify = []
                    
                    if recipients == 'all':
                        users_to_notify = User.objects.all()
                    elif recipients == 'organizers':
                        # Get users who are organizers (have group roles with can_post or can_manage_leadership)
                        users_to_notify = User.objects.filter(
                            group_roles__can_post=True
                        ).distinct() | User.objects.filter(
                            group_roles__can_manage_leadership=True
                        ).distinct()
                    elif recipients == 'selected':
                        selected_user_ids = request.POST.getlist('selected_users')
                        users_to_notify = User.objects.filter(id__in=selected_user_ids)
                    
                    if users_to_notify:
                        admin_name = request.user.profile.get_display_name() if hasattr(request.user, 'profile') else request.user.username
                        full_message = f"{admin_name}: {message}"
                        
                        notifications_created = []
                        for user in users_to_notify:
                            notification = Notification.objects.create(
                                user=user,
                                message=full_message,
                                link=link if link else None
                            )
                            notifications_created.append(notification)
                        
                        # Log the notification
                        AuditLog.log_action(
                            user=request.user,
                            action='bulk_notification_sent',
                            description=f'Sent notification to {len(notifications_created)} users: {message[:100]}{"..." if len(message) > 100 else ""}',
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', ''),
                            additional_data={
                                'message': message,
                                'link': link,
                                'recipient_count': len(notifications_created),
                                'recipient_type': recipients
                            }
                        )
                        
                        messages.success(request, f'Notification sent to {len(notifications_created)} users.', extra_tags='admin_notification')
                    else:
                        messages.warning(request, 'No users found to notify.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error sending notification: {str(e)}', extra_tags='admin_notification')
            else:
                messages.error(request, 'Recipients and message are required.', extra_tags='admin_notification')
            
            return redirect(build_redirect_url(tab='notify'))

        elif 'create_blog_post' in request.POST:
            # Handle blog post creation
            title = request.POST.get('blog_title', '').strip()
            content = request.POST.get('blog_content', '').strip()
            
            if title and content and hasattr(request.user, 'profile') and getattr(request.user.profile, 'can_post_blog', False):
                try:
                    bsky_handle = os.environ.get('BLUESKY_HANDLE')
                    bsky_app_password = os.environ.get('BLUESKY_APP_PASSWORD')
                    
                    if bsky_handle and bsky_app_password:
                        client = Client()
                        client.login(bsky_handle, bsky_app_password)
                        
                        # Create the post
                        post_text = f"{title}\n\n{content}"
                        response = client.post(post_text)
                        
                        # Log the blog post
                        AuditLog.log_action(
                            user=request.user,
                            action='blog_post_created',
                            description=f'Created blog post: {title}',
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', ''),
                            additional_data={
                                'title': title,
                                'content_length': len(content),
                                'platform': 'Bluesky'
                            }
                        )
                        
                        messages.success(request, f'Blog post "{title}" has been posted to Bluesky.', extra_tags='admin_notification')
                    else:
                        messages.error(request, 'Bluesky credentials not configured.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error posting to Bluesky: {str(e)}', extra_tags='admin_notification')
            else:
                if not (hasattr(request.user, 'profile') and getattr(request.user.profile, 'can_post_blog', False)):
                    messages.error(request, 'You do not have permission to post blog posts.', extra_tags='admin_notification')
                else:
                    messages.error(request, 'Title and content are required.', extra_tags='admin_notification')
            
            return redirect(build_redirect_url(tab='blog'))

        elif 'delete_blog_post' in request.POST:
            # Handle blog post deletion
            post_uri = request.POST.get('delete_post_uri')
            
            if post_uri and hasattr(request.user, 'profile') and getattr(request.user.profile, 'can_post_blog', False):
                try:
                    bsky_handle = os.environ.get('BLUESKY_HANDLE')
                    bsky_app_password = os.environ.get('BLUESKY_APP_PASSWORD')
                    
                    if bsky_handle and bsky_app_password:
                        client = Client()
                        client.login(bsky_handle, bsky_app_password)
                        
                        # Delete the post
                        client.delete_post(post_uri)
                        
                        # Log the deletion
                        AuditLog.log_action(
                            user=request.user,
                            action='blog_post_deleted',
                            description=f'Deleted blog post: {post_uri}',
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', ''),
                            additional_data={
                                'post_uri': post_uri
                            }
                        )
                        
                        messages.success(request, 'Blog post has been deleted from Bluesky.', extra_tags='admin_notification')
                    else:
                        messages.error(request, 'Bluesky credentials not configured.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error deleting from Bluesky: {str(e)}', extra_tags='admin_notification')
            else:
                if not (hasattr(request.user, 'profile') and getattr(request.user.profile, 'can_post_blog', False)):
                    messages.error(request, 'You do not have permission to delete blog posts.', extra_tags='admin_notification')
                else:
                    messages.error(request, 'Post URI is required.', extra_tags='admin_notification')
            
            return redirect(build_redirect_url(tab='blog'))

        elif 'update_user_modal' in request.POST:
            # Handle user updates from modal
            user_id = request.POST.get('edit_user_id')
            
            if user_id:
                try:
                    user_obj = User.objects.get(id=user_id)
                    
                    # Update staff status
                    new_staff_status = 'modal_staff' in request.POST
                    if user_obj.is_superuser != new_staff_status:
                        user_obj.is_superuser = new_staff_status
                        user_obj.is_staff = new_staff_status
                        user_obj.save()
                        
                        # Log the change
                        AuditLog.log_action(
                            user=request.user,
                            action='user_profile_updated',
                            description=f'Updated staff status for user {user_obj.username} to {new_staff_status}',
                            target_user=user_obj,
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', ''),
                            additional_data={
                                'old_staff_status': not new_staff_status,
                                'new_staff_status': new_staff_status
                            }
                        )
                    
                    # Update blog posting permission
                    new_blog_status = 'modal_blog' in request.POST
                    if user_obj.profile.can_post_blog != new_blog_status:
                        user_obj.profile.can_post_blog = new_blog_status
                        user_obj.profile.save()
                        
                        # Log the change
                        AuditLog.log_action(
                            user=request.user,
                            action='user_profile_updated',
                            description=f'Updated blog posting permission for user {user_obj.username} to {new_blog_status}',
                            target_user=user_obj,
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', ''),
                            additional_data={
                                'old_blog_status': not new_blog_status,
                                'new_blog_status': new_blog_status
                            }
                        )
                    
                    # Update groups
                    selected_group_ids = request.POST.getlist('modal_groups')
                    current_groups = set(user_obj.group_roles.all().values_list('group_id', flat=True))
                    new_groups = set(int(gid) for gid in selected_group_ids if gid.isdigit())
                    
                    # Find groups to add and remove
                    groups_to_add = new_groups - current_groups
                    groups_to_remove = current_groups - new_groups
                    
                    # Remove groups
                    if groups_to_remove:
                        GroupRole.objects.filter(user=user_obj, group_id__in=groups_to_remove).delete()
                    
                    # Add groups
                    for group_id in groups_to_add:
                        try:
                            group = Group.objects.get(id=group_id)
                            GroupRole.objects.create(user=user_obj, group=group)
                        except Group.DoesNotExist:
                            continue
                    
                    if groups_to_add or groups_to_remove:
                        # Log the change
                        AuditLog.log_action(
                            user=request.user,
                            action='user_profile_updated',
                            description=f'Updated groups for user {user_obj.username}',
                            target_user=user_obj,
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', ''),
                            additional_data={
                                'groups_added': list(groups_to_add),
                                'groups_removed': list(groups_to_remove)
                            }
                        )
                    
                    messages.success(request, f'User {user_obj.username} has been updated successfully.', extra_tags='admin_notification')
                    
                except User.DoesNotExist:
                    messages.error(request, 'User not found.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error updating user: {str(e)}', extra_tags='admin_notification')
            else:
                messages.error(request, 'User ID is required.', extra_tags='admin_notification')
            
            return redirect(build_redirect_url(tab='users'))

        # Default redirect if no POST action matched
        return redirect(build_redirect_url())

    context = {
        'users_to_promote': users_to_promote,
        'all_groups': paginated_groups,
        'all_users': all_users,  # Add this for ban form
        'group_form': group_form,
        'rename_group_forms': rename_group_forms,
        'user_profile_forms': user_profile_forms,
        'user_permission_forms': user_permission_forms,
        'all_banned_users': all_banned_users,
        'user_search': user_search,
        'group_search': group_search,
        'audit_logs': paginated_audit_logs,
        'audit_search': audit_search,
        'audit_user_filter': audit_user_filter,
        'audit_action_filter': audit_action_filter,
        'audit_actions': AuditLog.ACTION_CHOICES,
        'banner_enabled': cache.get('banner_enabled', False),
        'banner_text': cache.get('banner_text', ''),
        'banner_type': cache.get('banner_type', 'info'),
        'bluesky_posts': bluesky_posts_page,
        'bluesky_posts_paginator': bluesky_posts_paginator,
    }
    
    # Always use the AJAX template for better performance
    # Get the current tab from GET parameters or default to users
    current_tab = request.GET.get('tab', 'users')
    # Add the tab to the context for the AJAX template
    context['current_tab'] = current_tab
    # Return the AJAX template (which contains the full page structure)
    return render(request, 'users/administration.html', context)

@require_POST
@login_required
def delete_bluesky_post(request):
    if not (hasattr(request.user, 'profile') and getattr(request.user.profile, 'can_post_blog', False)):
        messages.error(request, 'You do not have permission to delete Bluesky posts.')
        return redirect('administration')
    uri = request.POST.get('uri')
    try:
        bsky_handle = os.environ.get('BLUESKY_HANDLE')
        bsky_app_password = os.environ.get('BLUESKY_APP_PASSWORD')
        if not bsky_handle or not bsky_app_password:
            raise Exception('Bluesky credentials not set in environment.')
        client = Client()
        client.login(bsky_handle, bsky_app_password)
        client.delete_post(uri)
        
        # Log the blog post deletion
        AuditLog.log_action(
            user=request.user,
            action='blog_post_deleted',
            description=f'Deleted blog post from Bluesky',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            additional_data={
                'uri': uri,
                'platform': 'Bluesky'
            }
        )
        
        messages.success(request, 'Post deleted from Bluesky.')
    except Exception as e:
        messages.error(request, f'Error deleting post: {e}')
    return redirect(f"{reverse('administration')}?tab=blogmgmt")

@login_required
@user_passes_test(lambda u: u.is_superuser)
def send_notification(request):
    if request.method == 'POST':
        user_ids = request.POST.getlist('user_ids')
        message = request.POST.get('notification_message')
        if not user_ids:
            messages.error(request, "Please select at least one user.")
            return redirect(reverse('administration'))
        if not message:
            messages.error(request, "Please enter a notification message.")
            return redirect(reverse('administration'))
        User = get_user_model()
        users = User.objects.filter(id__in=user_ids)
        for user in users:
            create_notification(user, message, link='/users/notifications/')
        messages.success(request, f"Notification sent to {users.count()} user(s).")
        return redirect(reverse('administration'))
    else:
        messages.error(request, "Invalid request method.")
        return redirect(reverse('administration'))

# New view for username suggestions
@user_passes_test(lambda u: u.is_superuser)
def user_search_autocomplete(request):
    query = request.GET.get('q', '')
    exclude_current = request.GET.get('exclude_current', 'false').lower() == 'true'
    is_organizer_filter = request.GET.get('is_organizer', 'false').lower() == 'true'

    if query:
        users_query = User.objects.filter(
            Q(username__icontains=query) | 
            Q(profile__display_name__icontains=query)
        ).select_related('profile')

        if exclude_current:
            users_query = users_query.exclude(id=request.user.id)

        if is_organizer_filter:
            # Only include users who are a leader of any group
            users_query = users_query.filter(grouprole__isnull=False).distinct()

        users = users_query[:10]
        results = [{
            'id': user.id, 
            'text': f"{user.profile.get_display_name()} ({user.username})",
            'username': user.username,
            'display_name': user.profile.get_display_name()
        } for user in users]
        return JsonResponse({'results': results})
    return JsonResponse({'results': []})

@login_required
@ensure_csrf_cookie
def get_notifications(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-timestamp')
    unread_count = notifications.filter(is_read=False).count()
    notification_list = []
    for notification in notifications:
        notification_list.append({
            'id': notification.id,
            'message': notification.message,
            'is_read': notification.is_read,
            'timestamp': notification.timestamp.isoformat(), # ISO format for easy JS parsing
            'link': notification.link
        })
    return JsonResponse({'notifications': notification_list, 'unread_count': unread_count})

@login_required
@require_POST
def mark_notifications_as_read(request):
    try:
        data = json.loads(request.body)
        notification_ids = data.get('notification_ids', [])
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON.'}, status=400)

    if not isinstance(notification_ids, list):
        return JsonResponse({'status': 'error', 'message': 'notification_ids must be a list.'}, status=400)

    # If no specific IDs are provided, mark all unread notifications for the user as read
    if not notification_ids:
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'status': 'success', 'message': 'All notifications marked as read.'})
    
    # Mark specific notifications as read
    Notification.objects.filter(user=request.user, id__in=notification_ids).update(is_read=True)
    return JsonResponse({'status': 'success', 'message': 'Notifications marked as read.'})

@login_required
@require_POST
@csrf_protect
def purge_read_notifications(request):
    """
    Deletes all read notifications for the authenticated user.
    """
    try:
        # Modified to delete all notifications, not just read ones
        deleted_count, _ = Notification.objects.filter(user=request.user).delete()
        return JsonResponse({'status': 'success', 'message': f'Successfully purged {deleted_count} notifications.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Failed to purge notifications: {str(e)}'}, status=500)

@login_required
@ensure_csrf_cookie
def notifications_page(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-timestamp')
    return render(request, 'users/notifications.html', {'notifications': notifications})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def send_bulk_notification(request):
    if request.method == 'POST':
        message = request.POST.get('notification_message')
        link = request.POST.get('notification_link', None)
        if not message:
            messages.error(request, 'Notification message is required.')
            return redirect('administration')
        UserModel = get_user_model()
        users = UserModel.objects.all()
        admin_name = request.user.profile.get_display_name() if hasattr(request.user, 'profile') else request.user.username
        full_message = f"{admin_name}: {message}"
        for user in users:
            Notification.objects.create(user=user, message=full_message, link=link)
        messages.success(request, f'Notification sent to {users.count()} users.')
        return redirect('administration')
    else:
        messages.error(request, 'Invalid request method.')
        return redirect('administration')

@login_required
def post_to_bluesky(request):
    user = request.user
    can_post = user.has_perm('users.can_post_blog') or (hasattr(user, 'profile') and getattr(user.profile, 'can_post_blog', False))
    if not can_post:
        messages.error(request, 'You do not have permission to post blog posts to Bluesky.')
        return redirect('administration')

    if request.method == 'POST':
        form = BlueskyBlogPostForm(request.POST)
        if form.is_valid():
            title = form.cleaned_data['title']
            content = form.cleaned_data['content']
            # Bluesky API integration
            try:
                bsky_handle = os.environ.get('BLUESKY_HANDLE')
                bsky_app_password = os.environ.get('BLUESKY_APP_PASSWORD')
                if not bsky_handle or not bsky_app_password:
                    raise Exception('Bluesky credentials not set in environment.')
                client = Client()
                client.login(bsky_handle, bsky_app_password)
                post_text = f"{title}\n\n{content}"
                client.send_post(text=post_text)
                
                # Log the blog post creation
                AuditLog.log_action(
                    user=request.user,
                    action='blog_post_created',
                    description=f'Created blog post: {title}',
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    additional_data={
                        'title': title,
                        'content_length': len(content),
                        'platform': 'Bluesky'
                    }
                )
                
                messages.success(request, 'Blog post successfully posted to Bluesky!')
            except Exception as e:
                messages.error(request, f'Error posting to Bluesky: {e}')
            return redirect('administration')
    else:
        form = BlueskyBlogPostForm()
    return render(request, 'users/post_to_bluesky.html', {'form': form})

@csrf_exempt
def telegram_login(request):
    """
    Handle Telegram login via AJAX
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            telegram_data = data.get('telegram_data', {})
            
            if not telegram_data:
                return JsonResponse({'success': False, 'error': 'No Telegram data provided'})
            
            # Authenticate user with Telegram data
            user = authenticate(request, telegram_data=telegram_data)
            
            if user:
                login(request, user)
                return JsonResponse({
                    'success': True, 
                    'redirect_url': '/',
                    'message': 'Successfully logged in with Telegram!'
                })
            else:
                return JsonResponse({
                    'success': False, 
                    'error': 'Invalid Telegram authentication data'
                })
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def telegram_login_embedded(request):
    """
    Handle Telegram login via embedded widget (GET parameters)
    This is for users who are not yet logged in
    """
    if request.method == 'GET':
        # Extract Telegram data from GET parameters
        telegram_data = {
            'id': request.GET.get('id'),
            'first_name': request.GET.get('first_name', ''),
            'last_name': request.GET.get('last_name', ''),
            'username': request.GET.get('username', ''),
            'photo_url': request.GET.get('photo_url', ''),
            'auth_date': request.GET.get('auth_date'),
            'hash': request.GET.get('hash'),
        }
        
        # Validate all required fields
        if not all([telegram_data['id'], telegram_data['auth_date'], telegram_data['hash']]):
            messages.error(request, 'Missing required Telegram data.')
            return redirect('login')
        
        # Hash verification (reuse backend logic)
        from users.backends import TelegramBackend
        backend = TelegramBackend()
        if not backend._validate_telegram_data(telegram_data):
            messages.error(request, 'Telegram authentication failed. Please try again.')
            return redirect('login')
        
        # Authenticate user with Telegram data
        user = authenticate(request, telegram_data=telegram_data)
        
        if user:
            login(request, user)
            messages.success(request, 'Successfully logged in with Telegram!')
            # Redirect to the return_to URL if provided, otherwise to home
            return_to = request.GET.get('return_to', '/')
            if not url_has_allowed_host_and_scheme(return_to, allowed_hosts={request.get_host()}):
                return_to = '/'
            return redirect(return_to)
        else:
            messages.error(request, 'Failed to authenticate with Telegram. Please try again.')
            return redirect('login')
    
    return redirect('login')

@login_required
def link_telegram_account(request):
    if request.method == 'GET':
        # Extract Telegram data from GET parameters
        telegram_data = {
            'id': request.GET.get('id'),
            'first_name': request.GET.get('first_name', ''),
            'last_name': request.GET.get('last_name', ''),
            'username': request.GET.get('username', ''),
            'photo_url': request.GET.get('photo_url', ''),
            'auth_date': request.GET.get('auth_date'),
            'hash': request.GET.get('hash'),
        }
        # Validate all required fields
        if not all([telegram_data['id'], telegram_data['auth_date'], telegram_data['hash']]):
            messages.error(request, 'Missing required Telegram data.')
            return redirect('profile')
        # Hash verification (reuse backend logic)
        from users.backends import TelegramBackend
        backend = TelegramBackend()
        if not backend._validate_telegram_data(telegram_data):
            messages.error(request, 'Telegram authentication failed. Please try again.')
            return redirect('profile')
        # Check if this Telegram account is already linked to another user
        from .models import Profile
        telegram_id = telegram_data['id']
        existing_profile = Profile.objects.filter(telegram_id=telegram_id).exclude(user=request.user).first()
        if existing_profile:
            messages.error(request, 'This Telegram account is already linked to another user.')
            return redirect('profile')
        # Link Telegram to current user
        profile = request.user.profile
        profile.telegram_id = int(telegram_id)
        profile.telegram_username = telegram_data.get('username')
        if not profile.display_name:
            profile.display_name = f"{telegram_data.get('first_name', '')} {telegram_data.get('last_name', '')}".strip()
        profile.save()
        from .views import create_notification
        create_notification(
            request.user,
            'Your account has been successfully linked to Telegram!',
            link='/users/profile/'
        )
        messages.success(request, 'Account successfully linked to Telegram!')
        return redirect(f"{reverse('profile')}?telegram_linked=1")

@login_required
def unlink_telegram_account(request):
    """
    Unlink Telegram account from user profile
    """
    if request.method == 'POST':
        try:
            profile = request.user.profile
            profile.telegram_id = None
            profile.telegram_username = None
            profile.save()
            
            create_notification(
                request.user, 
                'Your Telegram account has been unlinked.', 
                link='/users/profile/'
            )
            
            return JsonResponse({
                'success': True, 
                'message': 'Telegram account unlinked successfully!'
            })
                
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

class CustomLoginView(LoginView):
    template_name = 'users/login.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['telegram_bot_username'] = settings.TELEGRAM_BOT_USERNAME
        context['telegram_login_enabled'] = settings.TELEGRAM_LOGIN_ENABLED
        return context

class CustomPasswordResetView(PasswordResetView):
    template_name = 'users/password_reset.html'
    email_template_name = 'users/password_reset_email.html'
    subject_template_name = 'users/password_reset_subject.txt'
    success_url = reverse_lazy('password_reset_done')

class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'users/password_reset_done.html'

class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'users/password_reset_confirm.html'

class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'users/password_reset_complete.html'

@login_required
def twofa_settings(request):
    device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
    return render(request, 'fkixusers/2fa.html', {'device': device})

@login_required
def twofa_enable(request):
    key = request.session.get('totp_key')
    if not key:
        hex_secret = secrets.token_hex(20)
        key = hex_secret  # Store hex in the model
        request.session['totp_key'] = key
    else:
        hex_secret = key

    # For QR code, convert hex to base32
    secret_bytes = binascii.unhexlify(hex_secret)
    base32_key = base64.b32encode(secret_bytes).decode('utf-8').replace('=', '')

    print(f"[2FA DEBUG] Using hex secret: {hex_secret}")
    print(f"[2FA DEBUG] Using base32 key: {base32_key}")

    if request.method == 'POST':
        form = TOTPDeviceForm(data=request.POST, user=request.user, key=key)
        if form.is_valid():
            device = form.save()
            device.confirmed = True
            device.save()
            request.session.pop('totp_key', None)  # Safely remove key
            return redirect('profile')
    else:
        form = TOTPDeviceForm(user=request.user, key=key)

    # Create otpauth URL
    issuer = "FURsvp"
    label = quote(f"{request.user.email}")
    otpauth_url = f"otpauth://totp/{issuer}:{label}?secret={base32_key}&issuer={quote(issuer)}"
    print(f"[2FA DEBUG] otpauth URL: {otpauth_url}")

    # Generate QR code image
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(otpauth_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").resize((220, 220))

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()
    qr_code_url = f"data:image/png;base64,{qr_code_base64}"

    return render(request, 'users/2fa_enable.html', {
        'form': form,
        'qr_code_url': qr_code_url
    })

@login_required
def twofa_disable(request):
    if request.method == 'POST':
        TOTPDevice.objects.filter(user=request.user).delete()
        return redirect('twofa_settings')
    return render(request, 'users/2fa_disable.html')

@csrf_protect
def custom_login(request):
    error = None
    show_2fa = False
    username = request.POST.get('username') if request.method == 'POST' else ''
    password = request.POST.get('password') if request.method == 'POST' else ''
    token = request.POST.get('token') if request.method == 'POST' else ''
    pre_2fa_user_id = request.session.get('pre_2fa_user_id')
    user = None

    if request.method == 'POST':
        # If we're in the middle of 2FA (user id in session)
        if pre_2fa_user_id:
            from django.contrib.auth import get_user_model
            from django.conf import settings
            User = get_user_model()
            user = User.objects.get(id=pre_2fa_user_id)
            device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
            # Retrieve password from session if available
            if not password:
                password = request.session.get('pre_2fa_password', '')
            if device and token:
                if device.verify_token(token):
                    user.backend = settings.AUTHENTICATION_BACKENDS[0]
                    login(request, user)
                    del request.session['pre_2fa_user_id']
                    if 'pre_2fa_password' in request.session:
                        del request.session['pre_2fa_password']
                    return redirect('profile')
                else:
                    error = 'Invalid 2FA code.'
                    show_2fa = True
            else:
                error = '2FA code required.'
                show_2fa = True
        else:
            # First step: username/password
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if not hasattr(user, 'profile') or not user.profile.is_verified:
                    error = 'You must verify your email before logging in. Please check your inbox.'
                else:
                    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
                    if device:
                        request.session['pre_2fa_user_id'] = user.id
                        request.session['pre_2fa_password'] = password
                        show_2fa = True
                        error = None
                    else:
                        login(request, user)
                        return redirect('profile')
            else:
                error = 'Invalid username or password.'
    else:
        # GET request: clear any previous 2FA session
        if 'pre_2fa_user_id' in request.session:
            del request.session['pre_2fa_user_id']
        if 'pre_2fa_password' in request.session:
            del request.session['pre_2fa_password']

    return render(request, 'users/login.html', {
        'error': error,
        'show_2fa': show_2fa,
        'username': username,
        'password': password,
    })

@require_GET
def api_user_by_telegram(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'Missing username parameter'}, status=400)
    try:
        profile = Profile.objects.get(telegram_username__iexact=username)
        return JsonResponse({
            'id': profile.user.id,
            'username': profile.user.username,
            'display_name': profile.get_display_name(),
            'telegram_username': profile.telegram_username,
            'telegram_id': profile.telegram_id,
        })
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

def approve_all_logged_in_users():
    users = User.objects.exclude(last_login=None)
    for user in users:
        if hasattr(user, 'profile') and not user.profile.is_verified:
            user.profile.is_verified = True
            user.profile.save()

@login_required
@user_passes_test(lambda u: u.is_superuser)
@require_POST
def toggle_admin_status(request):
    """Toggle admin status for a user via AJAX"""
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        new_status = data.get('new_status')
        
        if not user_id or new_status not in ['admin', 'user']:
            return JsonResponse({
                'success': False,
                'error': 'Invalid parameters'
            }, status=400)
        
        # Get the user to modify
        target_user = get_object_or_404(User, id=user_id)
        
        # Prevent self-modification
        if target_user == request.user:
            return JsonResponse({
                'success': False,
                'error': 'You cannot modify your own admin status'
            }, status=400)
        
        # Update the user's admin status
        target_user.is_superuser = (new_status == 'admin')
        target_user.save()
        
        # Log the action
        AuditLog.objects.create(
            user=request.user,
            action='TOGGLE_ADMIN',
            target_user=target_user,
            details=f"Changed admin status to: {new_status}"
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Admin status updated to {new_status}',
            'new_status': new_status
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def custom_logout(request):
    """Custom logout view that accepts GET requests"""
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('home')

@require_GET
@login_required
def get_group_logo(request, group_id):
    """
    Get group logo data for Tom Select dropdowns
    """
    try:
        group = Group.objects.get(id=group_id)
        
        if group.logo_base64:
            return JsonResponse({
                'success': True,
                'logo': group.logo_base64,
                'has_logo': True
            })
        else:
            return JsonResponse({
                'success': True,
                'logo': None,
                'has_logo': False,
                'name': group.name,
                'description': group.description or ''
            })
    except Group.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Group not found'
        })

@require_GET
@login_required
def get_user_avatar(request, user_id):
    """
    Get user avatar data for Tom Select dropdowns
    """
    try:
        user = User.objects.get(id=user_id)
        profile = user.profile
        
        if profile.profile_picture_base64:
            return JsonResponse({
                'success': True,
                'avatar': profile.profile_picture_base64,
                'has_pfp': True
            })
        else:
            return JsonResponse({
                'success': True,
                'avatar': None,
                'has_pfp': False,
                'initials': profile.get_initials(),
                'color': profile.get_avatar_color()
            })
    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'User not found'
        })
