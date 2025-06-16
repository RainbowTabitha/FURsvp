from django.shortcuts import render, get_object_or_404, redirect
from .models import Event, RSVP
from django.utils import timezone
from datetime import timedelta, datetime
from django.contrib.auth.decorators import login_required
from .forms import EventForm, RSVPForm
from users.models import Profile, GroupDelegation, BannedUser
from django.contrib import messages
from django.db import models, transaction
from django.http import JsonResponse

# Create your views here.

def home(request):
    # Get sort parameters from request
    sort_by = request.GET.get('sort', 'date')  # Default sort by date
    sort_order = request.GET.get('order', 'asc')  # Default ascending order
    
    # Base queryset - filter out events that have already passed
    now = timezone.now()
    events = Event.objects.filter(
        models.Q(date__gt=now.date()) | 
        (models.Q(date=now.date()) & models.Q(end_time__gt=now.time()))
    ).annotate(
        confirmed_count=models.Count('rsvps', filter=models.Q(rsvps__status='confirmed'))
    )
    
    # Apply sorting
    if sort_by == 'date':
        events = events.order_by('date' if sort_order == 'asc' else '-date')
    elif sort_by == 'group':
        events = events.order_by(models.functions.Lower('group__name') if sort_order == 'asc' else models.functions.Lower('group__name').desc())
    elif sort_by == 'title':
        events = events.order_by(models.functions.Lower('title') if sort_order == 'asc' else models.functions.Lower('title').desc())
    elif sort_by == 'rsvps':
        events = events.annotate(rsvp_count=models.Count('rsvps')).order_by(
            'rsvp_count' if sort_order == 'asc' else '-rsvp_count'
        )
    
    context = {
        'events': events,
        'current_sort': sort_by,
        'current_order': sort_order,
    }
    return render(request, 'events/home.html', context)

