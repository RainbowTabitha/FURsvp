from django.shortcuts import render, get_object_or_404, redirect
from .models import Event, RSVP
from django.utils import timezone
from datetime import timedelta, datetime
from django.contrib.auth.decorators import login_required
from .forms import EventForm, RSVPForm
from users.models import Profile, GroupDelegation, BannedUser, Notification
from django.contrib import messages
from django.db import models, transaction
from django.http import JsonResponse
from users.utils import create_notification

# Create your views here.

def home(request):
    # Get sort parameters from request
    sort_by = request.GET.get('sort', 'date')  # Default sort by date
    sort_order = request.GET.get('order', 'asc')  # Default ascending order
    
    # Base queryset - filter out events that have already passed and cancelled events
    now = timezone.now()
    events = Event.objects.filter(
        models.Q(date__gt=now.date()) | 
        (models.Q(date=now.date()) & models.Q(end_time__gt=now.time())),
        status='active'  # Only show active events
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
    is_organizer_of_this_event = request.user.is_authenticated and event.organizer == request.user

    # Check if user is an approved organizer for this group or a delegated assistant
    can_access_group_contact_info = False
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            if profile.is_approved_organizer and event.group in profile.allowed_groups.all():
                can_access_group_contact_info = True
        except Profile.DoesNotExist:
            pass

        if not can_access_group_contact_info and event.group:
            if GroupDelegation.objects.filter(delegated_user=request.user, group=event.group).exists():
                can_access_group_contact_info = True

    if request.user.is_authenticated:
        user_rsvp = event.rsvps.filter(user=request.user).first()

    can_ban_user = is_organizer_of_this_event or is_site_admin
    can_view_contact_info = is_organizer_of_this_event or is_site_admin or can_access_group_contact_info
    can_cancel_event = is_organizer_of_this_event or is_site_admin

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
            if event.waitlist_enabled:
                can_join_waitlist = True

    if request.method == 'POST' and request.user.is_authenticated and not event_has_passed:
        # Prevent banned users from RSVPing
        if is_banned_by_organizer or is_banned_from_group:
            messages.error(request, 'You are banned from RSVPing to events by this organizer or group.', extra_tags='admin_notification')
            return redirect('event_detail', event_id=event.id)

        if 'cancel_event' in request.POST and can_cancel_event:
            with transaction.atomic():
                event.status = 'cancelled'
                event.save()
                
                # Notify all confirmed and waitlisted attendees
                for rsvp in event.rsvps.filter(status__in=['confirmed', 'waitlisted']):
                    if rsvp.user:
                        create_notification(
                            rsvp.user,
                            f'Event "{event.title}" has been cancelled.',
                            link=event.get_absolute_url()
                        )
                
                messages.success(request, 'Event has been cancelled and all attendees have been notified.', extra_tags='admin_notification')
                return redirect('event_detail', event_id=event.id)

        if 'remove_rsvp' in request.POST:
            if user_rsvp: # Ensure there is an RSVP to remove
                with transaction.atomic():
                    was_confirmed = (user_rsvp.status == 'confirmed')
                    user_rsvp.delete()
                    create_notification(request.user, 'You have removed your RSVP for this event.', link=event.get_absolute_url())

                    # If a confirmed spot opened up and waitlist is enabled, promote oldest waitlisted
                    if was_confirmed and event.waitlist_enabled and event.capacity is not None:
                        # Synchronously promote the oldest waitlisted user
                        oldest_waitlisted_rsvp = event.rsvps.filter(
                            status='waitlisted'
                        ).order_by('timestamp').first()

                        if oldest_waitlisted_rsvp:
                            oldest_waitlisted_rsvp.status = 'confirmed'
                            oldest_waitlisted_rsvp.timestamp = timezone.now()
                            oldest_waitlisted_rsvp.save()
                            create_notification(oldest_waitlisted_rsvp.user, f'You have been moved from the waitlist to confirmed for {event.title}!', link=event.get_absolute_url())
            else:
                messages.error(request, 'You do not have an RSVP to remove.', extra_tags='admin_notification')
            return redirect('event_detail', event_id=event.id)
        
        if 'delete_event' in request.POST and can_ban_user:
            event_title = event.title
            event.delete()
            create_notification(request.user, f'Event "{event_title}" has been deleted.', link='/') # Link to home since event is deleted
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
                create_notification(request.user, 'Your RSVP has been updated.', link=event.get_absolute_url())
            elif new_status == 'confirmed':
                with transaction.atomic():
                    # Re-check counts inside transaction to prevent race conditions
                    current_confirmed_count = event.rsvps.filter(status='confirmed').count()

                    if event.capacity is not None and current_confirmed_count >= event.capacity:
                        # Event is full
                        if event.waitlist_enabled:
                            rsvp = form.save(commit=False)
                            rsvp.status = 'waitlisted' # Force status to waitlisted
                            rsvp.event = event
                            rsvp.user = request.user
                            rsvp.save()
                            create_notification(request.user, "The event is full, but you've been added to the waitlist!", link=event.get_absolute_url())
                        else:
                            messages.error(request, 'The event is full and waitlist is not enabled.', extra_tags='admin_notification')
                            return redirect('event_detail', event_id=event.id)
                    else:
                        # Event has space
                        rsvp = form.save(commit=False)
                        rsvp.status = 'confirmed' # Ensure status is confirmed if there's space
                        rsvp.event = event
                        rsvp.user = request.user
                        rsvp.save()
                        create_notification(request.user, f'Your RSVP status has been updated to {rsvp.get_status_display()!s}.', link=event.get_absolute_url())
                        # If a new confirmed spot was taken, no need to promote here as current user took it.
            else: # If status is 'maybe' or 'not_attending'
                if user_rsvp and user_rsvp.status == 'confirmed': # If changing from confirmed to maybe/not_attending
                    with transaction.atomic():
                        user_rsvp.status = new_status
                        user_rsvp.save()
                        create_notification(request.user, f'Your RSVP status has been updated to {user_rsvp.get_status_display()!s}.', link=event.get_absolute_url())
                        # If a confirmed spot opened up, synchronously promote oldest waitlisted
                        if event.waitlist_enabled and event.capacity is not None:
                            current_confirmed_count_after_change = event.rsvps.filter(status='confirmed').count()
                            if current_confirmed_count_after_change < event.capacity:
                                oldest_waitlisted_rsvp = event.rsvps.filter(
                                    status='waitlisted'
                                ).order_by('timestamp').first()

                                if oldest_waitlisted_rsvp:
                                    oldest_waitlisted_rsvp.status = 'confirmed'
                                    oldest_waitlisted_rsvp.timestamp = timezone.now()
                                    oldest_waitlisted_rsvp.save()
                                    create_notification(oldest_waitlisted_rsvp.user, f'You have been moved from the waitlist to confirmed for {event.title}!', link=event.get_absolute_url())
                else:
                    rsvp = form.save(commit=False)
                    rsvp.event = event
                    rsvp.user = request.user
                    rsvp.save()
                    create_notification(request.user, f'Your RSVP status has been updated to {rsvp.get_status_display()!s}.', link=event.get_absolute_url())
            
            return redirect('event_detail', event_id=event.id)
        else:
            messages.error(request, f'Error updating RSVP: {form.errors}', extra_tags='admin_notification')

    elif 'update_rsvp_status_by_organizer' in request.POST:
        if not can_ban_user: # Use the new flag
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
                create_notification(request.user, message, link=event.get_absolute_url())
                # Send a notification to the user whose RSVP was updated
                if rsvp_to_update.user:
                    create_notification(rsvp_to_update.user, f'Your RSVP for {event.title} has been updated to {rsvp_to_update.get_status_display()}. (by {request.user.username})', link=event.get_absolute_url())

                # If a confirmed spot was freed up and new status is NOT confirmed
                if old_status == 'confirmed' and new_status != 'confirmed':
                    if event.waitlist_enabled and event.capacity is not None:
                        # Synchronously promote the oldest waitlisted user
                        oldest_waitlisted_rsvp = event.rsvps.filter(
                            status='waitlisted'
                        ).order_by('timestamp').first()

                        if oldest_waitlisted_rsvp:
                            oldest_waitlisted_rsvp.status = 'confirmed'
                            oldest_waitlisted_rsvp.timestamp = timezone.now()
                            oldest_waitlisted_rsvp.save()
                            create_notification(oldest_waitlisted_rsvp.user, f'You have been moved from the waitlist to confirmed for {event.title}!', link=event.get_absolute_url())
                
                # If changing from waitlisted to confirmed
                elif old_status == 'waitlisted' and new_status == 'confirmed':
                    pass # Logic already handles the count update by saving

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

    # Construct a well-formatted location string
    location_components = []
    if event.address:
        location_components.append(event.address)
    
    city_state_parts = []
    if event.city:
        city_state_parts.append(event.city)
    if event.state:
        city_state_parts.append(event.state)
    
    if city_state_parts:
        location_components.append(", ".join(city_state_parts))
    
    location_display_string = ", ".join(filter(None, location_components)) # filter(None, ...) removes empty strings

    # Check if user is an organizer or has group access
    # (is_organizer is already calculated above)

    # Determine if the RSVP form should be displayed
    show_rsvp_form = (not is_event_full or can_join_waitlist) or \
                     (user_rsvp is not None and user_rsvp.status != 'confirmed')

    context = {
        'event': event,
        'rsvps': rsvps,
        'form': form,
        'user_rsvp': user_rsvp,
        'is_organizer': is_organizer_of_this_event,
        'is_site_admin': is_site_admin,
        'event_has_passed': event_has_passed,
        'confirmed_rsvps_count': confirmed_rsvps_count,
        'waitlisted_rsvps_count': waitlisted_rsvps_count,
        'is_event_full': is_event_full,
        'can_join_waitlist': can_join_waitlist,
        'can_ban_user': can_ban_user,
        'location_display_string': location_display_string,
        'rsvp_groups': {
            'confirmed': confirmed_rsvps,
            'waitlisted': waitlisted_rsvps,
            'maybe': maybe_rsvps,
            'not_attending': not_attending_rsvps,
        },
        'can_view_contact_info': can_view_contact_info,
        'show_rsvp_form': show_rsvp_form,
        'can_cancel_event': can_cancel_event,
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
    if request.user != event.organizer and not request.user.is_superuser:
        messages.error(request, "You are not authorized to edit this event.")
        return redirect('event_detail', event_id=event.id)

    # Check if user is an approved organizer for this group or a delegated assistant
    is_delegated_assistant = False
    if request.user.is_authenticated and event.group:
        is_delegated_assistant = GroupDelegation.objects.filter(delegated_user=request.user, group=event.group, organizer=event.organizer).exists()
    
    if not request.user.is_superuser and not (request.user.profile.is_approved_organizer and event.group in request.user.profile.allowed_groups.all()) and not is_delegated_assistant:
        messages.error(request, "You are not authorized to edit events for this group.")
        return redirect('event_detail', event_id=event.id)

    if request.method == 'POST':
        form = EventForm(request.POST, instance=event, user=request.user)
        if form.is_valid():
            event = form.save(commit=False)
            # Organizer is set only if it's a new event or being set for the first time.
            # For existing events, it should not change unless specifically handled.
            if not event.organizer:
                event.organizer = request.user
            event.save()
            create_notification(request.user, 'Event updated successfully!', link=event.get_absolute_url())
            return redirect('event_detail', event_id=event.id)
    else:
        form = EventForm(instance=event, user=request.user)
    return render(request, 'events/event_edit.html', {'form': form, 'event': event})

@login_required
def uncancel_event(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if request.user != event.organizer and not request.user.is_superuser:
        messages.error(request, "You are not authorized to uncancel this event.")
        return redirect('event_detail', event_id=event.id)

    if request.method == 'POST':
        with transaction.atomic():
            event.status = 'active'
            event.save()
            
            # Notify all users who had RSVPs
            for rsvp in event.rsvps.all():
                if rsvp.user:
                    create_notification(
                        rsvp.user,
                        f'Event "{event.title}" has been uncancelled.',
                        link=event.get_absolute_url()
                    )
            
            messages.success(request, 'Event has been uncancelled and all attendees have been notified.', extra_tags='admin_notification')
            return redirect('event_detail', event_id=event.id)
    
    return redirect('event_detail', event_id=event.id)

