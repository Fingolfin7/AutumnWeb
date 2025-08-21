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

    class Meta:
        model = Profile
        fields = ['image', 'automatic_background','background_image', 'remove_background_image']