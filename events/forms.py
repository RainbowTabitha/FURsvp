from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from events.models import Event, Group, RSVP
from users.models import Profile, GroupDelegation
from tinymce.widgets import TinyMCE

class UserRegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'email']

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['is_approved_organizer']

class EventForm(forms.ModelForm):
    description = forms.CharField(widget=TinyMCE(attrs={'cols': 80, 'rows': 30}))
    
    class Meta:
        model = Event
        fields = ['title', 'group', 'description', 'date', 'start_time', 'end_time', 'address', 'city', 'state']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Event Title'}),
            'group': forms.Select(attrs={'class': 'form-select', 'placeholder': 'Select Group'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'placeholder': 'Event Date'}),
            'start_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time', 'placeholder': 'Start Time'}),
            'end_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time', 'placeholder': 'End Time'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Street Address'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City/Town'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State/Province'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        instance = kwargs.get('instance', None)
        super().__init__(*args, **kwargs)

        if user:
            # Initialize empty querysets
            allowed_groups = Group.objects.none()
            assistant_groups = Group.objects.none()
            
            # Admins can see all groups
            if user.is_superuser:
                self.fields['group'].queryset = Group.objects.all()
                return
            
            # For editing an existing event
            if instance:
                # If user is the organizer, they can only select from their allowed groups
                if instance.organizer == user:
                    try:
                        if user.profile.is_approved_organizer:
                            allowed_groups = user.profile.allowed_groups.all()
                    except Profile.DoesNotExist:
                        pass
                # If user is an assistant, they can only select from groups they're an assistant for
                else:
                    assistant_groups = Group.objects.filter(
                        groupdelegation__delegated_user=user,
                        groupdelegation__organizer=instance.organizer
                    )
            # For creating a new event
            else:
                # Check for approved organizer status
                try:
                    if user.profile.is_approved_organizer:
                        allowed_groups = user.profile.allowed_groups.all()
                except Profile.DoesNotExist:
                    pass
                
                # Check for assistant status
                assistant_groups = Group.objects.filter(
                    groupdelegation__delegated_user=user
                )
            
            # Combine querysets with consistent distinct settings
            combined_groups = Group.objects.filter(
                id__in=allowed_groups.values_list('id', flat=True) | 
                      assistant_groups.values_list('id', flat=True)
            ).distinct()
            
            if combined_groups.exists():
                self.fields['group'].queryset = combined_groups
            else:
                self.fields['group'].queryset = Group.objects.none()
        else:
            self.fields['group'].queryset = Group.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data

class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name']

class RenameGroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name']

class RSVPForm(forms.ModelForm):
    class Meta:
        model = RSVP
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={
                'class': 'form-select',
                'onchange': 'this.form.submit()'
            })
        }