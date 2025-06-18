from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from events.models import Event, Group, RSVP
from users.models import Profile, GroupDelegation, GroupRole
from tinymce.widgets import TinyMCE

class UserRegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'email']

class EventForm(forms.ModelForm):
    AGE_CHOICES = [
        ('none', 'No age restriction'),
        ('adult', '18+ (Adult)'),
        ('mature', '21+ (Mature)'),
    ]
    age_restriction = forms.ChoiceField(
        choices=AGE_CHOICES,
        required=True,
        label='Age Restriction',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    description = forms.CharField(widget=TinyMCE(attrs={'cols': 80, 'rows': 30}))
    
    # Add new checkbox fields
    eula_agreement = forms.BooleanField(
        required=True,
        label='I agree to the End User License Agreement (EULA)',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    state_agreement = forms.BooleanField(
        required=True,
        label='I confirm that this event is located in the same state as this FURsvp instance',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    class Meta:
        model = Event
        fields = [
            'title', 'group', 'date', 'start_time', 'end_time',
            'address', 'city', 'state', 'age_restriction', 'description',
            'capacity', 'waitlist_enabled'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Event Title'}),
            'group': forms.Select(attrs={'class': 'form-select', 'placeholder': 'Select Group'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank for no limit'}),
            'waitlist_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        instance = kwargs.get('instance', None)
        super().__init__(*args, **kwargs)

        if user:
            # Initialize empty querysets
            leader_groups = Group.objects.filter(group_roles__user=user)
            assistant_groups = Group.objects.none()
            
            # Admins can see all groups
            if user.is_superuser:
                self.fields['group'].queryset = Group.objects.all()
                return
            
            # For editing an existing event
            if instance:
                # If user is the organizer, they can only select from their leader groups
                if instance.organizer == user:
                    leader_groups = Group.objects.filter(group_roles__user=user)
                # If user is an assistant, they can only select from groups they're an assistant for
                else:
                    assistant_groups = Group.objects.filter(
                        groupdelegation__delegated_user=user,
                        groupdelegation__organizer=instance.organizer
                    )
            # For creating a new event
            else:
                leader_groups = Group.objects.filter(group_roles__user=user)
                assistant_groups = Group.objects.filter(
                    groupdelegation__delegated_user=user
                )
            # Combine querysets
            combined_groups = Group.objects.filter(
                id__in=leader_groups.values_list('id', flat=True) |
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
        waitlist_enabled = cleaned_data.get('waitlist_enabled')
        capacity = cleaned_data.get('capacity')

        if waitlist_enabled and not capacity:
            self.add_error('waitlist_enabled', 'Capacity must be set when waitlist is enabled.')
            self.add_error('capacity', 'Capacity must be set when waitlist is enabled.')
        
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.clean()  # Call the model's clean method
        if commit:
            instance.save()
        return instance

class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name']

class RenameGroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name']

class RSVPForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        
        # Get the base choices and filter out any existing empty choices
        base_choices = [choice for choice in list(self.fields['status'].choices) if choice[0] != '']
        
        # Add a custom empty choice at the beginning
        choices = [('', '--- Select RSVP Status ---')] + base_choices
        
        # If event doesn't have waitlist enabled or capacity set, remove waitlisted option
        if self.event and (not self.event.waitlist_enabled or self.event.capacity is None):
            choices = [choice for choice in choices if choice[0] != 'waitlisted']
            
        self.fields['status'].choices = choices
        
        # Explicitly set empty_label to None to prevent Django from adding another blank choice
        self.fields['status'].empty_label = None
        
        # Set initial value to empty string if no existing RSVP instance or status
        self.initial['status'] = ''

    class Meta:
        model = RSVP
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={
                'class': 'form-select',
                'onchange': 'this.form.submit()'
            })
        }

class GroupRoleForm(forms.ModelForm):
    class Meta:
        model = GroupRole
        fields = ['user', 'custom_label', 'can_post', 'can_manage_leadership']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select tomselect-user'}),
            'custom_label': forms.TextInput(attrs={'class': 'form-control'}),
            'can_post': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'can_manage_leadership': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        group = kwargs.pop('group', None)
        super().__init__(*args, **kwargs)
        self.fields['custom_label'].required = True
        if group:
            existing_users = GroupRole.objects.filter(group=group).values_list('user_id', flat=True)
            self.fields['user'].queryset = User.objects.exclude(id__in=existing_users)