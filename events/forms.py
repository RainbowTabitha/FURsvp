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
    capacity = forms.IntegerField(
        required=False,
        label='Capacity',
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank for no limit'})
    )
    
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
    start_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        input_formats=['%H:%M', '%I:%M %p', '%I:%M%p']
    )
    end_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        input_formats=['%H:%M', '%I:%M %p', '%I:%M%p']
    )
    
    class Meta:
        model = Event
        fields = [
            'title', 'group', 'date', 'start_time', 'end_time',
            'address', 'city', 'state', 'age_restriction', 'description',
            'capacity', 'waitlist_enabled', 'attendee_list_public', 'enable_rsvp_questions',
            'question1_text', 'question2_text', 'question3_text',
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
            'waitlist_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'attendee_list_public': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_rsvp_questions': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'question1_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'RSVP Question 1'}),
            'question2_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'RSVP Question 2'}),
            'question3_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'RSVP Question 3'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        instance = kwargs.get('instance') or getattr(self, 'instance', None)
        super().__init__(*args, **kwargs)

        date_widget = self.fields['date'].widget
        time_widget = self.fields['start_time'].widget

        if not self.is_bound and instance and instance.pk:
            if instance.date:
                # Format for Flatpickr: m/d/Y (no leading zeros)
                self.initial['date'] = f"{instance.date.month}/{instance.date.day}/{instance.date.year}"
            if instance.start_time:
                self.initial['start_time'] = instance.start_time.strftime('%I:%M %p')
            if instance.end_time:
                self.initial['end_time'] = instance.end_time.strftime('%I:%M %p')

        if instance:
            self.fields['eula_agreement'].required = False
            self.fields['state_agreement'].required = False
        else:
            self.fields['eula_agreement'].required = True
            self.fields['state_agreement'].required = True

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
    question1 = forms.CharField(
        required=False,
        label='Question 1',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'maxlength': 1000, 'style': 'resize:vertical; max-height: 7.5em; min-height: 2.5em; overflow-y:auto; resize:vertical;'}),
        help_text='Your answer will only be visible to event organizers.'
    )
    question2 = forms.CharField(
        required=False,
        label='Question 2',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'maxlength': 1000, 'style': 'resize:vertical; max-height: 7.5em; min-height: 2.5em; overflow-y:auto; resize:vertical;'}),
        help_text='Your answer will only be visible to event organizers.'
    )
    question3 = forms.CharField(
        required=False,
        label='Question 3',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'maxlength': 1000, 'style': 'resize:vertical; max-height: 7.5em; min-height: 2.5em; overflow-y:auto; resize:vertical;'}),
        help_text='Your answer will only be visible to event organizers.'
    )
    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        
        # Get the base choices and filter out any existing empty choices
        base_choices = [choice for choice in list(self.fields['status'].choices) if choice[0] != '']
        
        # Add a custom empty choice at the beginning
        choices = base_choices
        
        # If event doesn't have waitlist enabled or capacity set, remove waitlisted option
        if self.event and (not self.event.waitlist_enabled or self.event.capacity is None):
            choices = [choice for choice in choices if choice[0] != 'waitlisted']
            
        self.fields['status'].choices = choices
        
        # Explicitly set empty_label to None to prevent Django from adding another blank choice
        self.fields['status'].empty_label = None
        
        # Set initial value to empty string if no existing RSVP instance or status
        if not self.instance or not getattr(self.instance, 'status', None):
            self.initial['status'] = ''

        # Only show question fields if the event has text for them
        if self.event:
            if not getattr(self.event, 'question1_text', '').strip():
                self.fields.pop('question1', None)
            if not getattr(self.event, 'question2_text', '').strip():
                self.fields.pop('question2', None)
            if not getattr(self.event, 'question3_text', '').strip():
                self.fields.pop('question3', None)

    class Meta:
        model = RSVP
        fields = ['status', 'question1', 'question2', 'question3']
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