from django import forms
from .models import *
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UsernameField


class UserRegisterForm(UserCreationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'Username', 'class': 'full-width'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'placeholder': 'example@domain.com', 'class': 'full-width'}),)
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Enter Password', 'class': 'full-width'}))
    password2 = forms.CharField(label='Confirm Password',
                                widget=forms.PasswordInput(attrs={
                                    'placeholder': 'Confirm Password',
                                    'class': 'full-width'
                                }))

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']


class UserLoginForm(AuthenticationForm):
    username = UsernameField(widget=forms.TextInput(attrs={'placeholder': 'Username or Email', 'class': 'full-width'}),
                             label="Username or Email")
    password = forms.CharField(widget=forms.PasswordInput(
        attrs={'placeholder': 'Enter Password', 'class': 'full-width', 'autocomplete': 'on', 'id': 'password'}),
        label="Enter Password")


class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['username', 'email']


class ProfileUpdateForm(forms.ModelForm):
    image = forms.ImageField(widget=forms.FileInput(), required=False)
    automatic_background = forms.BooleanField(required=False, label='Automatically Set Background Image')
    background_dimming = forms.IntegerField(
        min_value=0,
        max_value=85,
        required=False,
        label='Background Dimming',
        widget=forms.NumberInput(attrs={
            'type': 'range',
            'min': '0',
            'max': '85',
            'step': '5',
            'class': 'background-dimming-slider',
        }),
    )

    BACKGROUND_CHOICES = [
        ('bing', 'Use Bing Wallpaper as Background'),
        ('nasa', 'Use NASA APOD as Background'),
    ]
    background_choice = forms.ChoiceField(
        choices=BACKGROUND_CHOICES,
        widget=forms.RadioSelect,
        required=False,
    )

    background_image = forms.ImageField(label='Background Image', required=False, widget=forms.FileInput())
    remove_background_image = forms.BooleanField(required=False, label='Remove current background image')
    default_filter_value = forms.IntegerField(
        min_value=1,
        max_value=1000,
        required=False,
        label='Default date range',
        widget=forms.NumberInput(attrs={
            'min': '1',
            'max': '1000',
            'class': 'profile-default-number',
        }),
    )
    default_filter_unit = forms.ChoiceField(
        choices=DEFAULT_FILTER_UNIT_CHOICES,
        required=False,
        label='Date range unit',
        widget=forms.Select(attrs={'class': 'profile-default-select'}),
    )
    insights_default_filter_value = forms.IntegerField(
        min_value=1,
        max_value=1000,
        required=False,
        label='Insights date range',
        widget=forms.NumberInput(attrs={
            'min': '1',
            'max': '1000',
            'class': 'profile-default-number',
        }),
    )
    insights_default_filter_unit = forms.ChoiceField(
        choices=DEFAULT_FILTER_UNIT_CHOICES,
        required=False,
        label='Insights date range unit',
        widget=forms.Select(attrs={'class': 'profile-default-select'}),
    )
    default_chart_project_count = forms.IntegerField(
        min_value=1,
        max_value=100,
        required=False,
        label='Projects per chart',
        widget=forms.NumberInput(attrs={
            'min': '1',
            'max': '100',
            'class': 'profile-default-number',
        }),
    )

    # New API key fields (write-only)
    gemini_api_key = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False, attrs={'placeholder': 'Gemini API Key', 'autocomplete': 'new-password'}))
    openai_api_key = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False, attrs={'placeholder': 'OpenAI API Key', 'autocomplete': 'new-password'}))
    claude_api_key = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False, attrs={'placeholder': 'Claude API Key', 'autocomplete': 'new-password'}))
    clear_gemini_api_key = forms.BooleanField(required=False, label='Clear Gemini Key')
    clear_openai_api_key = forms.BooleanField(required=False, label='Clear OpenAI Key')
    clear_claude_api_key = forms.BooleanField(required=False, label='Clear Claude Key')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Explicitly set API key fields to empty to prevent any autopopulation
        self.fields['gemini_api_key'].initial = ''
        self.fields['openai_api_key'].initial = ''
        self.fields['claude_api_key'].initial = ''

    def clean_background_dimming(self):
        value = self.cleaned_data.get('background_dimming')
        if value is not None:
            return value
        if self.instance and self.instance.pk:
            return self.instance.background_dimming
        return self._meta.model._meta.get_field('background_dimming').default

    def _preserve_profile_default(self, field_name):
        value = self.cleaned_data.get(field_name)
        if value not in (None, ''):
            return value
        if self.instance and self.instance.pk:
            return getattr(self.instance, field_name)
        return self._meta.model._meta.get_field(field_name).default

    def clean_default_filter_value(self):
        return self._preserve_profile_default('default_filter_value')

    def clean_default_filter_unit(self):
        return self._preserve_profile_default('default_filter_unit')

    def clean_insights_default_filter_value(self):
        return self._preserve_profile_default('insights_default_filter_value')

    def clean_insights_default_filter_unit(self):
        return self._preserve_profile_default('insights_default_filter_unit')

    def clean_default_chart_project_count(self):
        return self._preserve_profile_default('default_chart_project_count')

    class Meta:
        model = Profile
        fields = ['image', 'automatic_background', 'background_dimming', 'background_image', 'remove_background_image',
                  'default_filter_value', 'default_filter_unit',
                  'insights_default_filter_value', 'insights_default_filter_unit',
                  'default_chart_project_count',
                  'gemini_api_key', 'openai_api_key', 'claude_api_key',
                  'clear_gemini_api_key', 'clear_openai_api_key', 'clear_claude_api_key']