def event_detail(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    rsvps = event.rsvps.all().select_related('user__profile')
    
    # Calculate if event has passed
    event_end_datetime = datetime.combine(event.date, event.end_time)
    # Make event_end_datetime timezone-aware if USE_TZ is True in settings
    if timezone.is_aware(timezone.now()):
        event_end_datetime = timezone.make_aware(event_end_datetime, timezone.get_current_timezone())

    event_has_passed = timezone.now() > event_end_datetime

    # Get user's RSVP if they're logged in
    user_rsvp = None
    is_site_admin = request.user.is_authenticated and request.user.is_superuser
    is_delegated_assistant = False
    if request.user.is_authenticated:
        user_rsvp = event.rsvps.filter(user=request.user).first()
        
        # Check if user is a delegated assistant for this event's group
        if event.group:
            is_delegated_assistant = GroupDelegation.objects.filter(
                organizer=event.organizer, 
                delegated_user=request.user, 
                group=event.group
            ).exists()
    
    # Check if the user is banned by this event's organizer (for any group)
    is_banned_by_organizer = False
    if request.user.is_authenticated and event.organizer:
        is_banned_by_organizer = BannedUser.objects.filter(user=request.user, organizer=event.organizer).exists()

    # Check if the user is banned from this specific group
    is_banned_from_group = False
    if request.user.is_authenticated and event.group:
        is_banned_from_group = BannedUser.objects.filter(user=request.user, group=event.group).exists()

    # Calculate confirmed RSVPs and waitlisted RSVPs
    confirmed_rsvps_count = event.rsvps.filter(status='confirmed').count()
    waitlisted_rsvps_count = event.rsvps.filter(status='waitlisted').count()

    is_event_full = False
    can_join_waitlist = False
    if event.capacity is not None:
        if confirmed_rsvps_count >= event.capacity:
            is_event_full = True
            if event.waitlist_enabled and event.capacity is not None:
                can_join_waitlist = True

    if request.method == 'POST' and request.user.is_authenticated and not event_has_passed:
        # Prevent banned users from RSVPing
        if is_banned_by_organizer or is_banned_from_group:
            messages.error(request, 'You are banned from RSVPing to events by this organizer or group.', extra_tags='admin_notification')
            return redirect('event_detail', event_id=event.id)

        if 'remove_rsvp' in request.POST:
            if user_rsvp: # Ensure there is an RSVP to remove
                with transaction.atomic():
                    was_confirmed = (user_rsvp.status == 'confirmed')
                    user_rsvp.delete()
                    messages.success(request, 'You have removed your RSVP for this event.')

                    # If a confirmed spot opened up and waitlist is enabled, promote oldest waitlisted
                    if was_confirmed and event.waitlist_enabled and event.capacity is not None:
                        waitlisted_users = event.rsvps.filter(status='waitlisted').order_by('timestamp')
                        if waitlisted_users.exists():
                            promoted_rsvp = waitlisted_users.first()
                            promoted_rsvp.status = 'confirmed'
                            promoted_rsvp.save()
                            messages.info(request, f'{promoted_rsvp.user.username} has been moved from the waitlist to confirmed!', extra_tags='admin_notification')
            else:
                messages.error(request, 'You do not have an RSVP to remove.', extra_tags='admin_notification')
            return redirect('event_detail', event_id=event.id)
        
        if 'delete_event' in request.POST and (event.organizer == request.user or is_site_admin or is_delegated_assistant):
            event_title = event.title
            event.delete()
            messages.success(request, f'Event "{event_title}" has been deleted.')
            return redirect('home')
            
        form = RSVPForm(request.POST, instance=user_rsvp, event=event)
        if form.is_valid():
            new_status = form.cleaned_data['status']

            # If user is already confirmed and tries to RSVP again, just update other fields.
            # If changing from waitlisted to maybe/not_attending, no capacity check needed.
            if user_rsvp and user_rsvp.status == 'confirmed' and new_status == 'confirmed':
                rsvp = form.save(commit=False)
                rsvp.event = event
                rsvp.user = request.user
                rsvp.save()
                messages.success(request, 'Your RSVP has been updated.')
            elif new_status == 'confirmed':
                with transaction.atomic():
                    # Re-check counts inside transaction to prevent race conditions
                    current_confirmed_count = event.rsvps.filter(status='confirmed').count()

                    if event.capacity is not None and current_confirmed_count >= event.capacity:
                        if event.waitlist_enabled and event.capacity is not None:
                            rsvp = form.save(commit=False)
                            rsvp.status = 'waitlisted' # Force status to waitlisted
                            rsvp.event = event
                            rsvp.user = request.user
                            rsvp.save()
                            messages.info(request, "The event is full, but you've been added to the waitlist!", extra_tags='admin_notification')
                        else:
                            messages.error(request, 'The event is full and waitlist is not enabled.', extra_tags='admin_notification')
                            return redirect('event_detail', event_id=event.id)
                    else:
                        rsvp = form.save(commit=False)
                        rsvp.status = 'confirmed' # Ensure status is confirmed if there's space
                        rsvp.event = event
                        rsvp.user = request.user
                        rsvp.save()
                        messages.success(request, f'Your RSVP status has been updated to {rsvp.get_status_display()}.')
            else: # If status is 'maybe' or 'not_attending'
                if user_rsvp and user_rsvp.status == 'confirmed': # If changing from confirmed to maybe/not_attending
                    with transaction.atomic():
                        user_rsvp.status = new_status
                        user_rsvp.save()
                        messages.success(request, f'Your RSVP status has been updated to {user_rsvp.get_status_display()}.')
                        # If a confirmed spot opened up, promote oldest waitlisted
                        if event.waitlist_enabled and event.capacity is not None:
                            waitlisted_users = event.rsvps.filter(status='waitlisted').order_by('timestamp')
                            if waitlisted_users.exists():
                                promoted_rsvp = waitlisted_users.first()
                                promoted_rsvp.status = 'confirmed'
                                promoted_rsvp.save()
                                messages.info(request, f'{promoted_rsvp.user.username} has been moved from the waitlist to confirmed!', extra_tags='admin_notification')
                else: # If not currently confirmed, or creating a new maybe/not_attending RSVP
                    rsvp = form.save(commit=False)
                    rsvp.event = event
                    rsvp.user = request.user
                    rsvp.save()
                    messages.success(request, f'Your RSVP status has been updated to {rsvp.get_status_display()}.')
            
            return redirect('event_detail', event_id=event.id)
        else:
            messages.error(request, f'Error updating RSVP: {form.errors}', extra_tags='admin_notification')

    elif 'update_rsvp_status_by_organizer' in request.POST:
        if not (event.organizer == request.user or is_site_admin or is_delegated_assistant):
            return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)
        
        rsvp_id = request.POST.get('rsvp_id')
        new_status = request.POST.get('new_status')

        response_data = {}
        status_code = 200

        try:
            rsvp_to_update = event.rsvps.get(id=rsvp_id)
            
            with transaction.atomic():
                old_status = rsvp_to_update.status
                rsvp_to_update.status = new_status
                rsvp_to_update.save()

                message = f"{rsvp_to_update.user.username}'s RSVP updated to {rsvp_to_update.get_status_display()}."

                # If a confirmed spot was freed up and new status is NOT confirmed
                if old_status == 'confirmed' and new_status != 'confirmed':
                    if event.waitlist_enabled and event.capacity is not None:
                        waitlisted_users = event.rsvps.filter(status='waitlisted').order_by('timestamp')
                        if waitlisted_users.exists():
                            promoted_rsvp = waitlisted_users.first()
                            promoted_rsvp.status = 'confirmed'
                            promoted_rsvp.save()
                            message += f' {promoted_rsvp.user.username} has been moved from the waitlist to confirmed!';
                
                # If changing from waitlisted to confirmed
                elif old_status == 'waitlisted' and new_status == 'confirmed':
                    pass # Logic already handles the count update by saving

                messages.success(request, message, extra_tags='admin_notification')
                response_data = {'status': 'success', 'message': message}
                status_code = 200

        except RSVP.DoesNotExist:
            response_data = {'status': 'error', 'message': 'RSVP not found.'}
            status_code = 404
        except Exception as e:
            response_data = {'status': 'error', 'message': f'An error occurred: {str(e)}'}
            status_code = 500
        
        return JsonResponse(response_data, status=status_code)

    else:
        form = RSVPForm(instance=user_rsvp, event=event)

    # Get ban status for each RSVP user (for initial rendering)
    # And filter by status for display
    all_rsvps_data = []
    # Use prefetch_related for user__profile to reduce queries
    rsvps_queryset = event.rsvps.all().select_related('user__profile').order_by('timestamp')

    for rsvp in rsvps_queryset:
        is_banned = False
        # Check for group ban first
        if event.group:
            is_banned = BannedUser.objects.filter(user=rsvp.user, group=event.group).exists()
        # If not group banned, check for organizer ban (if event has an organizer)
        if not is_banned and event.organizer:
            is_banned = BannedUser.objects.filter(user=rsvp.user, organizer=event.organizer).exists()
        # If not group or organizer banned, check for site-wide ban
        if not is_banned:
            is_banned = BannedUser.objects.filter(user=rsvp.user, group__isnull=True, organizer__isnull=True).exists()

        all_rsvps_data.append({'rsvp': rsvp, 'is_banned': is_banned})

    # Group RSVPs by status for template display
    confirmed_rsvps = [r for r in all_rsvps_data if r['rsvp'].status == 'confirmed']
    waitlisted_rsvps = [r for r in all_rsvps_data if r['rsvp'].status == 'waitlisted']
    maybe_rsvps = [r for r in all_rsvps_data if r['rsvp'].status == 'maybe']
    not_attending_rsvps = [r for r in all_rsvps_data if r['rsvp'].status == 'not_attending']

    # Check if user is an organizer or has group access
    is_organizer = False
    if request.user.is_authenticated:
        # Check if user is an approved organizer for this group
        try:
            profile = request.user.profile
            if profile.is_approved_organizer and event.group in profile.allowed_groups.all():
                is_organizer = True
        except Profile.DoesNotExist:
            pass

        # Check if user has access to the group through delegation
        if not is_organizer and event.group:
            is_organizer = GroupDelegation.objects.filter(
                delegated_user=request.user,
                group=event.group
            ).exists()

    context = {
        'event': event,
        'rsvps': rsvps,
        'form': form,
        'user_rsvp': user_rsvp,
        'is_organizer': is_organizer,
        'is_site_admin': is_site_admin,
        'is_delegated_assistant': is_delegated_assistant,
        'can_view_contact_info': True,
        'event_has_passed': event_has_passed,
        'confirmed_rsvps_count': confirmed_rsvps_count,
        'waitlisted_rsvps_count': waitlisted_rsvps_count,
        'is_event_full': is_event_full,
        'can_join_waitlist': can_join_waitlist,
        'rsvp_groups': {
            'confirmed': confirmed_rsvps,
            'waitlisted': waitlisted_rsvps,
            'maybe': maybe_rsvps,
            'not_attending': not_attending_rsvps,
        }
    }
    return render(request, 'events/event_detail.html', context)

