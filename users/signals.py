from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import Profile, GroupRole

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_profile(sender, instance, **kwargs):
    instance.profile.save()

# Signal to update GroupRole.can_post when is_approved_organizer changes
@receiver(post_save, sender=Profile)
def update_group_roles_can_post(sender, instance, **kwargs):
    for grouprole in GroupRole.objects.filter(user=instance.user):
        grouprole.save() 