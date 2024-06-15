from django import forms
from .models import *


class SearchProjectForm(forms.Form):
    project_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'placeholder': 'Project Name'}))

    start_date = forms.DateField(required=False,
                                 widget=forms.DateInput(attrs={'type': 'date', 'placeholder': 'Start Date'}))

    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date','placeholder': 'End Date'}))

    status = forms.ChoiceField(required=False, choices=status_choices,
                               widget=forms.Select(attrs={'placeholder': 'Status'}))

