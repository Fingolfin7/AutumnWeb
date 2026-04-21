from django import forms
from django.utils import timezone
from .models import Projects, SubProjects, Sessions, Context, Tag, Commitment
from typing import cast


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

    exclude_projects = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Projects.objects.none(),
        widget=forms.CheckboxSelectMultiple(
            attrs={
                'id': 'exclude-projects-filter',
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

            tags_field = cast(forms.ModelMultipleChoiceField, self.fields['tags'])
            tags_field.queryset = Tag.objects.filter(user=user).order_by('name')
            tags_field.label_from_instance = lambda obj: obj.name
            exclude_field = cast(forms.ModelMultipleChoiceField, self.fields['exclude_projects'])
            exclude_field.queryset = Projects.objects.filter(user=user).order_by('name')
            exclude_field.label_from_instance = lambda obj: obj.name
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
            self.fields['tags'].label_from_instance = lambda obj: obj.name

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
            self.fields['tags'].label_from_instance = lambda obj: obj.name

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
            'start_time': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'half-width'},
                format='%Y-%m-%dT%H:%M',
            ),
            'end_time': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'half-width'},
                format='%Y-%m-%dT%H:%M',
            ),
            'note': forms.Textarea(attrs={'placeholder': 'Note', 'class': 'half-width', 'required': False}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_time'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        self.fields['end_time'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        if start_time and end_time and end_time < start_time:
            self.add_error('end_time', "End time cannot be earlier than start time.")

        return cleaned_data


class StopTimerForm(forms.ModelForm):
    class Meta:
        model = Sessions
        fields = ['start_time', 'end_time', 'note']
        widgets = {
            'start_time': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'half-width'},
                format='%Y-%m-%dT%H:%M',
            ),
            'end_time': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'half-width'},
                format='%Y-%m-%dT%H:%M',
            ),
            'note': forms.Textarea(
                attrs={
                    'placeholder': 'Session Note...',
                    'class': 'half-width',
                    'rows': 4,
                    'required': False,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_time'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        self.fields['end_time'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']

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

    import_context = forms.ModelChoiceField(
        required=False,
        queryset=Context.objects.none(),
        empty_label='(Use file context / default)',
        label='Import under context',
    )
    import_context_new = forms.CharField(
        required=False,
        label='Or create context',
        help_text='Optional. If provided, a new context will be created (or reused) and used for all imported projects.',
        widget=forms.TextInput(attrs={'placeholder': 'New context name'}),
    )

    class Meta:
        fields = [
            'file',
            'autumn_import',
            'force',
            'merge',
            'tolerance',
            'verbose',
            'import_context',
            'import_context_new',
        ]
        widgets = {
            'file': forms.FileInput(attrs={'accept': '.json'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None:
            cast(forms.ModelChoiceField, self.fields['import_context']).queryset = Context.objects.filter(user=user).order_by('name')

    def clean(self):
        cleaned = super().clean()
        new_name = (cleaned.get('import_context_new') or '').strip()
        if new_name:
            cleaned['import_context_new'] = new_name

        # If both are provided, keep behavior deterministic and tell the user.
        if cleaned.get('import_context') is not None and cleaned.get('import_context_new'):
            # New context name wins (matches import_stream precedence)
            self.add_error(
                'import_context',
                'Ignored because “Or create context” is filled. Clear it to use the dropdown context instead.',
            )

        return cleaned


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

    # New: optional export filters
    context = forms.ChoiceField(
        required=False,
        choices=[],
        widget=forms.Select(
            attrs={
                'id': 'export-context-filter',
                'class': 'half-width',
            }
        ),
    )

    tags = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Tag.objects.none(),
        widget=forms.CheckboxSelectMultiple(
            attrs={
                # Match manage-projects/search form so styling + any shared JS works the same.
                'id': 'tag-filter',
            }
        ),
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

    exclude_projects = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Projects.objects.none(),
        widget=forms.CheckboxSelectMultiple(
            attrs={
                'id': 'exclude-projects-filter',
            }
        ),
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

            tags_field = cast(forms.ModelMultipleChoiceField, self.fields['tags'])
            tags_field.queryset = Tag.objects.filter(user=user).order_by('name')
            tags_field.label_from_instance = lambda obj: obj.name
            exclude_field = cast(forms.ModelMultipleChoiceField, self.fields['exclude_projects'])
            exclude_field.queryset = Projects.objects.filter(user=user).order_by('name')
            exclude_field.label_from_instance = lambda obj: obj.name

        self.fields['context'].choices = choices


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


class CommitmentForm(forms.ModelForm):
    aggregation_type = forms.ChoiceField(
        choices=[('context', 'Context'), ('tag', 'Tag'), ('project', 'Project'), ('subproject', 'Subproject')],
        required=False,
        widget=forms.Select(attrs={'class': 'half-width'}),
    )
    project = forms.ModelChoiceField(queryset=Projects.objects.none(), required=False, widget=forms.Select(attrs={'class': 'half-width'}))
    subproject = forms.ModelChoiceField(queryset=SubProjects.objects.none(), required=False, widget=forms.Select(attrs={'class': 'half-width'}))
    context = forms.ModelChoiceField(queryset=Context.objects.none(), required=False, widget=forms.Select(attrs={'class': 'half-width'}))
    tag = forms.ModelChoiceField(queryset=Tag.objects.none(), required=False, widget=forms.Select(attrs={'class': 'half-width'}))
    include_projects = forms.ModelMultipleChoiceField(
        queryset=Projects.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    exclude_projects = forms.ModelMultipleChoiceField(
        queryset=Projects.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    include_subprojects = forms.ModelMultipleChoiceField(
        queryset=SubProjects.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    exclude_subprojects = forms.ModelMultipleChoiceField(
        queryset=SubProjects.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    include_contexts = forms.ModelMultipleChoiceField(
        queryset=Context.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    exclude_contexts = forms.ModelMultipleChoiceField(
        queryset=Context.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    include_tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    exclude_tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = Commitment
        fields = [
            'aggregation_type',
            'project',
            'subproject',
            'context',
            'tag',
            'include_projects',
            'exclude_projects',
            'include_subprojects',
            'exclude_subprojects',
            'include_contexts',
            'exclude_contexts',
            'include_tags',
            'exclude_tags',
            'commitment_type',
            'period',
            'start_date',
            'target',
            'banking_enabled',
            'max_balance',
            'min_balance',
        ]
        widgets = {
            'commitment_type': forms.Select(attrs={'class': 'half-width'}),
            'period': forms.Select(attrs={'class': 'half-width'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'half-width'}),
            'target': forms.NumberInput(attrs={'placeholder': 'Target amount', 'class': 'half-width', 'min': 1}),
            'max_balance': forms.NumberInput(attrs={'placeholder': 'Max balance cap', 'class': 'half-width', 'min': 0}),
            'min_balance': forms.NumberInput(attrs={'placeholder': 'Min balance cap', 'class': 'half-width', 'max': 0}),
            'banking_enabled': forms.CheckboxInput(),
        }
        labels = {
            'aggregation_type': 'Aggregation Type',
            'commitment_type': 'Commitment Type',
            'period': 'Period',
            'start_date': 'Start Date',
            'target': 'Target',
            'include_projects': 'Only include projects',
            'exclude_projects': 'Exclude projects',
            'include_subprojects': 'Only include subprojects',
            'exclude_subprojects': 'Exclude subprojects',
            'include_contexts': 'Only include contexts',
            'exclude_contexts': 'Exclude contexts',
            'include_tags': 'Only include tags',
            'exclude_tags': 'Exclude tags',
            'banking_enabled': 'Enable Time Banking',
            'max_balance': 'Max Balance (surplus cap)',
            'min_balance': 'Min Balance (deficit cap)',
        }
        help_texts = {
            'target': 'Minutes for time-based, count for session-based',
            'start_date': 'Commitment calculations begin from this date (inclusive).',
            'include_projects': 'If set, only sessions in these projects count.',
            'exclude_projects': 'Sessions in these projects never count.',
            'include_subprojects': 'If set, only sessions containing these subprojects count.',
            'exclude_subprojects': 'Sessions containing these subprojects are removed.',
            'include_contexts': 'If set, only sessions under projects in these contexts count.',
            'exclude_contexts': 'Sessions under projects in these contexts are removed.',
            'include_tags': 'If set, only sessions under projects with these tags count.',
            'exclude_tags': 'Sessions under projects with these tags are removed.',
            'max_balance': 'Maximum surplus that can be banked (in minutes or sessions)',
            'min_balance': 'Maximum deficit allowed (negative value)',
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.project_obj = kwargs.pop('project', None)
        super().__init__(*args, **kwargs)

        if self.user is not None and self.instance.user_id is None:
            self.instance.user = self.user

        if self.user is not None:
            self.fields['project'].queryset = Projects.objects.filter(user=self.user).order_by('name')
            self.fields['subproject'].queryset = SubProjects.objects.filter(user=self.user).order_by('name')
            self.fields['context'].queryset = Context.objects.filter(user=self.user).order_by('name')
            self.fields['tag'].queryset = Tag.objects.filter(user=self.user).order_by('name')
            self.fields['include_projects'].queryset = Projects.objects.filter(user=self.user).order_by('name')
            self.fields['exclude_projects'].queryset = Projects.objects.filter(user=self.user).order_by('name')
            self.fields['include_subprojects'].queryset = SubProjects.objects.filter(user=self.user).order_by('name')
            self.fields['exclude_subprojects'].queryset = SubProjects.objects.filter(user=self.user).order_by('name')
            self.fields['include_contexts'].queryset = Context.objects.filter(user=self.user).order_by('name')
            self.fields['exclude_contexts'].queryset = Context.objects.filter(user=self.user).order_by('name')
            self.fields['include_tags'].queryset = Tag.objects.filter(user=self.user).order_by('name')
            self.fields['exclude_tags'].queryset = Tag.objects.filter(user=self.user).order_by('name')
            self.fields['include_projects'].label_from_instance = lambda obj: obj.name
            self.fields['exclude_projects'].label_from_instance = lambda obj: obj.name
            self.fields['include_subprojects'].label_from_instance = lambda obj: f'{obj.name} ({obj.parent_project.name})'
            self.fields['exclude_subprojects'].label_from_instance = lambda obj: f'{obj.name} ({obj.parent_project.name})'
            self.fields['include_contexts'].label_from_instance = lambda obj: obj.name
            self.fields['exclude_contexts'].label_from_instance = lambda obj: obj.name
            self.fields['include_tags'].label_from_instance = lambda obj: obj.name
            self.fields['exclude_tags'].label_from_instance = lambda obj: obj.name

        if self.project_obj is not None and not self.instance.pk:
            self.initial['aggregation_type'] = 'project'
            self.initial['project'] = self.project_obj

        if self.instance.pk:
            self.initial['aggregation_type'] = self.instance.aggregation_type
        if not self.initial.get('start_date'):
            self.initial['start_date'] = timezone.localdate()
        self.fields['start_date'].required = False

    def clean(self):
        cleaned_data = super().clean()
        min_balance = cleaned_data.get('min_balance')
        max_balance = cleaned_data.get('max_balance')

        if min_balance is not None and max_balance is not None and min_balance > max_balance:
            raise forms.ValidationError("Min balance cannot be greater than max balance.")
        if min_balance is not None and min_balance > 0:
            raise forms.ValidationError("Min balance must be zero or negative.")

        aggregation_type = cleaned_data.get('aggregation_type') or getattr(self.instance, 'aggregation_type', None)
        if not aggregation_type and self.project_obj is not None:
            aggregation_type = 'project'
        if not aggregation_type:
            raise forms.ValidationError('Please select an aggregation type.')

        selected_target = cleaned_data.get(aggregation_type)
        if selected_target is None and self.instance.pk:
            selected_target = getattr(self.instance, aggregation_type, None)
        if selected_target is None and aggregation_type == 'project' and self.project_obj is not None:
            selected_target = self.project_obj
        if selected_target is None:
            raise forms.ValidationError('Please select a target for the chosen aggregation type.')

        cleaned_data['aggregation_type'] = aggregation_type
        if not cleaned_data.get('start_date'):
            cleaned_data['start_date'] = timezone.localdate()
        for field in ['project', 'subproject', 'context', 'tag']:
            cleaned_data[field] = selected_target if field == aggregation_type else None

        # Enforce hierarchy: Context > Tag > Project > Subproject.
        # A commitment can only compose rules from descendants of its scope.
        allowed_rule_dimensions = {
            'context': {'tag', 'project', 'subproject'},
            'tag': {'project', 'subproject'},
            'project': {'subproject'},
            'subproject': set(),
        }.get(aggregation_type, set())
        for dimension, fields in {
            'context': ('include_contexts', 'exclude_contexts'),
            'tag': ('include_tags', 'exclude_tags'),
            'project': ('include_projects', 'exclude_projects'),
            'subproject': ('include_subprojects', 'exclude_subprojects'),
        }.items():
            if dimension not in allowed_rule_dimensions:
                for f in fields:
                    cleaned_data[f] = []

        # Prevent contradictory include/exclude rules in the same dimension.
        for include_key, exclude_key, label in [
            ('include_projects', 'exclude_projects', 'projects'),
            ('include_subprojects', 'exclude_subprojects', 'subprojects'),
            ('include_contexts', 'exclude_contexts', 'contexts'),
            ('include_tags', 'exclude_tags', 'tags'),
        ]:
            include_items = set(cleaned_data.get(include_key) or [])
            exclude_items = set(cleaned_data.get(exclude_key) or [])
            overlap = include_items.intersection(exclude_items)
            if overlap:
                overlap_names = ', '.join(sorted(obj.name for obj in overlap))
                raise forms.ValidationError(
                    f'Cannot both include and exclude the same {label}: {overlap_names}.'
                )

        return cleaned_data


class UpdateCommitmentForm(CommitmentForm):
    class Meta(CommitmentForm.Meta):
        fields = CommitmentForm.Meta.fields + ['active']
        widgets = {
            **CommitmentForm.Meta.widgets,
            'active': forms.CheckboxInput(),
        }
        labels = {
            **CommitmentForm.Meta.labels,
            'active': 'Active',
        }
