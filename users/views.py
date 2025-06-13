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
@login_required
def ban_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Authentication required.'}, status=401)

    target_user_id = request.POST.get('user_id')
    group_id = request.POST.get('group_id')
    action = request.POST.get('action') # 'ban' or 'unban'
    reason = request.POST.get('reason', '')

    if not target_user_id or not group_id or not action:
        return JsonResponse({'status': 'error', 'message': 'Missing parameters.'}, status=400)

    try:
        target_user = User.objects.get(id=target_user_id)
        group = Group.objects.get(id=group_id)
    except (User.DoesNotExist, Group.DoesNotExist):
        return JsonResponse({'status': 'error', 'message': 'User or Group not found.'}, status=404)

    # Check for permissions (same as can_view_contact_info logic from event_detail)
    is_site_admin = request.user.is_superuser
    is_event_organizer_for_group = (request.user == group.event_set.first().organizer if group.event_set.first() else False)
    is_delegated_assistant = GroupDelegation.objects.filter(
        organizer=group.event_set.first().organizer if group.event_set.first() else None, 
        delegated_user=request.user, 
        group=group
    ).exists()
    
    can_manage_bans = is_site_admin or is_event_organizer_for_group or is_delegated_assistant

    if not can_manage_bans:
        return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)

    # Determine the organizer for the ban
    ban_organizer = None
    if is_site_admin:
        ban_organizer = request.user
    elif is_event_organizer_for_group:
        ban_organizer = group.event_set.first().organizer
    elif is_delegated_assistant:
        ban_organizer = GroupDelegation.objects.get(delegated_user=request.user, group=group).organizer

    if action == 'ban':
        if BannedUser.objects.filter(user=target_user, group=group).exists():
            return JsonResponse({'status': 'info', 'message': f'{target_user.username} is already banned from {group.name}.'})
        
        # Remove existing RSVPs for the banned user in this group's events
        target_user.rsvp_set.filter(event__group=group).delete()

        BannedUser.objects.create(user=target_user, group=group, banned_by=request.user, organizer=ban_organizer, reason=reason)
        messages.success(request, f'{target_user.username} has been banned from {group.name}.', extra_tags='admin_notification')
        return JsonResponse({'status': 'success', 'message': f'{target_user.username} banned successfully.'})
    
    elif action == 'unban':
        try:
            banned_entry = BannedUser.objects.get(user=target_user, group=group)
            banned_entry.delete()
            messages.success(request, f'{target_user.username} has been unbanned from {group.name}.', extra_tags='admin_notification')
            return JsonResponse({'status': 'success', 'message': f'{target_user.username} unbanned successfully.'})
        except BannedUser.DoesNotExist:
            return JsonResponse({'status': 'info', 'message': f'{target_user.username} is not currently banned from {group.name}.'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid action.'}, status=400)

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
    all_banned_users = BannedUser.objects.all().select_related('user', 'group', 'banned_by', 'organizer').order_by('-banned_at')

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
