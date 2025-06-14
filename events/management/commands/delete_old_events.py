from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, datetime
from events.models import Event

class Command(BaseCommand):
    help = 'Deletes events that ended more than 48 hours ago.'

    def handle(self, *args, **options):
        threshold_datetime = timezone.now() - timedelta(hours=48)

        # Filter events by combining their date and end_time into a single datetime for comparison
        # This approach iterates through events, which is safer for datetime comparisons in Python
        # If you have a very large number of events, a database-specific function for combining date/time
        # fields within the ORM query might be more efficient, but this is broadly compatible.
        events_to_delete_pks = []
        for event in Event.objects.all():
            event_end_datetime = datetime.combine(event.date, event.end_time)
            # Make event_end_datetime timezone-aware if USE_TZ is True in settings
            if timezone.is_aware(threshold_datetime):
                event_end_datetime = timezone.make_aware(event_end_datetime, timezone.get_current_timezone())

            if event_end_datetime < threshold_datetime:
                events_to_delete_pks.append(event.pk)

        deleted_count, _ = Event.objects.filter(pk__in=events_to_delete_pks).delete()

        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {deleted_count} old events.'))