from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from .forms import UserRegisterForm, UserProfileForm, AssistantAssignmentForm, UserPublicProfileForm, UserPasswordChangeForm
from events.models import Group, RSVP
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
            base64_image = request.POST.get('profile_picture_base64')
            if base64_image:  # Update with new image
                request.user.profile.profile_picture_base64 = base64_image
                create_notification(request.user, 'Your profile picture has been updated.', link='/accounts/profile/')
            else:  # Clear existing image
                request.user.profile.profile_picture_base64 = None
                create_notification(request.user, 'Your profile picture has been removed.', link='/accounts/profile/')
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
                    create_notification(request.user, 'Your profile picture has been removed.', link='/accounts/profile/')
                
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
                create_notification(request.user, 'Your password has been updated successfully.', link='/accounts/profile/')
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
                        create_notification(request.user, f'You have assigned {assignment.delegated_user.username} as an assistant for {assignment.group.name}.', link='/accounts/profile/')
                        create_notification(assignment.delegated_user, f'You have been assigned as an assistant for {assignment.group.name}.', link='/accounts/profile/')
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
                        create_notification(request.user, f'You have removed {delegated_user_name} as an assistant for {group_name}.', link='/accounts/profile/')
                        create_notification(assignment_to_delete.delegated_user, f'Your assistant role for {group_name} has been removed.', link='/accounts/profile/')
                    except GroupDelegation.DoesNotExist:
                        messages.error(request, 'Assistant assignment not found or you do not have permission to delete it.', extra_tags='admin_notification')
                return redirect('profile')
            else:
                messages.error(request, 'You are not authorized to delete assistant assignments.', extra_tags='admin_notification')

    context = {
        'user_events': user_events,
        'profile': request.user.profile,
        'assistant_assignment_form': assistant_assignment_form,
        'existing_assignments': existing_assignments,
        'profile_form': profile_form, # Ensure profile_form is always in context
        'password_change_form': password_change_form,
        'banned_users_in_groups': banned_users_in_groups, # Add this to context
    }
    return render(request, 'users/profile.html', context)

