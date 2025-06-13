from django.shortcuts import render, get_object_or_404, redirect
from .models import Event, RSVP
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from .forms import EventForm, RSVPForm
from users.models import Profile, GroupDelegation, BannedUser
from django.contrib import messages

# Create your views here.

def home(request):
    events = Event.objects.order_by('date')
    return render(request, 'events/home.html', {'events': events})

def event_detail(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    rsvps = event.rsvps.all().select_related('user__profile')
    
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

    if request.method == 'POST' and request.user.is_authenticated:
        # Prevent banned users from RSVPing
        if is_banned_by_organizer or is_banned_from_group:
            messages.error(request, 'You are banned from RSVPing to events by this organizer.', extra_tags='admin_notification')
            return redirect('event_detail', event_id=event.id)

        if 'remove_rsvp' in request.POST and user_rsvp:
            user_rsvp.delete()
            messages.success(request, 'You have removed your RSVP for this event.')
            return redirect('event_detail', event_id=event.id)
        
        if 'delete_event' in request.POST and (event.organizer == request.user or is_site_admin):
            event_title = event.title
            event.delete()
            messages.success(request, f'Event "{event_title}" has been deleted.')
            return redirect('home')
            
        form = RSVPForm(request.POST, instance=user_rsvp)
        if form.is_valid():
            rsvp = form.save(commit=False)
            rsvp.event = event
            rsvp.user = request.user
            rsvp.save()
            messages.success(request, f'Your RSVP status has been updated to {rsvp.get_status_display()}.')
            return redirect('event_detail', event_id=event.id)
    else:
        form = RSVPForm(instance=user_rsvp)

    # Get ban status for each RSVP user
    rsvps_with_ban_status = []
    for rsvp in rsvps:
        is_banned = False
        if event.group:
            is_banned = BannedUser.objects.filter(user=rsvp.user, group=event.group).exists()
        rsvps_with_ban_status.append({
            'rsvp': rsvp,
            'is_banned': is_banned
        })

    # Group RSVPs by status
    rsvp_groups = {
        'attending': [r for r in rsvps_with_ban_status if r['rsvp'].status == 'attending'],
        'maybe': [r for r in rsvps_with_ban_status if r['rsvp'].status == 'maybe'],
        'not_attending': [r for r in rsvps_with_ban_status if r['rsvp'].status == 'not_attending']
    }

    context = {
        'event': event,
        'rsvps': rsvps,
        'rsvp_groups': rsvp_groups,
        'form': form,
        'user_rsvp': user_rsvp,
        'is_organizer': event.organizer == request.user,
        'is_site_admin': is_site_admin,
        'is_delegated_assistant': is_delegated_assistant,
        'can_view_contact_info': event.organizer == request.user or is_site_admin or is_delegated_assistant
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
    is_site_admin = request.user.is_authenticated and request.user.is_superuser
    if not (event.organizer == request.user or is_site_admin):
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