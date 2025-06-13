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
    description = forms.CharField(widget=forms.Textarea(attrs={
        'class': 'form-control',
        'id': 'event-description',
        'rows': 15
    }))
    
    class Meta:
        model = Event
        fields = ['title', 'group', 'date', 'start_time', 'end_time', 'description']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter event title'
            }),
            'group': forms.Select(attrs={
                'class': 'form-select'
            }),
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'start_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'form-control'
            }),
            'end_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'form-control'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            # Initialize empty querysets
            allowed_groups = Group.objects.none()
            assistant_groups = Group.objects.none()
            
            # Admins can see all groups
            if user.is_superuser:
                self.fields['group'].queryset = Group.objects.all()
                return
            
            # Check for approved organizer status
            try:
                if user.profile.is_approved_organizer:
                    allowed_groups = user.profile.allowed_groups.all()
            except Profile.DoesNotExist:
                pass
            
            # Check for assistant status
            assistant_groups = Group.objects.filter(
                groupdelegation__delegated_user=user
            ).distinct()
            
            # Combine querysets
            combined_groups = (allowed_groups | assistant_groups).distinct()
            
            if combined_groups.exists():
                self.fields['group'].queryset = combined_groups
            else:
                self.fields['group'].queryset = Group.objects.none()
        else:
            self.fields['group'].queryset = Group.objects.none()

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