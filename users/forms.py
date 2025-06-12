from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from events.models import Event, Group
from users.models import Profile, GroupDelegation

class UserRegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'email']

class UserProfileForm(forms.ModelForm):
    allowed_groups = forms.ModelMultipleChoiceField(queryset=Group.objects.all(), required=False)
    clear_profile_picture = forms.BooleanField(required=False, label="Remove Profile Picture")
    is_approved_organizer = forms.BooleanField(required=False, label="Approved Organizer")

    class Meta:
        model = Profile
        fields = ['display_name', 'is_approved_organizer', 'allowed_groups', 'profile_picture_base64', 'discord_username', 'telegram_username']
        widgets = {
            'display_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your display name'
            }),
            'is_approved_organizer': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'discord_username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your Discord username'
            }),
            'telegram_username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your Telegram username'
            }),
            'profile_picture_base64': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            if self.instance.profile_picture_base64:
                self.initial['profile_picture_base64'] = self.instance.profile_picture_base64
            if self.instance.allowed_groups.exists():
                self.initial['allowed_groups'] = self.instance.allowed_groups.all()

class UserPublicProfileForm(forms.ModelForm):
    clear_profile_picture = forms.BooleanField(required=False, label="Remove Profile Picture")

    class Meta:
        model = Profile
        fields = ['display_name', 'discord_username', 'telegram_username', 'profile_picture_base64']
        widgets = {
            'display_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your display name'
            }),
            'discord_username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your Discord username'
            }),
            'telegram_username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your Telegram username'
            }),
            'profile_picture_base64': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.profile_picture_base64:
            self.initial['profile_picture_base64'] = self.instance.profile_picture_base64

class UserAdminProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['is_approved_organizer', 'allowed_groups']
        widgets = {
            'is_approved_organizer': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'allowed_groups': forms.SelectMultiple(attrs={
                'class': 'form-select tomselect-allowed-groups',
                'placeholder': 'Select groups'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.allowed_groups.exists():
            self.initial['allowed_groups'] = self.instance.allowed_groups.all()

class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'group', 'date', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user and hasattr(user, 'profile') and user.profile.is_approved_organizer:
            self.fields['group'].queryset = user.profile.allowed_groups.all()
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

class AssistantAssignmentForm(forms.ModelForm):
    delegated_user = forms.ModelChoiceField(queryset=User.objects.filter(is_superuser=False).exclude(id=None), label="Assign User as Assistant")
    group = forms.ModelChoiceField(queryset=Group.objects.all(), label="For Group")

    class Meta:
        model = GroupDelegation
        fields = ['delegated_user', 'group']

    def __init__(self, *args, **kwargs):
        organizer_profile = kwargs.pop('organizer_profile', None)
        super().__init__(*args, **kwargs)
        if organizer_profile:
            self.fields['group'].queryset = organizer_profile.allowed_groups.all()
        
        # Filter out the organizer themselves from the delegated_user choices
        if organizer_profile and organizer_profile.user:
            self.fields['delegated_user'].queryset = self.fields['delegated_user'].queryset.exclude(id=organizer_profile.user.id) 