from django import forms
from .models import Projects, SubProjects, Context, Tag, NotificationPreference
from typing import cast


NOTIFICATION_WEEKDAY_CHOICES = (
    (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
    (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
)


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


class NotificationPreferenceForm(forms.ModelForm):
    """The three independent delivery categories and their local slots."""

    WEEKDAY_CHOICES = NOTIFICATION_WEEKDAY_CHOICES

    class Meta:
        model = NotificationPreference
        fields = [
            "scheduled_reminders_enabled",
            "commitment_checks_enabled",
            "weekly_review_enabled",
            "commitment_check_time",
            "weekly_review_weekday",
            "weekly_review_time",
        ]
        widgets = {
            "scheduled_reminders_enabled": forms.CheckboxInput(),
            "commitment_checks_enabled": forms.CheckboxInput(),
            "weekly_review_enabled": forms.CheckboxInput(),
            "commitment_check_time": forms.TimeInput(attrs={"type": "time", "step": 60}),
            "weekly_review_weekday": forms.Select(choices=NOTIFICATION_WEEKDAY_CHOICES),
            "weekly_review_time": forms.TimeInput(attrs={"type": "time", "step": 60}),
        }
        labels = {
            "scheduled_reminders_enabled": "Scheduled reminders",
            "commitment_checks_enabled": "Commitment checks",
            "weekly_review_enabled": "Weekly review",
            "commitment_check_time": "Check time",
            "weekly_review_weekday": "Review day",
            "weekly_review_time": "Review time",
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["commitment_check_time"].help_text = (
            "Choose a local time from 18:00 through 23:59."
        )
        self.fields["weekly_review_time"].help_text = "This uses your profile timezone."

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.user is not None:
            obj.user = self.user
        if commit:
            obj.save()
        return obj


class SubprojectCheckboxSelect(forms.CheckboxSelectMultiple):
    """Checkboxes that carry their parent project id for client-side filtering."""

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-parent"] = str(instance.parent_project_id)
        return option


class ScheduledReminderForm(forms.Form):
    """Owned schedule fields; local date/time are profile-local.

    A schedule targets exactly one of a project (optionally narrowed to some of
    its subprojects), a context, or a tag.
    """

    target = forms.ChoiceField(
        choices=(
            ("project", "A project"),
            ("context", "A context"),
            ("tag", "A tag"),
        ),
        initial="project",
        label="Remind me about",
        widget=forms.Select(attrs={"data-schedule-target": ""}),
    )
    project = forms.ModelChoiceField(
        queryset=Projects.objects.none(),
        required=False,
        label="Project",
        widget=forms.Select(attrs={"data-schedule-project": ""}),
    )
    context = forms.ModelChoiceField(
        queryset=Context.objects.none(),
        required=False,
        label="Context",
        widget=forms.Select(attrs={"data-schedule-context": ""}),
    )
    tag = forms.ModelChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        label="Tag",
        widget=forms.Select(attrs={"data-schedule-tag": ""}),
    )
    subprojects = forms.ModelMultipleChoiceField(
        queryset=SubProjects.objects.none(),
        required=False,
        label="Subprojects (optional)",
        widget=SubprojectCheckboxSelect(attrs={
            "class": "nx-subproject-options",
            "data-schedule-subprojects": "",
        }),
    )
    local_date = forms.DateField(
        label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    local_time = forms.TimeField(
        label="Time", widget=forms.TimeInput(attrs={"type": "time", "step": 60}, format="%H:%M")
    )
    cadence = forms.ChoiceField(choices=(
        ("once", "Once"), ("daily", "Daily"), ("weekly", "Weekly"),
    ), initial="once", label="Repeat")
    message = forms.CharField(
        required=False, max_length=240, label="Message",
        widget=forms.TextInput(attrs={"maxlength": 240, "placeholder": "What should Autumn remind you about?"}),
    )
    version = forms.IntegerField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.instance = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        if self.user is not None:
            self.fields["project"].queryset = Projects.objects.filter(user=self.user).exclude(
                status__in=["archived", "complete"]
            ).order_by("name")
            # Context/Tag __str__ carries the owner's username; these pickers
            # only ever show one account's rows, so label by name alone.
            self.fields["context"].queryset = Context.objects.filter(
                user=self.user
            ).order_by("name")
            self.fields["context"].label_from_instance = lambda obj: obj.name
            self.fields["tag"].queryset = Tag.objects.filter(
                user=self.user
            ).order_by("name")
            self.fields["tag"].label_from_instance = lambda obj: obj.name
            self.fields["subprojects"].queryset = SubProjects.objects.filter(
                user=self.user
            ).exclude(
                parent_project__status__in=["archived", "complete"]
            ).select_related("parent_project").order_by("parent_project__name", "name")
            self.fields["subprojects"].label_from_instance = (
                lambda obj: f"{obj.name} ({obj.parent_project.name})"
            )
        if self.instance is not None and not self.is_bound:
            self.initial.update({
                "target": (
                    "context" if self.instance.context_id
                    else "tag" if self.instance.tag_id
                    else "project"
                ),
                "project": self.instance.project_id,
                "context": self.instance.context_id,
                "tag": self.instance.tag_id,
                "subprojects": list(
                    self.instance.subprojects.values_list("pk", flat=True)
                ),
                "local_date": self.instance.anchor_date,
                "local_time": self.instance.anchor_time,
                "cadence": self.instance.cadence,
                "message": self.instance.message,
                "version": self.instance.version,
            })

    def clean(self):
        cleaned = super().clean()
        target = cleaned.get("target")
        if target in {"context", "tag"}:
            if cleaned.get(target) is None:
                self.add_error(target, f"Choose a {target}.")
            # A context or tag already names its own scope; drop the project
            # fields so the service never sees two targets.
            for unused in {"project", "context", "tag"} - {target}:
                cleaned[unused] = None
            cleaned["subprojects"] = self.fields["subprojects"].queryset.none()
            return cleaned

        cleaned["context"] = None
        cleaned["tag"] = None
        project = cleaned.get("project")
        if project is None:
            self.add_error("project", "Choose a project.")
            return cleaned
        subprojects = cleaned.get("subprojects") or []
        if any(item.parent_project_id != project.pk for item in subprojects):
            self.add_error("subprojects", "Choose subprojects from the selected project.")
        return cleaned
