from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import login, authenticate
from django.contrib.auth.views import LoginView
from .forms import UserRegisterForm, UserProfileForm, AssistantAssignmentForm, UserPublicProfileForm, UserPasswordChangeForm
from events.models import Group, RSVP, Event
from events.forms import GroupForm, RenameGroupForm
from .models import Profile, GroupDelegation, BannedUser, Notification, GroupRole
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q
from django.db import models, transaction
import json
from django.core.serializers.json import DjangoJSONEncoder
from .utils import create_notification
from django.contrib.auth import get_user_model
from urllib.parse import urlparse
import base64
from django.core.files.base import ContentFile
from PIL import Image
import io
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.conf import settings

# Create your views here.

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            if not hasattr(user, 'profile'):
                Profile.objects.create(user=user)
            # Create welcome notification
            create_notification(
                user,
                'Welcome to FURsvp! We\'re excited to have you join our community. You can now RSVP to events and connect with other members.',
                link='/'
            )
            return redirect('registration_success')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})

def registration_success(request):
    return render(request, 'users/registration_success.html')

def pending_approval(request):
    return render(request, 'users/pending_approval.html')

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

            print("POST data:", post_data)  # Debug print
            profile_form = UserPublicProfileForm(post_data, instance=request.user.profile)
            if profile_form.is_valid():
                print("Form is valid")  # Debug print
                print("Form cleaned data:", profile_form.cleaned_data)  # Debug print
                # Handle clear profile picture
                if profile_form.cleaned_data.get('clear_profile_picture'):
                    request.user.profile.profile_picture_base64 = None
                    request.user.profile.save()
                    create_notification(request.user, 'Your profile picture has been removed.', link='/users/profile/')
                
                # Save profile settings
                profile = profile_form.save()
                return redirect('profile')
            else:
                print("Form errors:", profile_form.errors)  # Debug print
                messages.error(request, f'Error updating profile settings: {profile_form.errors}', extra_tags='admin_notification')
        
        elif 'submit_password_changes' in request.POST: # Handle password change
            password_change_form = UserPasswordChangeForm(user=request.user, data=request.POST)
            if password_change_form.is_valid():
                password_change_form.save()
                create_notification(request.user, 'Your password has been updated successfully.', link='/users/profile/')
                return redirect('profile') # Redirect to clear the POST data and display message
            else:
                messages.error(request, f'Error changing password: {password_change_form.errors}', extra_tags='admin_notification')

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
        'telegram_bot_username': settings.TELEGRAM_BOT_USERNAME,
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
                return JsonResponse({'status': 'success', 'message': f'{target_user.profile.get_display_name()} has been unbanned from the site.'})
            
            elif ban_type == 'group' and group:
                if not can_ban_group:
                    return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)
                BannedUser.objects.filter(user=target_user, group=group).delete()
                return JsonResponse({'status': 'success', 'message': f'{target_user.profile.get_display_name()} has been unbanned from {group.name}.'})

        elif action == 'ban':
            if ban_type == 'sitewide':
                if not can_ban_sitewide:
                    return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)
                BannedUser.objects.get_or_create(user=target_user, group=None, defaults={'banned_by': request.user, 'reason': reason or 'Banned from admin panel.'})
                return JsonResponse({'status': 'success', 'message': f'{target_user.profile.get_display_name()} has been banned from the site.'})

            elif ban_type == 'group' and group:
                if not can_ban_group:
                    return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)
                BannedUser.objects.get_or_create(user=target_user, group=group, defaults={'banned_by': request.user, 'reason': reason or 'Banned from group.'})
                return JsonResponse({'status': 'success', 'message': f'{target_user.profile.get_display_name()} has been banned from {group.name}.'})

        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=500)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def administration(request):
    # Get search parameters
    user_search = request.GET.get('user_search', '').strip()
    group_search = request.GET.get('group_search', '').strip()
    
    # Get all users including superusers with search and pagination
    all_users = User.objects.all().prefetch_related('profile')
    
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
        users_to_promote = user_paginator.page(user_page)
    except (PageNotAnInteger, EmptyPage):
        users_to_promote = user_paginator.page(1)

    # Get all groups with search and pagination
    all_groups = Group.objects.all()
    
    # Apply group search filter if provided
    if group_search:
        all_groups = all_groups.filter(name__icontains=group_search)
    
    group_paginator = Paginator(all_groups, 10)
    group_page = request.GET.get('group_page', 1)
    try:
        paginated_groups = group_paginator.page(group_page)
    except (PageNotAnInteger, EmptyPage):
        paginated_groups = group_paginator.page(1)

    group_form = GroupForm()
    rename_group_forms = {group.id: RenameGroupForm(instance=group) for group in all_groups}
    user_profile_forms = {user_obj.id: UserProfileForm(instance=user_obj.profile, prefix=f'profile_{user_obj.id}') for user_obj in all_users}
    all_banned_users = BannedUser.objects.all().select_related('user', 'group', 'banned_by', 'organizer').order_by('-banned_at')

    if request.method == 'POST':
        if 'promote_users_submit' in request.POST:
            success_count = 0
            error_count = 0
            for user_obj in users_to_promote:
                try:
                    user_obj.profile.refresh_from_db()
                    profile_form = UserProfileForm(request.POST, instance=user_obj.profile, prefix=f'profile_{user_obj.id}')
                    if profile_form.is_valid():
                        profile_form.save()
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    error_count += 1
                    messages.error(request, f'Error updating profile for {user_obj.username}: {str(e)}', extra_tags='admin_notification')

            if success_count > 0:
                messages.success(request, f'Successfully updated {success_count} user profiles.', extra_tags='admin_notification')
            if error_count > 0:
                messages.error(request, f'Failed to update {error_count} user profiles.', extra_tags='admin_notification')

            return redirect('administration')
        
        elif 'create_group_submit' in request.POST:
            group_form = GroupForm(request.POST)
            if group_form.is_valid():
                try:
                    group_form.save()
                    create_notification(request.user, f'You have created a new group: {group_form.instance.name}.', link='/administration')
                except Exception as e:
                    pass
            else:
                messages.error(request, 'Error creating group: Invalid form data.', extra_tags='admin_notification')
            return redirect('administration')
        
        elif any(f'rename_group_{group.id}' in request.POST for group in all_groups):
            for group in all_groups:
                if f'rename_group_{group.id}' in request.POST:
                    rename_form = RenameGroupForm(request.POST, instance=group)
                    if rename_form.is_valid():
                        try:
                            rename_form.save()
                            create_notification(request.user, f'You have renamed the group to "{group.name}".', link='/administration')
                        except Exception as e:
                            messages.error(request, f'Error renaming group: {str(e)}', extra_tags='admin_notification')
                    else:
                        messages.error(request, f'Error renaming group: Invalid form data.', extra_tags='admin_notification')
                    break
        
        elif 'delete_group_submit' in request.POST:
            group_id = request.POST.get('group_id')
            if group_id:
                try:
                    group_to_delete = Group.objects.get(id=group_id)
                    group_name = group_to_delete.name
                    group_to_delete.delete()
                    create_notification(request.user, f'You have deleted the group "{group_name}".', link='/administration')
                except Group.DoesNotExist:
                    messages.error(request, 'Group not found.', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error deleting group: {str(e)}', extra_tags='admin_notification')

        elif 'send_bulk_notification' in request.POST:
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

        return redirect('administration')

    context = {
        'users_to_promote': users_to_promote,
        'all_groups': paginated_groups,
        'group_form': group_form,
        'rename_group_forms': rename_group_forms,
        'user_profile_forms': user_profile_forms,
        'all_banned_users': all_banned_users,
        'user_search': user_search,
        'group_search': group_search,
    }
    return render(request, 'users/administration.html', context)

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

@login_required
def link_telegram_account(request):
    """
    Link existing account to Telegram
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            telegram_data = data.get('telegram_data', {})
            
            if not telegram_data:
                return JsonResponse({'success': False, 'error': 'No Telegram data provided'})
            
            # Check if this Telegram account is already linked to another user
            telegram_id = telegram_data.get('id')
            if telegram_id:
                existing_profile = Profile.objects.filter(telegram_id=telegram_id).exclude(user=request.user).first()
                if existing_profile:
                    return JsonResponse({
                        'success': False, 
                        'error': 'This Telegram account is already linked to another user'
                    })
            
            # Update user's profile with Telegram data
            profile = request.user.profile
            profile.telegram_id = telegram_id
            profile.telegram_username = telegram_data.get('username')
            
            # Update display name if not already set
            if not profile.display_name:
                first_name = telegram_data.get('first_name', '')
                last_name = telegram_data.get('last_name', '')
                profile.display_name = f"{first_name} {last_name}".strip()
            
            profile.save()
            
            create_notification(
                request.user, 
                'Your account has been successfully linked to Telegram!', 
                link='/users/profile/'
            )
            
            return JsonResponse({
                'success': True, 
                'message': 'Account successfully linked to Telegram!'
            })
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

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
        return context
