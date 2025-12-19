"""
Quick test to see what CheckboxSelectMultiple renders
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AutumnWeb.settings')
django.setup()

from django import forms
from django.forms.widgets import CheckboxSelectMultiple

class TestForm(forms.Form):
    tags = forms.MultipleChoiceField(
        choices=[
            (1, 'Python'),
            (2, 'Django'),
            (3, 'Web Development'),
        ],
        widget=CheckboxSelectMultiple(attrs={'id': 'tag-filter'}),
        required=False,
    )

# Create form and render
form = TestForm()
print("Rendered tags field:")
print(form.as_p())
print("\n\nJust the tags widget:")
print(form['tags'])

