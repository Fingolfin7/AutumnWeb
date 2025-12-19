from django import forms
from .models import Projects, SubProjects, Sessions, Context, Tag


class SearchProjectForm(forms.Form):
    project_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Projects',
                'id': 'project-search',
                'data-ajax_url': '/api/search_projects/',
                'autocomplete': 'off',
            }
        ),
    )

    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'placeholder': 'Start Date',
                'id': 'start_date',
            }
        ),
    )

    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'placeholder': 'End Date',
                'id': 'end_date',
            }
        ),
    )

    note_snippet = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Note Snippet',
                'id': 'note_snippet',
            }
        ),
    )

    context = forms.ChoiceField(
        required=False,
        choices=[],
        widget=forms.Select(
            attrs={
                'id': 'context-filter',
            }
        ),
    )

    tags = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Tag.objects.none(),
        widget=forms.CheckboxSelectMultiple(
            attrs={
                'id': 'tag-filter',
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Populate context choices per user
        choices = [('', 'All Contexts')]
        if user is not None:
            user_contexts = Context.objects.filter(user=user).order_by('name')

            # Pin "General" directly under "All Contexts" when present.
            general_ctx = None
            remaining_contexts = []
            for ctx in user_contexts:
                if ctx.name == 'General' and general_ctx is None:
                    general_ctx = ctx
                else:
                    remaining_contexts.append(ctx)

            if general_ctx is not None:
                choices.append((str(general_ctx.id), general_ctx.name))

            choices += [(str(ctx.id), ctx.name) for ctx in remaining_contexts]

            self.fields['tags'].queryset = Tag.objects.filter(user=user).order_by('name')
        self.fields['context'].choices = choices



class CreateProjectForm(forms.ModelForm):
    class Meta:
        model = Projects
        fields = ['name', 'description', 'context', 'tags']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Project Name', 'class': 'half-width'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'class': 'half-width', 'required': False}),
            'context': forms.Select(attrs={'class': 'half-width'}),
            'tags': forms.CheckboxSelectMultiple(),  # ✅ updated
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['context'].queryset = Context.objects.filter(user=user).order_by('name')
            self.fields['tags'].queryset = Tag.objects.filter(user=user).order_by('name')

            # Default to the user's "General" context (created by migration 0030 for existing data)
            general = Context.objects.filter(user=user, name='General').first()
            if general is not None and not self.initial.get('context'):
                self.initial['context'] = general


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
        fields = ['name', 'description', 'status', 'context', 'tags']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Project Name', 'class': 'half-width'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'class': 'half-width', 'required': False}),
            'status': forms.Select(attrs={'placeholder': 'Status', 'class': 'half-width'}),
            'context': forms.Select(attrs={'class': 'half-width'}),
            'tags': forms.CheckboxSelectMultiple(),  # ✅ updated
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['context'].queryset = Context.objects.filter(user=user).order_by('name')
            self.fields['tags'].queryset = Tag.objects.filter(user=user).order_by('name')

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

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        if start_time and end_time and end_time < start_time:
            self.add_error('end_time', "End time cannot be earlier than start time.")

        return cleaned_data


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


class MergeProjectsForm(forms.Form):
    project1 = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Select first project',
                'id': 'project1-search',
                'data-ajax_url': '/api/search_projects/',
                'class': 'half-width',
                'autocomplete': 'off',
            }
        )
    )
    
    project2 = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Select second project',
                'id': 'project2-search',
                'data-ajax_url': '/api/search_projects/',
                'class': 'half-width',
                'autocomplete': 'off',
            }
        )
    )
    
    new_project_name = forms.CharField(
        required=True,
        max_length=255,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Enter name for merged project',
                'class': 'half-width',
            }
        )
    )
    
    def clean(self):
        cleaned_data = super().clean()
        project1_name = cleaned_data.get('project1')
        project2_name = cleaned_data.get('project2')
        new_name = cleaned_data.get('new_project_name')
        
        if project1_name and project2_name and project1_name == project2_name:
            raise forms.ValidationError("Cannot merge a project with itself.")
            
        return cleaned_data


class MergeSubProjectsForm(forms.Form):
    subproject1 = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Select first subproject',
                'id': 'subproject1-search',
                'data-ajax_url': '/api/search_subprojects/',
                'class': 'half-width',
                'autocomplete': 'off',
            }
        )
    )
    
    subproject2 = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Select second subproject',
                'id': 'subproject2-search',
                'data-ajax_url': '/api/search_subprojects/',
                'class': 'half-width',
                'autocomplete': 'off',
            }
        )
    )
    
    new_subproject_name = forms.CharField(
        required=True,
        max_length=255,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Enter name for merged subproject',
                'class': 'half-width',
            }
        )
    )
    
    def clean(self):
        cleaned_data = super().clean()
        subproject1_name = cleaned_data.get('subproject1')
        subproject2_name = cleaned_data.get('subproject2')
        new_name = cleaned_data.get('new_subproject_name')
        
        if subproject1_name and subproject2_name and subproject1_name == subproject2_name:
            raise forms.ValidationError("Cannot merge a subproject with itself.")
            
        return cleaned_data


class ContextForm(forms.ModelForm):
    class Meta:
        model = Context
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Context Name', 'class': 'half-width'}),
            'description': forms.Textarea(attrs={'placeholder': 'Description', 'class': 'half-width', 'required': False}),
        }


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ['name', 'color']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Tag Name', 'class': 'half-width'}),
            'color': forms.TextInput(attrs={'placeholder': 'Optional color (e.g. #ff0000 or label)', 'class': 'half-width'}),
        }