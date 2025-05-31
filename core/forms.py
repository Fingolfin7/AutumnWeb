from django import forms
from .models import Projects, SubProjects, Sessions


class SearchProjectForm(forms.Form):
    project_name = forms.CharField(required=False, widget=forms.TextInput(
        attrs={
            'placeholder': 'Projects',
            'id': 'project-search',
            'data-ajax_url': '/api/search_projects/',
            'autocomplete': 'off'
        })
    )

    start_date = forms.DateField(required=False,
                                 widget=forms.DateInput(attrs={'type': 'date', 'placeholder': 'Start Date',
                                                               'id': 'start_date'}))

    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date','placeholder': 'End Date',
                                                                             'id': 'end_date'}))

    note_snippet = forms.CharField(required=False, widget=forms.TextInput(attrs={'placeholder': 'Note Snippet',
                                                                                 'id': 'note_snippet'}))



class CreateProjectForm(forms.ModelForm):
    class Meta:
        model = Projects
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Project Name', 'class': 'half-width'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'class': 'half-width', 'required': False}),
        }


class CreateSubProjectForm(forms.ModelForm):
    class Meta:
        model = SubProjects
        fields = ['name', 'description', 'parent_project']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Subproject Name'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'required': False}),
            'parent_project': forms.TextInput(attrs={'id': 'parent_project', 'hidden': True}),
        }


class UpdateProjectForm(forms.ModelForm):
    class Meta:
        model = Projects
        fields = ['name', 'description', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Project Name', 'class': 'half-width'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'class': 'half-width',
                                                 'required': False}),
            'status': forms.Select(attrs={'placeholder': 'Status', 'class': 'half-width'}),
        }


class UpdateSubProjectForm(forms.ModelForm):
    class Meta:
        model = SubProjects
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Subproject Name'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'required': False}),
        }


class UpdateSessionForm(forms.ModelForm):
    project_name = forms.CharField(required=False, widget=forms.TextInput(
        attrs={
            'placeholder': 'Projects',
            'id': 'project-search',
            'data-ajax_url': '/api/search_projects/',
            'class': 'half-width',
            'autocomplete': 'off'
        })
    )

    class Meta:
        model = Sessions
        fields = ['start_time', 'end_time', 'note']
        widgets = {
            'note': forms.Textarea(attrs={'placeholder': 'Note', 'class': 'half-width', 'required': False}),
        }


class ImportJSONForm(forms.Form):
    file = forms.FileField()
    autumn_import = forms.BooleanField(required=False, initial=False)
    force = forms.BooleanField(required=False, initial=False)
    merge = forms.BooleanField(required=False, initial=True)
    tolerance = forms.FloatField(initial=0.5, label='Tolerance (minutes)')
    verbose = forms.BooleanField(required=False)

    class Meta:
        fields = ['file', 'autumn_import', 'force', 'merge', 'tolerance', 'verbose']
        widgets = {
            'file': forms.FileInput(attrs={'accept': '.json'}),
        }


class ExportJSONForm(forms.Form):
    project_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Projects (leave blank to export all)',
                'id': 'project-search',
                'data-ajax_url': '/api/search_projects/',
                'class': 'half-width',
                'autocomplete': 'off',
            }
        )
    )

    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'half-width',
                'placeholder': 'Start date (optional)',
                'id': 'export-start-date',
            }
        )
    )

    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'half-width',
                'placeholder': 'End date (optional)',
                'id': 'export-end-date',
            }
        )
    )

    output_file = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Filename (leave blank to use default)',
                'class': 'half-width',
            }
        )
    )
    autumn_compatible = forms.BooleanField(required=False, initial=False)
    compress = forms.BooleanField(required=False, initial=False)
