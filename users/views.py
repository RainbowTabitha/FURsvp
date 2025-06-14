from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from .forms import UserRegisterForm, UserProfileForm, AssistantAssignmentForm, UserPublicProfileForm, UserAdminProfileForm
from events.models import Group
from events.forms import GroupForm, RenameGroupForm
from .models import Profile, GroupDelegation, BannedUser
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q

# Create your views here.

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            if not hasattr(user, 'profile'):
                Profile.objects.create(user=user)
            messages.success(request, f'Your account has been created! You can now log in.', extra_tags='admin_notification')
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

    if request.method == 'POST':
        print("Raw POST data received:", request.POST) # <- NEW DEBUG PRINT
        if 'submit_pfp_changes' in request.POST: # Handle profile picture upload
            base64_image = request.POST.get('profile_picture_base64')
            if base64_image:  # Only update if there's actually an image
                request.user.profile.profile_picture_base64 = base64_image
                request.user.profile.save()
                messages.success(request, 'Profile picture updated successfully!', extra_tags='admin_notification')
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
                    messages.success(request, 'Profile picture removed successfully!', extra_tags='admin_notification')
                
                # Save profile settings
                profile = profile_form.save(commit=False)
                print("Profile before save:", profile.__dict__)  # Debug print
                profile.save()
                print("Profile after save:", profile.__dict__)  # Debug print
                messages.success(request, 'Profile settings updated successfully!', extra_tags='admin_notification')
                return redirect('profile')
            else:
                print("Form errors:", profile_form.errors)  # Debug print
                messages.error(request, f'Error updating profile settings: {profile_form.errors}', extra_tags='admin_notification')
        
        elif 'create_assignment_submit' in request.POST: # Handle creating assistant assignment
            if request.user.profile.is_approved_organizer:
                assistant_assignment_form = AssistantAssignmentForm(request.POST, organizer_profile=request.user.profile)
                if assistant_assignment_form.is_valid():
                    assignment = assistant_assignment_form.save(commit=False)
                    assignment.organizer = request.user
                    try:
                        assignment.save()
                        messages.success(request, f'Assistant {assignment.delegated_user.username} assigned for {assignment.group.name} successfully!', extra_tags='admin_notification')
                        return redirect('profile')
                    except Exception as e:
                        messages.error(request, f'Error creating assistant assignment: {e}', extra_tags='admin_notification')
                else:
                    messages.error(request, f'Error creating assistant assignment: {assistant_assignment_form.errors}', extra_tags='admin_notification')
            else:
                messages.error(request, 'You are not authorized to create assistant assignments.', extra_tags='admin_notification')

        elif 'delete_assignment_submit' in request.POST: # Handle deleting assistant assignment
            if request.user.profile.is_approved_organizer:
                assignment_id = request.POST.get('assignment_id')
                if assignment_id:
                    try:
                        assignment_to_delete = GroupDelegation.objects.get(id=assignment_id, organizer=request.user)
                        delegated_user_name = assignment_to_delete.delegated_user.username
                        group_name = assignment_to_delete.group.name
                        assignment_to_delete.delete()
                        messages.success(request, f'Assistant assignment for {delegated_user_name} to {group_name} deleted successfully!', extra_tags='admin_notification')
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
    }
    return render(request, 'users/profile.html', context)

