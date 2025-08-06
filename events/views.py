from django.shortcuts import render, get_object_or_404, redirect
from .models import Event, RSVP, Post, Group
from django.utils import timezone
from datetime import timedelta, datetime
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from .forms import EventForm, RSVPForm, Group
from users.models import Profile, GroupDelegation, BannedUser, Notification, GroupRole, AuditLog
from django.contrib import messages
from django.db import models, transaction
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from users.utils import create_notification
import feedparser
from django.views.generic import ListView, DetailView
import pytz
import time
from events.forms import GroupRoleForm
from django.db.models import Q
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
import calendar
from django.forms.utils import ErrorList
from events.utils import post_to_telegram_channel
from django.urls import reverse
import os
import json
import requests
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET
from django.contrib.auth.models import User
from .models import PlatformStats
from django.core.mail import send_mail
from django.conf import settings


# Create your views here.

def get_telegram_feed(channel='', limit=5):
    url = f"https://rss.tabithahanegan.com/telegram/channel/{channel}"
    if url == "https://rss.tabithahanegan.com/telegram/channel/None":
        url = ""
    feed = feedparser.parse(url)
    entries = feed.entries[:limit]
    eastern = pytz.timezone('America/New_York')
    for entry in entries:
        # Try published_parsed first
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            dt_utc = datetime.fromtimestamp(time.mktime(entry.published_parsed), pytz.utc)
            entry.est_datetime = dt_utc.astimezone(eastern)
        # Fallback: try published (RFC822 string)
        elif hasattr(entry, 'published') and entry.published:
            try:
                dt_utc = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %Z')
                dt_utc = pytz.utc.localize(dt_utc)
                entry.est_datetime = dt_utc.astimezone(eastern)
            except Exception:
                entry.est_datetime = None
        else:
            entry.est_datetime = None
    return entries

def get_bluesky_feed(profile='fursvp.org', limit=10):
    url = f"https://rss.tabithahanegan.com/bsky/profile/{profile}"
    feed = feedparser.parse(url)
    entries = feed.entries[:limit]
    eastern = pytz.timezone('America/New_York')
    for entry in entries:
        # Try published_parsed first
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            dt_utc = datetime.fromtimestamp(time.mktime(entry.published_parsed), pytz.utc)
            entry.est_datetime = dt_utc.astimezone(eastern)
        elif hasattr(entry, 'published') and entry.published:
            try:
                dt_utc = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %Z')
                dt_utc = pytz.utc.localize(dt_utc)
                entry.est_datetime = dt_utc.astimezone(eastern)
            except Exception:
                entry.est_datetime = None
        else:
            entry.est_datetime = None
    return entries


