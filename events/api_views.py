from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import datetime
from django.db.models import Q
from rest_framework.views import APIView
from django.shortcuts import render
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.contrib.auth.models import User

from .models import Group, Event, RSVP
from .serializers import (
    GroupSerializer, EventSerializer, EventDetailSerializer, RSVPSerializer, UserLookupSerializer
)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for User model - read-only"""
    queryset = User.objects.all()
    serializer_class = UserLookupSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @swagger_auto_schema(
        operation_description="Look up user by Telegram username",
        manual_parameters=[
            openapi.Parameter('username', openapi.IN_QUERY, description="Telegram username (with or without @)", type=openapi.TYPE_STRING, required=True),
        ],
        responses={
            200: openapi.Response('Success - User found'),
            400: 'Bad Request - Missing username parameter',
            404: 'Not Found - User not found'
        }
    )
    @action(detail=False, methods=['get'])
    def by_telegram(self, request):
        """Look up user by Telegram username"""
        telegram_username = request.query_params.get('username', '').strip()
        
        if not telegram_username:
            return Response(
                {'error': 'Query parameter "username" is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Remove @ if present
        if telegram_username.startswith('@'):
            telegram_username = telegram_username[1:]
        
        try:
            user = User.objects.get(profile__telegram_username=telegram_username)
            serializer = UserLookupSerializer(user)
            return Response({
                'found': True,
                'user': serializer.data
            })
        except User.DoesNotExist:
            return Response({
                'found': False,
                'message': f'No user found with Telegram username: {telegram_username}'
            }, status=status.HTTP_404_NOT_FOUND)

    @swagger_auto_schema(
        operation_description="Get events registered by a specific user (respecting privacy settings)",
        manual_parameters=[
            openapi.Parameter('user_id', openapi.IN_QUERY, description="User ID to look up events for", type=openapi.TYPE_INTEGER, required=True),
        ],
        responses={
            200: openapi.Response('Success - User events retrieved'),
            400: 'Bad Request - Missing user_id parameter',
            404: 'Not Found - User not found'
        }
    )
    @action(detail=False, methods=['get'])
    def events(self, request):
        """Get events registered by a specific user (respecting privacy settings)"""
        user_id = request.query_params.get('user_id', '').strip()
        
        if not user_id:
            return Response(
                {'error': 'Query parameter "user_id" is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({
                'error': f'User with ID {user_id} not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get user's RSVPs
        user_rsvps = RSVP.objects.filter(user=user).select_related('event', 'event__group')
        
        # Filter events based on privacy settings
        visible_events = []
        for rsvp in user_rsvps:
            event = rsvp.event
            
            # Skip cancelled events
            if event.status == 'cancelled':
                continue
            
            # Check if event is visible based on privacy settings
            is_visible = False
            
            # Event is visible if:
            # 1. User is requesting their own events
            # 2. Event has public attendee list
            # 3. User is authenticated and is an organizer/admin
            if (request.user.is_authenticated and 
                (request.user == user or 
                 request.user == event.organizer or 
                 request.user.is_staff)):
                is_visible = True
            elif event.attendee_list_public:
                is_visible = True
            
            if is_visible:
                event_data = {
                    'event_id': event.id,
                    'event_title': event.title,
                    'group_name': event.group.name,
                    'event_date': event.date,
                    'rsvp_status': rsvp.status,
                    'rsvp_timestamp': rsvp.timestamp,
                    'attendee_list_public': event.attendee_list_public
                }
                visible_events.append(event_data)
        
        # Sort by event date (most recent first)
        visible_events.sort(key=lambda x: x['event_date'], reverse=True)
        
        return Response({
            'user_id': user_id,
            'username': user.username,
            'display_name': user.profile.get_display_name() if hasattr(user, 'profile') else user.username,
            'events': visible_events,
            'count': len(visible_events)
        })


class GroupViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for Group model - read-only"""
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['get'])
    def events(self, request, pk=None):
        """Get all events for a specific group"""
        group = self.get_object()
        events = Event.objects.filter(group=group, status='active')
        
        # Filter by upcoming/past events
        event_type = request.query_params.get('type', 'all')
        now = timezone.now()
        
        if event_type == 'upcoming':
            events = events.filter(
                Q(date__gt=now.date()) | 
                (Q(date=now.date()) & Q(end_time__gt=now.time()))
            ).order_by('date', 'start_time')
        elif event_type == 'past':
            events = events.filter(
                Q(date__lt=now.date()) | 
                (Q(date=now.date()) & Q(end_time__lt=now.time()))
            ).order_by('-date', '-start_time')
        else:
            events = events.order_by('date', 'start_time')
        
        serializer = EventSerializer(events, many=True)
        return Response(serializer.data)


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for Event model - read-only"""
    queryset = Event.objects.filter(status='active')
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_serializer_class(self):
        """Use detailed serializer for single event, basic for list"""
        if self.action == 'retrieve':
            return EventDetailSerializer
        return EventSerializer
    
    def get_queryset(self):
        """Filter queryset based on query parameters"""
        queryset = Event.objects.filter(status='active')
        
        # Filter by group
        group_id = self.request.query_params.get('group', None)
        if group_id:
            queryset = queryset.filter(group_id=group_id)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        # Filter by event type (upcoming/past) - only if explicitly requested
        event_type = self.request.query_params.get('type', None)
        if event_type:
            now = timezone.now()
            
            if event_type == 'upcoming':
                queryset = queryset.filter(
                    Q(date__gt=now.date()) | 
                    (Q(date=now.date()) & Q(end_time__gt=now.time()))
                )
            elif event_type == 'past':
                queryset = queryset.filter(
                    Q(date__lt=now.date()) | 
                    (Q(date=now.date()) & Q(end_time__lt=now.time()))
                )
        
        # Filter by location
        city = self.request.query_params.get('city', None)
        if city:
            queryset = queryset.filter(city__icontains=city)
        
        state = self.request.query_params.get('state', None)
        if state:
            queryset = queryset.filter(state__icontains=state)
        
        # Filter by age restriction
        age_restriction = self.request.query_params.get('age_restriction', None)
        if age_restriction:
            queryset = queryset.filter(age_restriction=age_restriction)
        
        return queryset.order_by('date', 'start_time')
    
    @action(detail=True, methods=['get'])
    def attendees(self, request, pk=None):
        """Get attendees for a specific event"""
        event = self.get_object()
        
        # Check if attendee list is public
        if not event.attendee_list_public and not request.user.is_authenticated:
            return Response(
                {'error': 'Attendee list is not public for this event'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        rsvps = event.rsvps.filter(status='confirmed').order_by('timestamp')
        serializer = RSVPSerializer(rsvps, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def waitlist(self, request, pk=None):
        """Get waitlist for a specific event"""
        event = self.get_object()
        
        # Check if attendee list is public
        if not event.attendee_list_public and not request.user.is_authenticated:
            return Response(
                {'error': 'Attendee list is not public for this event'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        rsvps = event.rsvps.filter(status='waitlisted').order_by('timestamp')
        serializer = RSVPSerializer(rsvps, many=True)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        operation_description="Look up users for events with public registration",
        manual_parameters=[
            openapi.Parameter('q', openapi.IN_QUERY, description="Search query (minimum 2 characters)", type=openapi.TYPE_STRING, required=True),
            openapi.Parameter('limit', openapi.IN_QUERY, description="Maximum number of results (default: 10, max: 50)", type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter('type', openapi.IN_QUERY, description="Search type: all, username, display_name, discord, telegram", type=openapi.TYPE_STRING, required=False),
        ],
        responses={
            200: openapi.Response('Success', UserLookupSerializer(many=True)),
            400: 'Bad Request - Invalid query parameters',
            403: 'Forbidden - Event does not have public registration'
        }
    )
    @action(detail=True, methods=['get'])
    def user_lookup(self, request, pk=None):
        """Look up users for events with public registration"""
        event = self.get_object()
        
        # Check if this event has public registration (attendee list is public)
        if not event.attendee_list_public:
            return Response(
                {'error': 'User lookup is only available for events with public registration'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get query parameters
        query = request.query_params.get('q', '').strip()
        limit = min(int(request.query_params.get('limit', 10)), 50)  # Max 50 results
        search_type = request.query_params.get('type', 'all')  # all, username, display_name, discord, telegram
        
        if not query or len(query) < 2:
            return Response(
                {'error': 'Query parameter "q" is required and must be at least 2 characters'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Build the search query based on search type
        if search_type == 'username':
            users = User.objects.filter(username__icontains=query)
        elif search_type == 'display_name':
            users = User.objects.filter(profile__display_name__icontains=query)
        elif search_type == 'discord':
            users = User.objects.filter(profile__discord_username__icontains=query)
        elif search_type == 'telegram':
            users = User.objects.filter(profile__telegram_username__icontains=query)
        else:  # 'all' - search across all fields
            users = User.objects.filter(
                Q(username__icontains=query) |
                Q(profile__display_name__icontains=query) |
                Q(profile__discord_username__icontains=query) |
                Q(profile__telegram_username__icontains=query)
            ).distinct()
        
        # Apply limit and order by username
        users = users.order_by('username')[:limit]
        
        serializer = UserLookupSerializer(users, many=True)
        return Response({
            'query': query,
            'search_type': search_type,
            'results': serializer.data,
            'count': len(serializer.data),
            'event_id': event.id,
            'event_title': event.title
        })
    
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """Get upcoming events"""
        now = timezone.now()
        events = self.get_queryset().filter(
            Q(date__gt=now.date()) | 
            (Q(date=now.date()) & Q(end_time__gt=now.time()))
        ).order_by('date', 'start_time')
        
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def today(self, request):
        """Get events happening today"""
        today = timezone.now().date()
        events = self.get_queryset().filter(date=today).order_by('start_time')
        
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)


class CustomAPIRootView(APIView):
    api_root_dict = None
    schema_urls = None

    @swagger_auto_schema(auto_schema=None)
    def get(self, request, *args, **kwargs):
        return render(request, 'rest_framework/api_root.html') 