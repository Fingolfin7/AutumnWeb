from django import forms
from .models import *


class SearchProjectForm(forms.Form):
    project_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'placeholder': 'Project Name'}))

    start_date = forms.DateField(required=False,
                                 widget=forms.DateInput(attrs={'type': 'date', 'placeholder': 'Start Date'}))

    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date','placeholder': 'End Date'}))

    status = forms.ChoiceField(required=False, choices=status_choices,
                               widget=forms.Select(attrs={'placeholder': 'Status'}))


class CreateProjectForm(forms.ModelForm):
    class Meta:
        model = Projects
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Project Name'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'required': False}),
        }


class CreateSubProjectForm(forms.ModelForm):
    class Meta:
        model = SubProjects
        fields = ['name', 'description', 'parent_project']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Subproject Name'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'required': False}),
            'parent_project': forms.TextInput(attrs={'placeholder': 'Parent Project', 'id': 'parent_project',
                                                     'hidden': True}),
            # we'll use the project search.js script for this
        }


class UpdateProjectForm(forms.ModelForm):
    class Meta:
        model = Projects
        fields = ['name', 'description', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Project Name'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'required': False}),
            'status': forms.Select(attrs={'placeholder': 'Status'}),
        }


class UpdateSubProjectForm(forms.ModelForm):
    class Meta:
        model = SubProjects
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Subproject Name'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'required': False}),
        }