def home(request):
    # Get sort parameters from request
    sort_by = request.GET.get('sort', 'date')  # Default sort by date
    sort_order = request.GET.get('order', 'asc')  # Default ascending order
    filter_adult = request.GET.get('adult', 'true') # Default to show adult events
    view_type = request.GET.get('view', 'list')  # Default to list view
    page = request.GET.get('page', 1)  # Default to first page
    
    # Get year and month for calendar vieww
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    search_query = request.GET.get('search', '').strip()
    state_filter = request.GET.get('state', '').strip()
    
    # Base queryset - filter out events that have already passed and cancelled events
    now = timezone.now()
    
    # Only show events that the user has RSVP'd to
    if request.user.is_authenticated:
        events = Event.objects.filter(
            models.Q(date__gt=now.date()) | 
            (models.Q(date=now.date()) & models.Q(end_time__gt=now.time())),
            status='active',  # Only show active events
            rsvps__user=request.user  # Only events user has RSVP'd to
        ).distinct()
    else:
        # If not authenticated, show no events
        events = Event.objects.none()

    if filter_adult == 'false':
        events = events.exclude(age_restriction__in=['adult', 'mature'])

    # Apply search filter
    if search_query:
        events = events.filter(
            models.Q(title__icontains=search_query) |
            models.Q(description__icontains=search_query) |
            models.Q(city__icontains=search_query) |
            models.Q(group__name__icontains=search_query)
        )

    # Apply state filter
    if state_filter:
        events = events.filter(state__iexact=state_filter)

    events = events.annotate(
        confirmed_count=models.Count('rsvps', filter=models.Q(rsvps__status='confirmed'))
    )
    
    # Add user's RSVP information if user is authenticated
    if request.user.is_authenticated:
        events = events.annotate(
            user_rsvp_status=models.Subquery(
                RSVP.objects.filter(
                    event=models.OuterRef('pk'),
                    user=request.user
                ).values('status')[:1]
            )
        )
        
        # Add user's RSVP list for template compatibility
        for event in events:
            user_rsvp = event.rsvps.filter(user=request.user).first()
            if user_rsvp:
                event.user_rsvp_list = [user_rsvp]
            else:
                event.user_rsvp_list = []
    
    # Apply sorting
    if sort_by == 'date':
        events = events.order_by('date', 'start_time') if sort_order == 'asc' else events.order_by('-date', '-start_time')
    elif sort_by == 'group':
        events = events.order_by(models.functions.Lower('group__name') if sort_order == 'asc' else models.functions.Lower('group__name').desc())
    elif sort_by == 'title':
        events = events.order_by(models.functions.Lower('title') if sort_order == 'asc' else models.functions.Lower('title').desc())
    elif sort_by == 'rsvps':
        events = events.annotate(rsvp_count=models.Count('rsvps')).order_by(
            'rsvp_count' if sort_order == 'asc' else '-rsvp_count'
        )
    
    # Pagination
    paginator = Paginator(events, 12)  # Show 12 events per page
    try:
        events_page = paginator.page(page)
    except PageNotAnInteger:
        events_page = paginator.page(1)
    except EmptyPage:
        events_page = paginator.page(paginator.num_pages)
    
    # Add user's RSVP information if user is authenticated (AFTER pagination)
    if request.user.is_authenticated:
        # Add user's RSVP list for template compatibility
        for event in events_page:
            # Clean HTML content for event descriptions
            if event.description:
                event.description = clean_html_content(event.description)
            
            user_rsvp = event.rsvps.filter(user=request.user).first()
            if user_rsvp:
                event.user_rsvp_list = [user_rsvp]
            else:
                event.user_rsvp_list = []
    
    # Calendar data
    if view_type == 'calendar':
        # Set first weekday to Sunday
        calendar.setfirstweekday(calendar.SUNDAY)
        # Create calendar object
        cal = calendar.monthcalendar(year, month)
        month_name = calendar.month_name[month]
        
        # Get events for this month
        start_date = datetime(year, month, 1).date()
        if month == 12:
            end_date = datetime(year + 1, 1, 1).date()
        else:
            end_date = datetime(year, month + 1, 1).date()
        
        month_events = events.filter(
            date__gte=start_date,
            date__lt=end_date
        ).order_by('date', 'start_time')
        
        # Group events by date
        events_by_date = {}
        for event in month_events:
            date_key = event.date.strftime('%Y-%m-%d')
            if date_key not in events_by_date:
                events_by_date[date_key] = []
            events_by_date[date_key].append(event)
        
        # Navigation
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        
        eastern = pytz.timezone('America/New_York')
        today = timezone.now().astimezone(eastern).date()
        calendar_data = {
            'calendar': cal,
            'month_name': month_name,
            'year': year,
            'month': month,
            'events_by_date': events_by_date,
            'prev_month': prev_month,
            'prev_year': prev_year,
            'next_month': next_month,
            'next_year': next_year,
            'today': today,
        }
    else:
        calendar_data = None
    
    # Get all unique states for the dropdown
    all_states = Event.objects.exclude(state__isnull=True).exclude(state__exact='').values_list('state', flat=True).distinct().order_by('state')

    # Get cumulative stats that always increase
    stats = PlatformStats.get_or_create_stats()
    
    # Active events (current and future)
    active_events = Event.objects.filter(
        models.Q(date__gte=now.date()) | 
        (models.Q(date=now.date()) & models.Q(end_time__gt=now.time())),
        status='active'
    ).count()
    
    context = {
        'events': events_page,
        'current_sort': sort_by,
        'current_order': sort_order,
        'filter_adult': filter_adult,
        'view_type': view_type,
        'calendar_data': calendar_data,
        'paginator': paginator,
        'page_obj': events_page,
        'today': timezone.now().date(),
        'all_states': all_states,
        'events_count': stats.total_events_created,
        'groups_count': stats.total_groups_created,
        'users_count': stats.total_users_registered,
        'rsvps_count': stats.total_rsvps_created,
        'active_events_count': active_events,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # If it's an AJAX request, only return the partial event list HTML
        return render(request, 'events/events_list_partial.html', context)
    
    # For regular requests, render the full page
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
            if GroupRole.objects.filter(user=profile.user, group=event.group).exists():
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

    def promote_waitlisted_if_spot(event):
        if event.waitlist_enabled and event.capacity is not None:
            current_confirmed_count = event.rsvps.filter(status='confirmed').count()
            if current_confirmed_count < event.capacity:
                oldest_waitlisted_rsvp = event.rsvps.filter(
                    status='waitlisted'
                ).order_by('timestamp').first()
                if oldest_waitlisted_rsvp:
                    oldest_waitlisted_rsvp.status = 'confirmed'
                    oldest_waitlisted_rsvp.timestamp = timezone.now()
                    oldest_waitlisted_rsvp.save()
                    if oldest_waitlisted_rsvp.user:
                        create_notification(
                            oldest_waitlisted_rsvp.user,
                            f'You have been moved from the waitlist to confirmed for {event.title}!',
                            link=event.get_absolute_url()
                        )

    if request.method == 'POST':
        if not request.user.is_authenticated:
            messages.error(request, 'You must be logged in to RSVP.')
            return redirect('login')
            
        # Handle event cancellation
        if 'cancel_event' in request.POST:
            if not can_cancel_event:
                messages.error(request, 'You are not authorized to cancel this event.')
                return redirect('event_detail', event_id=event.id)
            
            event.status = 'cancelled'
            event.save()
            
            # Notify all attendees
            for rsvp in event.rsvps.all():
                if rsvp.user:
                    create_notification(
                        rsvp.user,
                        f'The event "{event.title}" has been cancelled.',
                        link=event.get_absolute_url()
                    )
            
            messages.success(request, 'Event has been cancelled and all attendees have been notified.')
            return redirect('event_detail', event_id=event.id)
            
        # Handle event deletion
        if 'delete_event' in request.POST:
            if not can_cancel_event:  # Use same permission as cancel
                messages.error(request, 'You are not authorized to delete this event.')
                return redirect('event_detail', event_id=event.id)
            
            # Store event info for logging before deletion
            event_title = event.title
            event_group = event.group.name if event.group else None
            event_group_obj = event.group  # Store the group object
            
            # Delete the event
            event.delete()
            
            # Log the deletion
            AuditLog.log_action(
                user=request.user,
                action='event_deleted',
                description=f'Deleted event: {event_title}',
                group=event_group_obj,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                additional_data={
                    'event_title': event_title,
                    'event_group': event_group,
                    'deleted_by': request.user.username
                }
            )
            
            messages.success(request, 'Event has been deleted successfully.')
            return redirect('home')
            
        if event.status == 'cancelled':
            messages.error(request, 'This event has been cancelled.')
            return redirect('home')
            
        form = RSVPForm(request.POST, instance=user_rsvp, event=event)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            rsvp = form.save(commit=False)
            rsvp.event = event
            rsvp.user = request.user
            rsvp.save()
            
            create_notification(request.user, f'Your RSVP status has been updated to {rsvp.get_status_display()!s} for {event.title}.', link=event.get_absolute_url())
            # Telegram webhook for public RSVP (any status)
            if event.attendee_list_public and event.group and getattr(event.group, 'telegram_webhook_channel', None):
                telegram_username = None
                if hasattr(request.user, 'profile') and getattr(request.user.profile, 'telegram_username', None):
                    telegram_username = request.user.profile.telegram_username
                if telegram_username:
                    mention = f'@{telegram_username}'
                else:
                    mention = request.user.get_username() if request.user else 'Someone'
                date_str = event.date.strftime('%m/%d/%Y') if hasattr(event.date, 'strftime') else str(event.date)
                event_url = request.build_absolute_uri(event.get_absolute_url())
                status_emoji = {
                    'confirmed': '✅',
                    'waitlisted': '⏳',
                    'maybe': '❔',
                    'not_attending': '🚫'
                }.get(new_status, '')
                msg = (
                    f'{status_emoji} {mention} RSVP\'d as *{rsvp.get_status_display()}* for [{event.title}]({event_url}).\n'
                    f'*Date:* {date_str}\n'
                    f'*Group:* {event.group.name}'
                )
                post_to_telegram_channel(event.group.telegram_webhook_channel, msg, parse_mode="Markdown")
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

                # Log the organizer RSVP status change
                AuditLog.log_action(
                    user=request.user,
                    action='rsvp_status_changed',
                    description=f'Changed {rsvp_to_update.user.username}\'s RSVP status from {old_status} to {new_status} for {event.title}',
                    group=event.group,
                    event=event,
                    target_user=rsvp_to_update.user,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    additional_data={
                        'old_status': old_status,
                        'new_status': new_status,
                        'rsvp_id': rsvp_to_update.id,
                        'changed_by': request.user.username
                    }
                )

                message = f"{rsvp_to_update.user.username}'s RSVP for {event.title} updated to {rsvp_to_update.get_status_display()}."
                create_notification(request.user, message, link=event.get_absolute_url())
                # Send a notification to the user whose RSVP was updated
                if rsvp_to_update.user:
                    create_notification(rsvp_to_update.user, f'Your RSVP for {event.title} has been updated to {rsvp_to_update.get_status_display()}. (by {request.user.username})', link=event.get_absolute_url())

                # If a confirmed spot was freed up and new status is NOT confirmed
                if old_status == 'confirmed' and new_status != 'confirmed':
                    if event.waitlist_enabled and event.capacity is not None:
                        # Synchronously promote the oldest waitlisted user
                        promote_waitlisted_if_spot(event)
                
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
        # Always use instance=user_rsvp for the RSVP form if user_rsvp exists
        form = RSVPForm(instance=user_rsvp, event=event)
    
    # Add EventForm for the edit event modal
    event_form = None
    edit_event_errors = None
    edit_event_post = None
    if request.user.is_authenticated:
        # Check for edit errors in session (from failed edit_event POST)
        edit_event_errors = request.session.pop('edit_event_errors', None)
        edit_event_post = request.session.pop('edit_event_post', None)
        if edit_event_post:
            event_form = EventForm(edit_event_post, instance=event, user=request.user)
            # Manually assign errors to the form, converting lists back to ErrorList
            if edit_event_errors:
                event_form._errors = {}
                for k, v in edit_event_errors.items():
                    event_form._errors[k] = ErrorList(v)
        else:
            event_form = EventForm(instance=event, user=request.user)

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
    
    # Do NOT include county in location_components
    location_display_string = ", ".join(filter(None, location_components)) # filter(None, ...) removes empty strings

    # Check if user is an organizer or has group access
    # (is_organizer is already calculated above)

    # Determine if the RSVP form should be displayed
    show_rsvp_form = (not is_event_full or can_join_waitlist) or \
                     (user_rsvp is not None and user_rsvp.status != 'confirmed')

    # Determine attendee list visibility
    can_view_attendee_list = (
        event.attendee_list_public or
        is_organizer_of_this_event or
        is_site_admin or
        can_access_group_contact_info
    )

    # If attendee list is hidden, but user has an RSVP, only show their RSVP in the list
    if not can_view_attendee_list and user_rsvp:
        def only_user_rsvp(group, status):
            if user_rsvp.status == status:
                return [{'rsvp': user_rsvp, 'is_banned': False}]
            return []
        confirmed_rsvps = only_user_rsvp(confirmed_rsvps, 'confirmed')
        waitlisted_rsvps = only_user_rsvp(waitlisted_rsvps, 'waitlisted')
        maybe_rsvps = only_user_rsvp(maybe_rsvps, 'maybe')
        not_attending_rsvps = only_user_rsvp(not_attending_rsvps, 'not_attending')
    elif not can_view_attendee_list and not user_rsvp:
        confirmed_rsvps = []
        waitlisted_rsvps = []
        maybe_rsvps = []
        not_attending_rsvps = []

    # Pre-load avatar data for all users to avoid individual HTTP requests
    def get_avatar_data(profile):
        if profile.profile_picture_base64:
            return {
                'has_pfp': True,
                'avatar': profile.profile_picture_base64,
                'initials': None,
                'color': None
            }
        else:
            return {
                'has_pfp': False,
                'avatar': None,
                'initials': profile.get_initials(),
                'color': profile.get_avatar_color()
            }
    
    # Add avatar data to all users in the context
    avatar_data = {}
    for rsvp in rsvps:
        if rsvp.user and rsvp.user.profile:
            avatar_data[rsvp.user.id] = get_avatar_data(rsvp.user.profile)

    context = {
        'event': event,
        'rsvps': rsvps,
        'form': form,
        'event_form': event_form,
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
        'can_view_attendee_list': can_view_attendee_list,
        'edit_event_errors': edit_event_errors,
        'edit_event_post': edit_event_post,
        'avatar_data': avatar_data,  # Add avatar data to context
    }
    return render(request, 'events/event_detail.html', context)

@login_required
def create_event(request):
    # Check if user is a group leader, an assistant, or an admin
    is_leader = GroupRole.objects.filter(user=request.user).exists()
    is_assistant = GroupDelegation.objects.filter(delegated_user=request.user).exists()
    
    # Admins can always create events
    if not (request.user.is_superuser or is_leader or is_assistant):
        return redirect('pending_approval')

    if request.method == 'POST':
        form = EventForm(request.POST, user=request.user)
        if form.is_valid():
            event = form.save(commit=False)
            event.organizer = request.user
            event.save()
            
            # Log the event creation
            AuditLog.log_action(
                user=request.user,
                action='event_created',
                description=f'Created new event: {event.title}',
                group=event.group,
                event=event,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                additional_data={
                    'event_title': event.title,
                    'event_date': event.date.isoformat(),
                    'event_group': event.group.name,
                    'event_capacity': event.capacity,
                    'event_status': event.status
                }
            )
            
            # Telegram webhook for new event
            group = event.group
            if group and getattr(group, 'telegram_webhook_channel', None):
                date_str = event.date.strftime('%m/%d/%Y') if hasattr(event.date, 'strftime') else str(event.date)
                event_url = request.build_absolute_uri(event.get_absolute_url())
                msg = (
                    "🎉 *New Event Created!*\n"
                    f"*Title:* [{event.title}]({event_url})\n"
                    f"*Date:* {date_str}\n"
                    f"*Group:* {group.name}"
                )
                post_to_telegram_channel(group.telegram_webhook_channel, msg, parse_mode="Markdown")
            return redirect('event_detail', event_id=event.id)
        else:
            # Form is invalid - render with errors but preserve the data
            print("Form errors:", form.errors)
            return render(request, 'events/event_create.html', {'form': form})
    else:
        form = EventForm(user=request.user)
    return render(request, 'events/event_create.html', {'form': form})

@login_required
def edit_event(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if request.user != event.organizer and not request.user.is_superuser:
        messages.error(request, "You are not authorized to edit this event.")
        return redirect('event_detail', event_id=event.id)

    # Only check group role/delegation if user is not the organizer or superuser
    if not request.user.is_superuser and request.user != event.organizer:
        is_delegated_assistant = False
        if request.user.is_authenticated and event.group:
            is_delegated_assistant = GroupDelegation.objects.filter(delegated_user=request.user, group=event.group, organizer=event.organizer).exists()
        is_leader = GroupRole.objects.filter(user=request.user, group=event.group).exists()
        if not (is_leader or is_delegated_assistant):
            messages.error(request, "You are not authorized to edit events for this group.")
            return redirect('event_detail', event_id=event.id)

    if request.method == 'POST':
        # Handle the form submission manually to avoid TinyMCE validation issues
        try:
            # Get all the form data
            title = request.POST.get('title', event.title)
            group_id = request.POST.get('group')
            date = request.POST.get('date')
            start_time = request.POST.get('start_time')
            end_time = request.POST.get('end_time')
            address = request.POST.get('address', event.address)
            city = request.POST.get('city', event.city)
            state = request.POST.get('state', event.state)
            age_restriction = request.POST.get('age_restriction', event.age_restriction)
            description = request.POST.get('description', event.description)
            capacity = request.POST.get('capacity')
            waitlist_enabled = request.POST.get('waitlist_enabled') == 'on'
            attendee_list_public = request.POST.get('attendee_list_public') == 'on'
            accessibility_details = request.POST.get('accessibility_details', event.accessibility_details)
            
            print(f"DEBUG: Description content received: {description[:200]}...")  # Debug log
            
            # Validate required fields
            errors = []
            if not title:
                errors.append('Title is required')
            if not group_id:
                errors.append('Group is required')
            if not date:
                errors.append('Date is required')
            if not start_time:
                errors.append('Start time is required')
            if not end_time:
                errors.append('End time is required')
            
            if errors:
                print(f"DEBUG: Validation errors: {errors}")  # Debug log
                messages.error(request, f"Please fix the following errors: {', '.join(errors)}")
                return redirect(f'{event.get_absolute_url()}?edit=1')
            
            # Update the event
            event.title = title
            if group_id:
                event.group = Group.objects.get(id=group_id)
            if date:
                # Convert MM/DD/YYYY to YYYY-MM-DD format
                try:
                    from datetime import datetime
                    parsed_date = datetime.strptime(date, '%m/%d/%Y')
                    event.date = parsed_date.date()
                except ValueError:
                    # Try alternative format if the first one fails
                    try:
                        parsed_date = datetime.strptime(date, '%Y-%m-%d')
                        event.date = parsed_date.date()
                    except ValueError:
                        print(f"DEBUG: Could not parse date: {date}")
                        messages.error(request, f"Invalid date format: {date}. Please use MM/DD/YYYY format.")
                        return redirect(f'{event.get_absolute_url()}?edit=1')
            if start_time:
                # Parse time string to time object
                try:
                    from datetime import datetime
                    # Try different time formats
                    time_formats = ['%H:%M', '%I:%M %p', '%I:%M%p', '%I:%M %P', '%I:%M%P']
                    parsed_start_time = None
                    for fmt in time_formats:
                        try:
                            parsed_start_time = datetime.strptime(start_time, fmt).time()
                            break
                        except ValueError:
                            continue
                    
                    if parsed_start_time is None:
                        messages.error(request, f"Invalid start time format: {start_time}. Please use HH:MM or HH:MM AM/PM format.")
                        return redirect(f'{event.get_absolute_url()}?edit=1')
                    
                    event.start_time = parsed_start_time
                except Exception as e:
                    messages.error(request, f"Error parsing start time: {start_time}")
                    return redirect(f'{event.get_absolute_url()}?edit=1')
            
            if end_time:
                # Parse time string to time object
                try:
                    from datetime import datetime
                    # Try different time formats
                    time_formats = ['%H:%M', '%I:%M %p', '%I:%M%p', '%I:%M %P', '%I:%M%P']
                    parsed_end_time = None
                    for fmt in time_formats:
                        try:
                            parsed_end_time = datetime.strptime(end_time, fmt).time()
                            break
                        except ValueError:
                            continue
                    
                    if parsed_end_time is None:
                        messages.error(request, f"Invalid end time format: {end_time}. Please use HH:MM or HH:MM AM/PM format.")
                        return redirect(f'{event.get_absolute_url()}?edit=1')
                    
                    event.end_time = parsed_end_time
                except Exception as e:
                    messages.error(request, f"Error parsing end time: {end_time}")
                    return redirect(f'{event.get_absolute_url()}?edit=1')
            event.address = address
            event.city = city
            event.state = state
            event.age_restriction = age_restriction
            event.description = description
            if capacity:
                event.capacity = int(capacity) if capacity.isdigit() else None
            event.waitlist_enabled = waitlist_enabled
            event.attendee_list_public = attendee_list_public
            event.accessibility_details = accessibility_details
            
            event.save()
            print(f"DEBUG: Event saved with description length: {len(event.description)}")  # Debug log
            
            # Store old data for comparison
            old_data = {
                'title': event.title,
                'date': event.date.isoformat(),
                'description': event.description,
                'capacity': event.capacity,
                'status': event.status,
                'group': event.group.name if event.group else None
            }
            
            # Log the event update
            AuditLog.log_action(
                user=request.user,
                action='event_updated',
                description=f'Updated event: {event.title}',
                group=event.group,
                event=event,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                additional_data={
                    'old_data': old_data,
                    'new_data': {
                        'title': event.title,
                        'date': event.date.isoformat(),
                        'description': event.description,
                        'capacity': event.capacity,
                        'status': event.status,
                        'group': event.group.name if event.group else None
                    }
                }
            )
            
            create_notification(request.user, f'Event for {event.title} updated successfully!', link=event.get_absolute_url())
            for rsvp in event.rsvps.select_related('user').all():
                if rsvp.user and rsvp.user != request.user:
                    create_notification(
                        rsvp.user,
                        f'The event "{event.title}" you RSVP\'d to has been updated. Please review the changes.',
                        link=event.get_absolute_url()
                    )
            return redirect('event_detail', event_id=event.id)
            
        except Exception as e:
            print(f"DEBUG: Error saving event: {e}")  # Debug log
            messages.error(request, f"Error saving event: {str(e)}")
            return redirect(event.get_absolute_url())
    else:
        # For GET requests, just redirect to event detail page
        return redirect(event.get_absolute_url())

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
            
            return redirect('event_detail', event_id=event.id)
    
    return redirect('event_detail', event_id=event.id)

def terms(request):
    return render(request, 'events/terms.html')

def faq(request):
    return render(request, 'events/faq.html')

def eula(request):
    return render(request, 'events/eula.html')

def privacy(request):
    return render(request, 'events/privacy.html')

def clean_html_content(html_content):
    """
    Clean and parse HTML content, removing unwanted tags and attributes
    while preserving safe HTML formatting.
    """
    if not html_content:
        return ""
    
    import re
    from bs4 import BeautifulSoup
    
    try:
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove unwanted tags and attributes
        unwanted_tags = ['script', 'style', 'iframe', 'object', 'embed']
        for tag in unwanted_tags:
            for element in soup.find_all(tag):
                element.decompose()
        
        # Remove unwanted attributes
        unwanted_attrs = ['onclick', 'onload', 'onerror', 'onmouseover', 'onmouseout']
        for tag in soup.find_all():
            for attr in unwanted_attrs:
                if attr in tag.attrs:
                    del tag.attrs[attr]
        
        # Clean up Wix-specific classes and styles
        for tag in soup.find_all():
            if 'wixui-rich-text' in tag.get('class', []):
                # Remove Wix-specific classes but keep the content
                new_classes = [cls for cls in tag.get('class', []) if 'wixui' not in cls]
                if new_classes:
                    tag['class'] = new_classes
                else:
                    del tag['class']
            
            # Clean up inline styles that might be problematic
            if tag.get('style'):
                style = tag['style']
                # Remove potentially dangerous CSS properties
                dangerous_props = ['javascript:', 'expression(', 'eval(']
                for prop in dangerous_props:
                    if prop in style.lower():
                        del tag['style']
                        break
        
        # Convert to string and clean up
        cleaned_html = str(soup)
        
        # Remove any remaining problematic patterns
        cleaned_html = re.sub(r'<p><span[^>]*>', '<p>', cleaned_html)
        cleaned_html = re.sub(r'</span></p>', '</p>', cleaned_html)
        
        return cleaned_html
        
    except Exception as e:
        # If parsing fails, return the original content stripped of HTML tags
        import html
        return html.escape(html_content)

def group_detail(request, group_id):
    group = get_object_or_404(Group, pk=group_id)
    
    # Clean the group description HTML
    if group.description:
        group.description = clean_html_content(group.description)
    
    # Remove legacy organizers and assistants
    organizers = []
    assistants = []
    
    # Get upcoming and past events
    upcoming_events = group.get_upcoming_events()
    past_events = group.get_past_events()[:10]  # Limit to 10 most recent past events
    
    # Check if user can edit this group
    can_edit_group = False
    if request.user.is_authenticated:
        can_edit_group = (
            request.user.is_superuser or 
            GroupRole.objects.filter(user=request.user, group=group).filter(
                Q(can_post=True) | Q(can_manage_leadership=True)
            ).exists()
        )
    
    # Handle POST requests
    if request.method == 'POST':
        print("DEBUG: POST request received")
        print("DEBUG: User is superuser:", request.user.is_superuser)
        print("DEBUG: Can edit group:", can_edit_group)
        print("DEBUG: POST keys:", list(request.POST.keys()))
        
        if not can_edit_group:
            messages.error(request, 'You do not have permission to edit this group.')
            return redirect('group_detail', group_id=group.id)
        # Handle group editing
        if 'edit_group' in request.POST:
            try:
                # Update group fields
                group.name = request.POST.get('name', group.name)
                group.description = request.POST.get('description', group.description)
                group.website = request.POST.get('website', group.website)
                group.contact_email = request.POST.get('contact_email', group.contact_email)
                group.telegram_channel = request.POST.get('telegram_channel', group.telegram_channel)
                group.telegram_webhook_channel = request.POST.get('telegram_webhook_channel', group.telegram_webhook_channel)
                
                # Handle logo upload
                logo_base64 = request.POST.get('logo_base64')
                if logo_base64:
                    group.logo_base64 = logo_base64
                
                group.save()
                messages.success(request, f'Group "{group.name}" has been updated successfully.')
                return redirect('group_detail', group_id=group.id)
                
            except Exception as e:
                messages.error(request, f'Error updating group: {str(e)}')
        
        # Handle leadership management
        elif 'add_leader' in request.POST:
            user_id = request.POST.get('new_leader')
            custom_label = request.POST.get('leader_role', '')
            
            if user_id:
                try:
                    user_obj = User.objects.get(id=user_id)
                    
                    # Check if user is already a leader in this group
                    existing_role = GroupRole.objects.filter(user=user_obj, group=group).first()
                    if existing_role:
                        messages.error(request, f'{user_obj.profile.get_display_name()} is already a leader in this group.')
                    else:
                        # Create new role
                        role = GroupRole.objects.create(
                            user=user_obj,
                            group=group,
                            custom_label=custom_label,
                            can_post=True,
                            can_manage_leadership=True
                        )
                        messages.success(request, f'{user_obj.profile.get_display_name()} added as leader successfully.')
                except User.DoesNotExist:
                    messages.error(request, 'Selected user not found.')
                except Exception as e:
                    messages.error(request, f'Error adding leader: {str(e)}')
            else:
                messages.error(request, 'Please select a user to add as leader.')
            
            return redirect('group_detail', group_id=group.id)
        
        elif 'edit_leader' in request.POST:
            role_id = request.POST.get('role_id')
            try:
                role = GroupRole.objects.get(pk=role_id, group=group)
                role.custom_label = request.POST.get('custom_label', role.custom_label)
                role.can_manage_leadership = bool(request.POST.get('can_manage_leadership'))
                role.save()
                messages.success(request, 'Leader updated successfully.')
            except GroupRole.DoesNotExist:
                messages.error(request, 'Leader not found.')
            return redirect('group_detail', group_id=group.id)
        
        elif 'submit_leadership_changes' in request.POST or 'remove_leader' in request.POST:
            # Handle leadership changes from the modal
            if 'remove_leader' in request.POST:
                # Find which remove_leader button was clicked
                user_id = None
                for key in request.POST.keys():
                    if key.startswith('remove_leader_'):
                        user_id = key.replace('remove_leader_', '')
                        break
                
                if user_id:
                    try:
                        role = GroupRole.objects.get(user_id=user_id, group=group)
                        user_name = role.user.profile.get_display_name()
                        
                        # Check if trying to remove the last leader (prevent orphaned groups)
                        total_leaders = GroupRole.objects.filter(group=group).count()
                        if total_leaders <= 1:
                            messages.error(request, f'Cannot remove {user_name}: Groups must have at least one leader.')
                        else:
                            role.delete()
                            messages.success(request, f'Successfully removed {user_name} as leader.')
                    except GroupRole.DoesNotExist:
                        messages.error(request, 'Leader not found.')
                else:
                    messages.error(request, 'Invalid request. No user ID found.')
                    # Debug: log all POST keys
                    print("DEBUG: POST keys:", list(request.POST.keys()))
                    print("DEBUG: User is superuser:", request.user.is_superuser)
                    print("DEBUG: Can edit group:", can_edit_group)
            
            # Handle add leader from the modal
            elif 'add_leader' in request.POST:
                user_id = request.POST.get('new_leader')
                custom_label = request.POST.get('leader_role', '').strip()
                
                if user_id:
                    try:
                        user_obj = User.objects.get(id=user_id)
                        
                        # Check if user is already a leader in this group
                        existing_role = GroupRole.objects.filter(user=user_obj, group=group).first()
                        if existing_role:
                            messages.error(request, f'{user_obj.profile.get_display_name()} is already a leader in this group.')
                        else:
                            # Create new role
                            role = GroupRole.objects.create(
                                user=user_obj,
                                group=group,
                                custom_label=custom_label,
                                can_post=True,
                                can_manage_leadership=True
                            )
                            messages.success(request, f'{user_obj.profile.get_display_name()} added as leader successfully.')
                    except User.DoesNotExist:
                        messages.error(request, 'Selected user not found.')
                    except Exception as e:
                        messages.error(request, f'Error adding leader: {str(e)}')
                else:
                    messages.error(request, 'Please select a user to add as leader.')
            
            return redirect('group_detail', group_id=group.id)
    
    # Get Telegram feed for this group (if channel set), else default
    telegram_channel = group.telegram_channel
    telegram_feed = get_telegram_feed(telegram_channel)

    # Leadership roles and form
    leadership_roles = GroupRole.objects.filter(group=group).select_related('user')
    
    # For staff, show all users. For group leaders, only show users not already in the group
    if request.user.is_superuser:
        leadership_form = GroupRoleForm()  # Show all users for staff
        all_users = User.objects.all().select_related('profile')
    else:
        leadership_form = GroupRoleForm(group=group)  # Exclude existing members for group leaders
        all_users = User.objects.exclude(
            id__in=GroupRole.objects.filter(group=group).values_list('user_id', flat=True)
        ).select_related('profile')
    
    context = {
        'group': group,
        'organizers': organizers,
        'assistants': assistants,
        'upcoming_events': upcoming_events,
        'past_events': past_events,
        'can_edit_group': can_edit_group,
        'telegram_feed': telegram_feed,
        'leadership_roles': leadership_roles,
        'leadership_form': leadership_form,
        'all_users': all_users,
        'can_manage_leadership': can_edit_group,  # or use your own logic
    }
    
    return render(request, 'events/group_detail.html', context)

@login_required
def manage_group_leadership(request, group_id):
    group = get_object_or_404(Group, pk=group_id)
    user_roles = GroupRole.objects.filter(group=group, user=request.user)
    can_manage = user_roles.filter(can_manage_leadership=True).exists() or request.user.is_superuser
    if not can_manage:
        return HttpResponseForbidden('You do not have permission to manage leadership.')

    if request.method == 'POST':
        if 'add_leader' in request.POST:
            # For staff, don't pass group parameter to allow adding any user
            if request.user.is_superuser:
                form = GroupRoleForm(request.POST)
            else:
                form = GroupRoleForm(request.POST, group=group)
            
            if form.is_valid():
                role = form.save(commit=False)
                role.group = group
                # If this is the first leader for the group, give all permissions
                if GroupRole.objects.filter(group=group).count() == 0:
                    role.can_post = True
                    role.can_manage_leadership = True
                role.save()
                messages.success(request, 'Leader added successfully.')
            else:
                messages.error(request, 'Error adding leader. Please check the form.')
            return redirect('group_detail', group_id=group.id)
        elif 'edit_leader' in request.POST:
            role_id = request.POST.get('role_id')
            role = get_object_or_404(GroupRole, pk=role_id, group=group)
            form = GroupRoleForm(request.POST, instance=role, group=group)
            if form.is_valid():
                form.save()
                return JsonResponse({'success': True, 'msg': 'Leader updated successfully.'})
            else:
                return JsonResponse({'success': False, 'errors': form.errors})
        elif 'remove_leader' in request.POST:
            role_id = request.POST.get('role_id')
            role = get_object_or_404(GroupRole, pk=role_id, group=group)
            role.delete()
            return JsonResponse({'success': True, 'msg': 'Leader removed successfully.'})
    else:
        roles = GroupRole.objects.filter(group=group).select_related('user')
        form = GroupRoleForm(group=group)
        return render(request, 'events/leadership_editor.html', {'group': group, 'roles': roles, 'form': form, 'can_manage': can_manage})

def groups_list(request):
    search_query = request.GET.get('search', '').strip()
    groups = Group.objects.all()
    if search_query:
        groups = groups.filter(
            models.Q(name__icontains=search_query) |
            models.Q(description__icontains=search_query)
        )
    groups = groups.order_by('name')
    
    # Clean HTML content for all groups
    for group in groups:
        if group.description:
            group.description = clean_html_content(group.description)
    
    paginator = Paginator(groups, 9)  # 9 groups per page
    page = request.GET.get('page', 1)
    try:
        paginated_groups = paginator.page(page)
    except PageNotAnInteger:
        paginated_groups = paginator.page(1)
    except EmptyPage:
        paginated_groups = paginator.page(paginator.num_pages)
    context = {
        'groups': paginated_groups,
        'search_query': search_query,
    }
    return render(request, 'events/groups_list.html', context)

def event_index(request):
    """Calendar view with all events underneath"""
    # Get year and month from request, default to current
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Get filter parameters for events list
    sort_by = request.GET.get('sort', 'date')
    sort_order = request.GET.get('order', 'asc')
    filter_adult = request.GET.get('adult', 'true')
    view_type = request.GET.get('view', 'list')
    page = request.GET.get('page', 1)
    search_query = request.GET.get('search', '').strip()
    state_filter = request.GET.get('state', '').strip()
    mileage_range = request.GET.get('mileage', '50')  # Default 50 miles
    
    # Set first weekday to Sunday
    calendar.setfirstweekday(calendar.SUNDAY)
    # Create calendar object
    cal = calendar.monthcalendar(year, month)
    # Get month name
    month_name = calendar.month_name[month]
    # Get events for this month
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date()
    else:
        end_date = datetime(year, month + 1, 1, 1).date()
    calendar_events = Event.objects.filter(
        date__gte=start_date,
        date__lt=end_date,
        status='active'
    ).order_by('date', 'start_time')
    # Group events by date
    events_by_date = {}
    for event in calendar_events:
        date_key = event.date.strftime('%Y-%m-%d')
        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(event)
    # Navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    eastern = pytz.timezone('America/New_York')
    today = timezone.now().astimezone(eastern).date()
    
    # Get all events for the list section
    now = timezone.now()
    all_events = Event.objects.filter(
        models.Q(date__gt=now.date()) | 
        (models.Q(date=now.date()) & models.Q(end_time__gt=now.time())),
        status='active'
    )
    
    # Convert to list for filtering
    all_events = list(all_events)
    
    # Clean HTML content for all events
    for event in all_events:
        if event.description:
            event.description = clean_html_content(event.description)
    
    # Handle adult content filtering
    if filter_adult == 'false' or filter_adult == 'hide':
        all_events = [e for e in all_events if e.age_restriction not in ['adult', 'mature']]
    elif filter_adult == 'show':
        # Show only adult events
        all_events = [e for e in all_events if e.age_restriction in ['adult', 'mature']]
    # If filter_adult is 'true' or empty, show all events (default behavior)

    # Apply search filter
    if search_query:
        all_events = [e for e in all_events if 
                     search_query.lower() in e.title.lower() or
                     (e.description and search_query.lower() in e.description.lower()) or
                     (e.city and search_query.lower() in e.city.lower()) or
                     (e.group and search_query.lower() in e.group.name.lower())]

    # Apply state filter
    if state_filter:
        all_events = [e for e in all_events if e.state and e.state.lower() == state_filter.lower()]

    # Get user location from form or session
    user_location = request.GET.get('user_location') or request.session.get('user_location', 'CA')
    if user_location:
        request.session['user_location'] = user_location
    
    # Apply pagination
    paginator = Paginator(all_events, 12)  # 12 events per page
    try:
        paginated_events = paginator.page(page)
    except PageNotAnInteger:
        paginated_events = paginator.page(1)
    except EmptyPage:
        paginated_events = paginator.page(paginator.num_pages)
    
    # Apply mileage filter using OpenStreetMap geocoding - temporarily disabled
    # if mileage_range and mileage_range != 'all':
    #     try:
    #         mileage = int(mileage_range)
    #         print(f"DEBUG: Before mileage filtering: {len(all_events)} events")
    #         
    #         # Get user coordinates from session
    #         user_lat = request.session.get('user_lat')
    #         user_lng = request.session.get('user_lng')
    #         
    #         if user_lat and user_lng:
    #             # Use OpenStreetMap to calculate distances to event cities
    #             import requests
    #             import math
    #             
    #             def calculate_distance(lat1, lon1, lat2, lon2):
    #                 """Calculate distance between two points using Haversine formula"""
    #                 R = 3959  # Earth's radius in miles
    #                 
    #                 lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    #                 dlat = lat2 - lat1
    #                 dlon = lon2 - lon1
    #                     
    #                     a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    #                     c = 2 * math.asin(math.sqrt(a))
    #                     distance = R * c
    #                     
    #                     return distance
    #                 
    #                 def geocode_city(city, state):
    #                     """Geocode a city using OpenStreetMap Nominatim API"""
    #                     try:
    #                         query = f"{city}, {state}, USA"
    #                         url = "https://nominatim.openstreetmap.org/search"
    #                         params = {
    #                             'q': query,
    #                             'format': 'json',
    #                             'limit': 1,
    #                             'countrycodes': 'us'
    #                         }
    #                         headers = {
    #                             'User-Agent': 'FURsvp/1.0 (https://fursvp.org)'
    #                         }
    #                         
    #                         response = requests.get(url, params=params, headers=headers, timeout=5)
    #                         if response.status_code == 200:
    #                             data = response.json()
    #                             if data:
    #                                     return float(data[0]['lat']), float(data[0]['lon'])
    #                     except Exception as e:
    #                         print(f"Geocoding error for {city}, {state}: {e}")
    #                     return None, None
    #                 
    #                 # Filter events by distance
    #                 events_within_range = []
    #                 user_lat, user_lng = float(user_lat), float(user_lng)
    #                 
    #                 for event in all_events:
    #                     if event.city and event.state:
    #                         # Try to get coordinates for the event city
    #                         event_lat, event_lng = geocode_city(event.city, event.state)
    #                         
    #                         if event_lat and event_lng:
    #                             # Calculate distance
    #                             distance = calculate_distance(user_lat, user_lng, event_lat, event_lng)
    #                             
    #                             if distance <= mileage:
    #                                 events_within_range.append(event.id)
    #                         else:
    #                             # Fallback: include events in the same state for local searches
    #                             if mileage <= 50:
    #                                 user_state = request.session.get('user_state', user_location)
    #                                 if event.state == user_state:
    #                                     events_within_range.append(event.id)
    #                 
    #                 # Filter the list to only include events within range
    #                 if events_within_range:
    #                     all_events = [e for e in all_events if e.id in events_within_range]
    #                 else:
    #                     # If no events found, show events in the same state
    #                     user_state = request.session.get('user_state', user_location)
    #                     all_events = [e for e in all_events if e.state and e.state.lower() == user_state.lower()]
    #             else:
    #                 # Fallback to state-based filtering if no coordinates
    #                 if mileage <= 100:
    #                     all_events = [e for e in all_events if e.state and e.state.lower() == user_location.lower()]
    #                 
    #         except ValueError:
    #             pass

    # Add user's RSVP information if user is authenticated
    if request.user.is_authenticated:
        # Add user's RSVP list for template compatibility
        for event in all_events:
            user_rsvp = event.rsvps.filter(user=request.user).first()
            if user_rsvp:
                event.user_rsvp_list = [user_rsvp]
            else:
                event.user_rsvp_list = []
    
    # Apply sorting
    if sort_by == 'date':
        # all_events = all_events.order_by('date', 'start_time') if sort_order == 'asc' else all_events.order_by('-date', '-start_time')
        pass
    elif sort_by == 'group':
        # all_events = all_events.order_by(models.functions.Lower('group__name') if sort_order == 'asc' else models.functions.Lower('group__name').desc())
        pass
    elif sort_by == 'title':
        # all_events = all_events.order_by(models.functions.Lower('title') if sort_order == 'asc' else models.functions.Lower('title').desc())
        pass
    elif sort_by == 'rsvps':
        # all_events = all_events.annotate(rsvp_count=models.Count('rsvps')).order_by(
        #     'rsvp_count' if sort_order == 'asc' else '-rsvp_count'
        # )
        pass
    
    # Apply pagination
    
    # Apply pagination
    paginator = Paginator(all_events, 12)  # 12 events per page
    try:
        events_page = paginator.page(page)
    except PageNotAnInteger:
        events_page = paginator.page(1)
    except EmptyPage:
        events_page = paginator.page(paginator.num_pages)
    
    # Add user's RSVP information if user is authenticated (AFTER pagination)
    if request.user.is_authenticated:
        # Add user's RSVP list for template compatibility
        for event in events_page.object_list:
            user_rsvp = event.rsvps.filter(user=request.user).first()
            if user_rsvp:
                event.user_rsvp_list = [user_rsvp]
            else:
                event.user_rsvp_list = []
    
    # Get all unique states for the dropdown
    all_states = Event.objects.exclude(state__isnull=True).exclude(state__exact='').values_list('state', flat=True).distinct().order_by('state')
    
    # Get groups count for stats
    from users.models import Group
    groups_count = Group.objects.count()
    

    
    context = {
        'calendar': cal,
        'month_name': month_name,
        'year': year,
        'month': month,
        'events_by_date': events_by_date,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'today': today,
        'events': events_page,
        'current_sort': sort_by,
        'current_order': sort_order,
        'filter_adult': filter_adult,
        'view_type': view_type,
        'paginator': events_page.paginator,
        'page_obj': events_page,
        'all_states': all_states,
        'mileage_range': mileage_range,
        'search_query': search_query,
        'state_filter': state_filter,
        'groups_count': groups_count,
    }
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # If it's an AJAX request, only return the partial event list HTML
        return render(request, 'events/events_list_partial.html', context)
    
    return render(request, 'events/event_index.html', context)

@csrf_exempt
def save_user_location(request):
    """Save user's geolocation coordinates"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            lat = data.get('lat')
            lng = data.get('lng')
            state = data.get('state')
            
            if lat and lng:
                request.session['user_lat'] = lat
                request.session['user_lng'] = lng
                if state:
                    request.session['user_state'] = state
                
                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})



@login_required
def rsvp_answers(request, event_id, user_id):
    from .models import RSVP, Event
    event = Event.objects.get(pk=event_id)
    is_organizer = (request.user == event.organizer) or request.user.is_superuser
    if not is_organizer:
        return JsonResponse({'error': 'Forbidden'}, status=403)
    try:
        rsvp = RSVP.objects.get(event=event, user_id=user_id)
        data = {
            'question1_text': event.question1_text,
            'question1': rsvp.question1,
            'question2_text': event.question2_text,
            'question2': rsvp.question2,
            'question3_text': event.question3_text,
            'question3': rsvp.question3,
        }
        return JsonResponse(data)
    except RSVP.DoesNotExist:
        return JsonResponse({'error': 'RSVP not found'}, status=404)

@csrf_exempt
def telegram_bot_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'ok': True})
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'})
    message = data.get('message', {})
    chat = message.get('chat', {})
    chat_id = str(chat.get('id'))
    text = message.get('text', '')

    from django.utils import timezone
    today = timezone.now().date()

    def send_telegram_message(chat_id, text, parse_mode=None, reply_markup=None):
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(url, json=payload)
        print(resp.text)

    # Try to find a group for this chat_id
    group = Group.objects.filter(telegram_webhook_channel=chat_id).first()

    # Get Telegram username if available
    username = None
    if 'from' in message and message['from'].get('username'):
        username = message['from']['username']
    elif 'callback_query' in data and data['callback_query']['from'].get('username'):
        username = data['callback_query']['from']['username']

    # Handle callback queries for RSVP list, show all groups, and RSVP menu/actions
    if "callback_query" in data:
        callback = data["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        data_str = callback["data"]
        from events.models import RSVP
        from users.models import Profile
        # Show all groups
        if data_str == "show_all_groups":
            events = Event.objects.filter(date__gte=today).order_by('date')[:10]
            msg = "<b>Upcoming Events (All Groups)</b>\n\n"
            keyboard = []
            if events:
                for event in events:
                    url = f"https://{request.get_host()}{event.get_absolute_url()}"
                    keyboard.append([
                        {"text": event.title, "callback_data": f"rsvplist_{event.id}"},
                        {"text": "RSVP", "callback_data": f"rsvp_menu_{event.id}"}
                    ])
                    msg += f"• <a href='{url}'>{event.title}</a> — <code>{event.date.strftime('%m/%d/%Y')}</code>\n"
            else:
                msg += "No events found."
            send_telegram_message(chat_id, msg, parse_mode="HTML", reply_markup={"inline_keyboard": keyboard})
            return JsonResponse({'ok': True})
        # RSVP menu
        if data_str.startswith("rsvp_menu_"):
            event_id = data_str.split("_", 2)[2]
            try:
                event = Event.objects.get(id=event_id, date__gte=today)
            except Event.DoesNotExist:
                send_telegram_message(chat_id, "Event not found.")
                return JsonResponse({'ok': True})
            # Find user by Telegram username
            user = None
            if username:
                try:
                    profile = Profile.objects.get(telegram_username=username)
                    user = profile.user
                except Profile.DoesNotExist:
                    pass
            # Check if user already RSVP'd
            existing_rsvp = RSVP.objects.filter(event=event, user=user).first() if user else None
            # Check if event is full
            confirmed_count = RSVP.objects.filter(event=event, status='confirmed').count()
            is_full = event.capacity is not None and confirmed_count >= event.capacity
            # Build RSVP options
            keyboard = []
            keyboard.append([
                {"text": "✅ Confirm", "callback_data": f"rsvp_confirm_{event.id}"},
                {"text": "❔ Maybe", "callback_data": f"rsvp_maybe_{event.id}"},
                {"text": "🚫 Not Attending", "callback_data": f"rsvp_no_{event.id}"}
            ])
            if is_full and event.waitlist_enabled:
                keyboard.append([{"text": "⏳ Waitlist", "callback_data": f"rsvp_waitlist_{event.id}"}])
            if existing_rsvp:
                keyboard.append([{"text": "Remove RSVP", "callback_data": f"rsvp_remove_{event.id}"}])
            send_telegram_message(chat_id, f"<b>Choose your RSVP status for</b> <i>{event.title}</i>", parse_mode="HTML", reply_markup={"inline_keyboard": keyboard})
            return JsonResponse({'ok': True})
        # RSVP actions
        for status in ["confirm", "maybe", "no", "waitlist", "remove"]:
            if data_str.startswith(f"rsvp_{status}_"):
                event_id = data_str.split("_", 2)[2]
                try:
                    event = Event.objects.get(id=event_id, date__gte=today)
                except Event.DoesNotExist:
                    send_telegram_message(chat_id, "Event not found.")
                    return JsonResponse({'ok': True})
                # Find user by Telegram username
                user = None
                if username:
                    try:
                        profile = Profile.objects.get(telegram_username=username)
                        user = profile.user
                    except Profile.DoesNotExist:
                        send_telegram_message(chat_id, "You must link your Telegram username in your FURsvp profile to RSVP.")
                        return JsonResponse({'ok': True})
                if not user:
                    send_telegram_message(chat_id, "You must link your Telegram username in your FURsvp profile to RSVP.")
                    return JsonResponse({'ok': True})
                if status == "remove":
                    deleted, _ = RSVP.objects.filter(event=event, user=user).delete()
                    if deleted:
                        send_telegram_message(chat_id, "Your RSVP has been removed.")
                    else:
                        send_telegram_message(chat_id, "You do not have an RSVP for this event.")
                    return JsonResponse({'ok': True})
                # Set RSVP status
                rsvp, created = RSVP.objects.get_or_create(event=event, user=user, defaults={'status': status if status != 'no' else 'not_attending'})
                if not created:
                    if status == 'waitlist':
                        rsvp.status = 'waitlisted'
                    elif status == 'maybe':
                        rsvp.status = 'maybe'
                    elif status == 'no':
                        rsvp.status = 'not_attending'
                    else:
                        rsvp.status = 'confirmed'
                    rsvp.save()
                send_telegram_message(chat_id, f"Your RSVP status for <b>{event.title}</b> is now <b>{'Waitlisted' if status == 'waitlist' else status.capitalize() if status != 'no' else 'Not Attending'}</b>.", parse_mode="HTML")
                return JsonResponse({'ok': True})
        # RSVP list (unchanged)
        if data_str.startswith("rsvplist_"):
            event_id = data_str.split("_", 1)[1]
            if group:
                event = Event.objects.filter(id=event_id, group=group, date__gte=today).first()
            else:
                event = Event.objects.filter(id=event_id, date__gte=today).first()
            if not event:
                send_telegram_message(chat_id, "Event not found.")
            else:
                show_all = bool(group)
                if not show_all and not event.attendee_list_public:
                    send_telegram_message(chat_id, "The group organizer has hidden RSVPs from the public view.")
                else:
                    rsvps = RSVP.objects.filter(event=event, status='confirmed')
                    names = [r.user.profile.get_display_name() if r.user and hasattr(r.user, 'profile') else (r.user.username if r.user else r.name or 'Anonymous') for r in rsvps]
                    if names:
                        msg = f"<b>RSVP'd Users for</b> <i>{event.title}</i>\n\n" + "\n".join([f"• {name}" for name in names])
                    else:
                        msg = f"<b>RSVP'd Users for</b> <i>{event.title}</i>\n\n<em>No RSVPs yet.</em>"
                    send_telegram_message(chat_id, msg, parse_mode="HTML")
            return JsonResponse({'ok': True})

    if text.startswith('/event'):
        parts = text.split()
        if len(parts) == 1:
            # List upcoming events for this group if found, else all
            if group:
                events = Event.objects.filter(group=group, date__gte=today).order_by('date')[:10]
            else:
                events = Event.objects.filter(date__gte=today).order_by('date')[:10]
            msg = "<b>Upcoming Events</b>\n\n"
            keyboard = []
            if events:
                for event in events:
                    url = f"https://{request.get_host()}{event.get_absolute_url()}"
                    keyboard.append([
                        {"text": event.title, "callback_data": f"rsvplist_{event.id}"},
                        {"text": "RSVP", "callback_data": f"rsvp_menu_{event.id}"}
                    ])
                    msg += f"• <a href='{url}'>{event.title}</a> — <code>{event.date.strftime('%m/%d/%Y')}</code>\n"
            else:
                msg += "No events found for this group."
            # Always add the Show All Groups button if in a group
            if group:
                keyboard.append([{"text": "Show All Groups", "callback_data": "show_all_groups"}])
            reply_markup = {"inline_keyboard": keyboard}
            send_telegram_message(chat_id, msg, parse_mode="HTML", reply_markup=reply_markup)
        else:
            event_id = parts[1]
            if group:
                event = Event.objects.filter(id=event_id, group=group, date__gte=today).first()
            else:
                event = Event.objects.filter(id=event_id, date__gte=today).first()
            if not event:
                send_telegram_message(chat_id, "No event found.")
            else:
                url = f"https://{request.get_host()}{event.get_absolute_url()}"
                msg = f"<b>{event.title}</b>\nDate: <code>{event.date.strftime('%m/%d/%Y')}</code>\n<a href='{url}'>View Event</a>\n\n{event.description or ''}"
                send_telegram_message(chat_id, msg, parse_mode="HTML")

    return JsonResponse({'ok': True})

# RSVP by Telegram username endpoint
@require_GET
@ensure_csrf_cookie
def rsvp_telegram(request, event_id):
    username = request.GET.get('username')
    if not username:
        return HttpResponse('Missing Telegram username.', status=400)
    try:
        profile = Profile.objects.get(telegram_username=username)
    except Profile.DoesNotExist:
        return HttpResponse('No user with that Telegram username is registered.', status=404)
    try:
        event = Event.objects.get(id=event_id)
    except Event.DoesNotExist:
        return HttpResponse('Event not found.', status=404)
    from events.models import RSVP
    rsvp, created = RSVP.objects.get_or_create(event=event, user=profile.user, defaults={'status': 'confirmed'})
    if not created:
        return HttpResponse('You have already RSVP\'d to this event.', status=200)
    return HttpResponse('RSVP successful! You are now confirmed for this event.', status=200)

def blog(request):
    profile = request.GET.get('profile', 'fursvp.org')
    bluesky_feed = get_bluesky_feed(profile=profile, limit=10)
    context = {
        'bluesky_feed': bluesky_feed,
        'bluesky_profile': profile,
    }
    return render(request, 'events/blog.html', context)

def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        inquiry_type = request.POST.get('inquiry_type')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # Validate required fields
        if not all([name, email, inquiry_type, subject, message]):
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'events/contact.html')
        
        # Prepare email content
        inquiry_type_display = {
            'general': 'General Inquiries',
            'organizer': 'Organizer Inquiries', 
            'user': 'User Inquiries',
            'development': 'Development Inquiries'
        }.get(inquiry_type, inquiry_type)
        
        email_subject = f"FURsvp Contact: {subject} - {inquiry_type_display}"
        
        email_body = f"""
New contact form submission from FURsvp website:

Name: {name}
Email: {email}
Inquiry Type: {inquiry_type_display}
Subject: {subject}

Message:
{message}

---
This message was sent from the FURsvp contact form.
        """
        
        try:
            # Send email using Django's email backend
            send_mail(
                subject=email_subject,
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.CONTACT_EMAIL],  # You'll need to add this to settings
                fail_silently=False,
            )
            
            messages.success(request, 'Thank you for your message! We will get back to you within 3 business days.')
            return render(request, 'events/contact.html')
            
        except Exception as e:
            messages.error(request, 'Sorry, there was an error sending your message. Please try again later.')
            return render(request, 'events/contact.html')
    
    return render(request, 'events/contact.html')

def custom_404(request, exception=None):
    """Custom 404 error page"""
    return render(request, 'events/404.html', status=404)