@require_POST
@csrf_protect
def ban_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Authentication required.'}, status=401)

    try:
        target_user_id = request.POST.get('user_id')
        group_id = request.POST.get('group_id') # Can be None for organizer-wide or sitewide bans
        action = request.POST.get('action') # 'ban' or 'unban'
        reason = request.POST.get('reason', '')
        # New parameter to specify ban type (e.g., 'group', 'organizer', 'sitewide')
        ban_type = request.POST.get('ban_type', 'group') # Default to 'group' for existing frontend

        if not target_user_id or not action:
            return JsonResponse({'status': 'error', 'message': 'Missing parameters.'}, status=400)

        try:
            target_user = User.objects.get(id=target_user_id)
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Target User not found.'}, status=404)

        if action == 'ban' and request.user.id == target_user.id:
            return JsonResponse({'status': 'error', 'message': 'You cannot ban yourself.'}, status=403)

        # Permissions Check
        is_site_admin = request.user.is_superuser
        can_manage_group_ban = False
        can_manage_organizer_ban = False
        can_manage_sitewide_ban = is_site_admin # Only site admins can manage sitewide bans

        group = None
        if group_id: # If a group_id is provided, it's a group-specific action or relates to a specific group
            try:
                group = Group.objects.get(id=group_id)
                # Check if current user is organizer or delegated for this specific group
                user_profile = None
                try:
                    user_profile = request.user.profile
                except Profile.DoesNotExist:
                    pass
                
                is_approved_organizer_for_group = False
                if user_profile and user_profile.is_approved_organizer and group in user_profile.allowed_groups.all():
                    is_approved_organizer_for_group = True

                is_delegated_assistant_for_group = GroupDelegation.objects.filter(
                    delegated_user=request.user,
                    group=group
                ).exists()
                can_manage_group_ban = is_site_admin or is_approved_organizer_for_group or is_delegated_assistant_for_group

            except Group.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Group not found.'}, status=404)

        # Determine overall permission for the requested ban_type
        permission_granted = False
        if ban_type == 'group' and can_manage_group_ban:
            permission_granted = True
        elif ban_type == 'organizer' and is_site_admin: # Organizer-wide bans can only be issued by site admins via this view
            permission_granted = True
        elif ban_type == 'sitewide' and is_site_admin:
            permission_granted = True

        if not permission_granted:
            return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)

        # Determine banned_by and organizer for the new ban entry
        banned_by_user = request.user
        organizer_user = None # Only set if it's an organizer-wide ban
        
        if ban_type == 'organizer':
            # For an organizer-wide ban initiated by a site admin, organizer is the target_user
            organizer_user = target_user # This means target_user is an organizer being banned from organizing for themselves
            # This implies the target_user must be an organizer. This logic needs refinement if organizers can ban other organizers.

        elif ban_type == 'group': # For a group ban, the organizer is implicitly the one who owns the group/delegation
            if is_approved_organizer_for_group:
                organizer_user = request.user
            elif is_delegated_assistant_for_group:
                delegation = GroupDelegation.objects.filter(delegated_user=request.user, group=group).first()
                if delegation:
                    organizer_user = delegation.organizer
            # If site admin, no specific organizer for a group ban, as it's a direct group ban

        # Action: Ban or Unban
        if action == 'ban':
            # Check for existing ban of any type to prevent duplicates/conflicts
            existing_ban = None
            if ban_type == 'group':
                existing_ban = BannedUser.objects.filter(user=target_user, group=group, organizer__isnull=True).first()
            elif ban_type == 'organizer':
                # This is for banning a user from all events by a specific organizer
                # The frontend needs to pass `organizer_id` in this case.
                organizer_id = request.POST.get('organizer_id')
                if not organizer_id:
                    return JsonResponse({'status': 'error', 'message': 'Missing organizer_id for organizer ban.'}, status=400)
                try:
                    organizer_user = User.objects.get(id=organizer_id)
                except User.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': 'Organizer not found.'}, status=404)
                existing_ban = BannedUser.objects.filter(user=target_user, organizer=organizer_user, group__isnull=True).first()
            elif ban_type == 'sitewide':
                existing_ban = BannedUser.objects.filter(user=target_user, organizer__isnull=True, group__isnull=True).first()

            if existing_ban:
                return JsonResponse({'status': 'info', 'message': f'{target_user.username} is already banned.'})

            # Create ban entry based on ban_type
            if ban_type == 'group':
                if not group:
                    return JsonResponse({'status': 'error', 'message': 'Group ID is required for a group ban.'}, status=400)
                BannedUser.objects.create(
                    user=target_user, 
                    group=group, 
                    banned_by=banned_by_user, 
                    reason=reason,
                    organizer=organizer_user
                )
                # Delete RSVPs for this user in this group's events
                from events.models import RSVP
                RSVP.objects.filter(user=target_user, event__group=group).delete()
                return JsonResponse({'status': 'success', 'message': f'{target_user.username} has been banned from {group.name}.'})
            elif ban_type == 'organizer':
                if not organizer_user:
                     return JsonResponse({'status': 'error', 'message': 'Organizer user is required for an organizer ban.'}, status=400)
                BannedUser.objects.create(
                    user=target_user, 
                    organizer=organizer_user, 
                    banned_by=banned_by_user, 
                    reason=reason,
                    group=None # Ensure group is null for organizer ban
                )
                # Delete RSVPs for this user in this organizer's events
                from events.models import RSVP
                RSVP.objects.filter(user=target_user, event__organizer=organizer_user).delete()
                return JsonResponse({'status': 'success', 'message': f'{target_user.username} has been banned from all events by {organizer_user.username}.'})
            elif ban_type == 'sitewide':
                BannedUser.objects.create(
                    user=target_user, 
                    banned_by=banned_by_user, 
                    reason=reason,
                    group=None, # Ensure group is null for sitewide ban
                    organizer=None # Ensure organizer is null for sitewide ban
                )
                # Delete all RSVPs for this user
                from events.models import RSVP
                RSVP.objects.filter(user=target_user).delete()
                return JsonResponse({'status': 'success', 'message': f'{target_user.username} has been banned sitewide.'})
            else:
                return JsonResponse({'status': 'error', 'message': 'Unsupported ban type for this action.'}, status=400)

        elif action == 'unban':
            ban_query = Q(user=target_user)
            if ban_type == 'group':
                if not group:
                    return JsonResponse({'status': 'error', 'message': 'Group ID is required to unban from a group.'}, status=400)
                ban_query &= Q(group=group, organizer__isnull=True)
            elif ban_type == 'organizer':
                organizer_id = request.POST.get('organizer_id')
                if not organizer_id:
                    return JsonResponse({'status': 'error', 'message': 'Missing organizer_id for organizer unban.'}, status=400)
                try:
                    organizer_user = User.objects.get(id=organizer_id)
                except User.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': 'Organizer not found for unban.'}, status=404)
                ban_query &= Q(organizer=organizer_user, group__isnull=True)
            elif ban_type == 'sitewide':
                ban_query &= Q(organizer__isnull=True, group__isnull=True)
            else:
                return JsonResponse({'status': 'error', 'message': 'Unsupported unban type for this action.'}, status=400)
            
            try:
                banned_entry = BannedUser.objects.get(ban_query)
                banned_entry.delete()
                return JsonResponse({'status': 'success', 'message': f'{target_user.username} unbanned successfully.'})
            except BannedUser.DoesNotExist:
                return JsonResponse({'status': 'info', 'message': f'{target_user.username} is not currently banned for the specified type.'})
        
        return JsonResponse({'status': 'error', 'message': 'Invalid action.'}, status=400)
    except Exception as e:
        # Catch any unexpected errors and return a JSON error response
        return JsonResponse({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=500)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def administration(request):
    # Get all users including superusers with pagination
    all_users = User.objects.all().prefetch_related('profile')
    user_paginator = Paginator(all_users, 20)
    user_page = request.GET.get('user_page', 1)
    try:
        users_to_promote = user_paginator.page(user_page)
    except (PageNotAnInteger, EmptyPage):
        users_to_promote = user_paginator.page(1)

    # Get all groups with pagination
    all_groups = Group.objects.all()
    group_paginator = Paginator(all_groups, 20)
    group_page = request.GET.get('group_page', 1)
    try:
        paginated_groups = group_paginator.page(group_page)
    except (PageNotAnInteger, EmptyPage):
        paginated_groups = group_paginator.page(1)

    group_form = GroupForm()
    rename_group_forms = {group.id: RenameGroupForm(instance=group) for group in all_groups}
    user_profile_forms = {user_obj.id: UserAdminProfileForm(instance=user_obj.profile, prefix=f'profile_{user_obj.id}') for user_obj in all_users}
    all_banned_users = BannedUser.objects.all().select_related('user', 'group', 'banned_by', 'organizer').order_by('-banned_at') # Changed 'organizer' to 'organizer'

    if request.method == 'POST':
        if 'promote_users_submit' in request.POST:
            success_count = 0
            error_count = 0
            for user_obj in all_users:
                try:
                    # Load the latest profile instance before processing the form
                    user_obj.profile.refresh_from_db()
                    profile_form = UserAdminProfileForm(request.POST, instance=user_obj.profile, prefix=f'profile_{user_obj.id}')
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
                    messages.success(request, 'Group created successfully!', extra_tags='admin_notification')
                except Exception as e:
                    messages.error(request, f'Error creating group: {str(e)}', extra_tags='admin_notification')
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
                            messages.success(request, f'Group "{group.name}" renamed successfully!', extra_tags='admin_notification')
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
                    messages.success(request, f'Group "{group_name}" deleted successfully!', extra_tags='admin_notification')
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
    }
    return render(request, 'users/administration.html', context)
