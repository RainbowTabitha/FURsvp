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

from .models import Group, Event, RSVP
from .serializers import (
    GroupSerializer, EventSerializer, EventDetailSerializer, RSVPSerializer
)


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
        
        # Filter by event type (upcoming/past)
        event_type = self.request.query_params.get('type', None)
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

    def get(self, request, *args, **kwargs):
        return render(request, 'rest_framework/api_root.html') 