@require_POST
@csrf_protect
def ban_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Authentication required.'}, status=401)

    print("ban_user request.POST:", request.POST) # Added for debugging

    try:
        target_user_id = request.POST.get('user_id')
        group_id = request.POST.get('group_id') # Can be None for organizer-wide or sitewide bans
        action = request.POST.get('action') # 'ban' or 'unban'
        reason = request.POST.get('reason', '')
        ban_type = request.POST.get('ban_type', 'group') # Default to 'group' for existing frontend

        if not action or not target_user_id: # Ensure action and user_id are provided
            return JsonResponse({'status': 'error', 'message': 'Missing parameters (action or user ID).'}, status=400)

        try:
            target_user = User.objects.get(id=target_user_id)
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Target User not found.'}, status=404)

        if action == 'ban' and request.user.id == target_user.id:
            return JsonResponse({'status': 'error', 'message': 'You cannot ban yourself.'}, status=403)

        # Permissions Check
        is_site_admin = request.user.is_superuser
        can_manage_group_ban = False
        can_manage_sitewide_ban = is_site_admin # Only site admins can manage sitewide bans

        group = None
        is_delegated_assistant_for_group = False

        if group_id: # If a group_id is provided, it's a group-specific action or relates to a specific group
            try:
                group = Group.objects.get(id=group_id)
                user_profile = None
                try:
                    user_profile = request.user.profile
                except Profile.DoesNotExist:
                    pass

                # User is a group leader if GroupRole exists for this group
                is_group_leader_for_group = GroupRole.objects.filter(user=request.user, group=group).exists()

                is_delegated_assistant_for_group = GroupDelegation.objects.filter(
                    delegated_user=request.user,
                    group=group
                ).exists()
                can_manage_group_ban = is_site_admin or is_group_leader_for_group or is_delegated_assistant_for_group

            except Group.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Group not found.'}, status=404)

        # Determine overall permission for the requested ban_type
        permission_granted = False
        if ban_type == 'group' and can_manage_group_ban:
            permission_granted = True
        elif ban_type == 'organizer' and is_site_admin: # Organizer-wide bans can only be issued by site admins
            permission_granted = True
        elif ban_type == 'sitewide' and is_site_admin:
            permission_granted = True

        if not permission_granted:
            return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)

        # banned_by_user is always the current user making the ban/unban request
        banned_by_user = request.user

        # Action: Ban or Unban
        if action == 'ban':
            # Handle getting organizer_user for 'organizer' ban type or for group bans initiated by an organizer
            organizer_user_for_ban_entry = None # This will be the 'organizer' field in BannedUser model

            if ban_type == 'group':
                if not group:
                    return JsonResponse({'status': 'error', 'message': 'Group ID is required for a group ban.'}, status=400)

                if is_group_leader_for_group:
                    organizer_user_for_ban_entry = request.user
                elif is_delegated_assistant_for_group:
                    delegation = GroupDelegation.objects.filter(delegated_user=request.user, group=group).first()
                    if delegation:
                        organizer_user_for_ban_entry = delegation.organizer
                # If site admin, organizer_user_for_ban_entry remains None, which is fine for site-admin issued group bans

                existing_ban = BannedUser.objects.filter(user=target_user, group=group, organizer=organizer_user_for_ban_entry).first()
                if existing_ban:
                    return JsonResponse({'status': 'info', 'message': f'{target_user.username} is already banned from {group.name}.'})

                BannedUser.objects.create(
                    user=target_user,
                    group=group,
                    banned_by=banned_by_user,
                    reason=reason,
                )
                # Delete RSVPs for this user in this group's events
                RSVP.objects.filter(user=target_user, event__group=group).delete()
                return JsonResponse({'status': 'success', 'message': f'{target_user.username} has been banned from {group.name}.'})

            elif ban_type == 'organizer':
                organizer_id = request.POST.get('organizer_id')
                if not organizer_id:
                    return JsonResponse({'status': 'error', 'message': 'Missing organizer_id for organizer ban.'}, status=400)
                try:
                    organizer_user_for_ban_entry = User.objects.get(id=organizer_id)
                except User.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': 'Organizer not found for organizer ban.'}, status=404)

                existing_ban = BannedUser.objects.filter(user=target_user, organizer=organizer_user_for_ban_entry, group__isnull=True).first()
                if existing_ban:
                    return JsonResponse({'status': 'info', 'message': f'{target_user.username} is already banned from all events by {organizer_user_for_ban_entry.username}.'})

                BannedUser.objects.create(
                    user=target_user,
                    organizer=organizer_user_for_ban_entry,
                    banned_by=banned_by_user,
                    reason=reason,
                    group=None
                )
                # Delete RSVPs for this user in this organizer's events
                RSVP.objects.filter(user=target_user, event__organizer=organizer_user_for_ban_entry).delete()
                return JsonResponse({'status': 'success', 'message': f'{target_user.username} has been banned from all events by {organizer_user_for_ban_entry.username}.'})

            elif ban_type == 'sitewide':
                existing_ban = BannedUser.objects.filter(user=target_user, group__isnull=True, organizer__isnull=True).first()
                if existing_ban:
                    return JsonResponse({'status': 'info', 'message': f'{target_user.username} is already site-wide banned.'})

                BannedUser.objects.create(
                    user=target_user,
                    banned_by=banned_by_user,
                    reason=reason,
                    group=None, # Explicitly set to None for site-wide ban
                    organizer=None # Explicitly set to None for site-wide ban
                )
                return JsonResponse({'status': 'success', 'message': f'{target_user.username} has been site-wide banned.'})
            else:
                return JsonResponse({'status': 'error', 'message': 'Unsupported ban type for this action.'}, status=400)

        elif action == 'unban':
            ban_query = Q(user=target_user)

            if ban_type == 'group':
                if not group:
                    return JsonResponse({'status': 'error', 'message': 'Group ID is required to unban from a group.'}, status=400)
                ban_query &= Q(group=group)
            elif ban_type == 'organizer':
                organizer_id = request.POST.get('organizer_id')
                if not organizer_id:
                    return JsonResponse({'status': 'error', 'message': 'Missing organizer_id for organizer unban.'}, status=400)
                try:
                    organizer_user_for_unban = User.objects.get(id=organizer_id)
                except User.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': 'Organizer not found for unban.'}, status=404)
                ban_query &= Q(organizer=organizer_user_for_unban, group__isnull=True)
            elif ban_type == 'sitewide':
                ban_query &= Q(group__isnull=True, organizer__isnull=True)
            else:
                return JsonResponse({'status': 'error', 'message': 'Unsupported unban type for this action.'}, status=400)

            matching_bans = BannedUser.objects.filter(ban_query)
            if matching_bans.exists():
                matching_bans.delete()
                return JsonResponse({'status': 'success', 'message': f'{target_user.username} unbanned successfully.'})
            else:
                return JsonResponse({'status': 'info', 'message': f'{target_user.username} is not currently banned for the specified type.'})

        return JsonResponse({'status': 'error', 'message': 'Invalid action.'}, status=400)
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