@login_required
def create_event(request):
    # Check if user is an approved organizer, an assistant, or an admin
    is_approved_organizer = False
    is_assistant = False
    
    # Admins can always create events
    if request.user.is_superuser:
        is_approved_organizer = True
    else:
        try:
            profile = request.user.profile
            is_approved_organizer = profile.is_approved_organizer
        except Profile.DoesNotExist:
            pass
        
        is_assistant = GroupDelegation.objects.filter(delegated_user=request.user).exists()

    if not (is_approved_organizer or is_assistant):
        return redirect('pending_approval')

    if request.method == 'POST':
        form = EventForm(request.POST, user=request.user)
        if form.is_valid():
            event = form.save(commit=False)
            event.organizer = request.user
            event.save()
            return redirect('event_detail', event_id=event.id)
    else:
        form = EventForm(user=request.user)
    return render(request, 'events/event_create.html', {'form': form})

@login_required
def edit_event(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    
    # Check permissions
    is_site_admin = request.user.is_superuser
    is_event_owner = (event.organizer == request.user)
    is_organizer_for_group = False
    is_delegated_assistant = False

    # Check if user is an approved organizer for this group
    try:
        profile = request.user.profile
        if profile.is_approved_organizer and event.group in profile.allowed_groups.all():
            is_organizer_for_group = True
    except Profile.DoesNotExist:
        pass
    
    # Check if user has access to the group through delegation
    if not is_organizer_for_group and event.group:
        is_delegated_assistant = GroupDelegation.objects.filter(
            delegated_user=request.user,
            group=event.group
        ).exists()
    
    if not (is_site_admin or is_event_owner or is_organizer_for_group or is_delegated_assistant):
        messages.error(request, 'You do not have permission to edit this event.')
        return redirect('event_detail', event_id=event.id)

    if request.method == 'POST':
        form = EventForm(request.POST, instance=event, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Event updated successfully!')
            return redirect('event_detail', event_id=event.id)
    else:
        form = EventForm(instance=event, user=request.user)
    return render(request, 'events/event_edit.html', {'form': form, 'event': event})

