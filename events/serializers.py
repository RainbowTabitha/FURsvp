from rest_framework import serializers
from .models import Group, Event, RSVP
from django.contrib.auth.models import User
from datetime import datetime
from django.utils import timezone


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model (organizer info)"""
    display_name = serializers.CharField(source='username', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'display_name']


class GroupSerializer(serializers.ModelSerializer):
    """Serializer for Group model"""
    class Meta:
        model = Group
        fields = [
            'id', 'name', 'description', 'website', 
            'contact_email', 'telegram_channel'
        ]


class EventSerializer(serializers.ModelSerializer):
    """Serializer for Event model with basic info"""
    group = GroupSerializer(read_only=True)
    start_timestamp = serializers.SerializerMethodField()
    end_timestamp = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'title', 'group', 'date', 'start_time', 'end_time',
            'start_timestamp', 'end_timestamp', 'description', 'address', 'city', 'state',
            'status', 'age_restriction', 'capacity', 'waitlist_enabled',
            'attendee_list_public', 'enable_rsvp_questions'
        ]
    
    def get_start_timestamp(self, obj):
        """Get ISO-8601 timestamp for start time"""
        if obj.date and obj.start_time:
            dt = datetime.combine(obj.date, obj.start_time)
            # Make timezone-aware if Django is configured for timezones
            if timezone.is_aware(timezone.now()):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt.isoformat()
        return None
    
    def get_end_timestamp(self, obj):
        """Get ISO-8601 timestamp for end time"""
        if obj.date and obj.end_time:
            dt = datetime.combine(obj.date, obj.end_time)
            # Make timezone-aware if Django is configured for timezones
            if timezone.is_aware(timezone.now()):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt.isoformat()
        return None


class EventDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for Event model with additional info"""
    group = GroupSerializer(read_only=True)
    attendee_count = serializers.SerializerMethodField()
    waitlist_count = serializers.SerializerMethodField()
    start_timestamp = serializers.SerializerMethodField()
    end_timestamp = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'title', 'group', 'date', 'start_time', 'end_time',
            'start_timestamp', 'end_timestamp', 'description', 'address', 'city', 'state',
            'status', 'age_restriction', 'capacity', 'waitlist_enabled',
            'attendee_list_public', 'enable_rsvp_questions',
            'attendee_count', 'waitlist_count'
        ]
    
    def get_attendee_count(self, obj):
        """Get count of confirmed attendees"""
        return obj.rsvps.filter(status='confirmed').count()
    
    def get_waitlist_count(self, obj):
        """Get count of waitlisted attendees"""
        return obj.rsvps.filter(status='waitlisted').count()
    
    def get_start_timestamp(self, obj):
        """Get ISO-8601 timestamp for start time"""
        if obj.date and obj.start_time:
            dt = datetime.combine(obj.date, obj.start_time)
            # Make timezone-aware if Django is configured for timezones
            if timezone.is_aware(timezone.now()):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt.isoformat()
        return None
    
    def get_end_timestamp(self, obj):
        """Get ISO-8601 timestamp for end time"""
        if obj.date and obj.end_time:
            dt = datetime.combine(obj.date, obj.end_time)
            # Make timezone-aware if Django is configured for timezones
            if timezone.is_aware(timezone.now()):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt.isoformat()
        return None


class RSVPSerializer(serializers.ModelSerializer):
    """Serializer for RSVP model"""
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = RSVP
        fields = [
            'id', 'user', 'name', 'timestamp', 'status',
            'question1', 'question2', 'question3'
        ]
        read_only_fields = ['timestamp'] 