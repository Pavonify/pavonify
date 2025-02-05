from django import forms
from .models import VocabularyWord, VocabularyList, Class, User, Student, Assignment
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone
from datetime import timedelta
from .models import User
from django_countries.widgets import CountrySelectWidget
from django_countries.fields import CountryField  # ✅ Import CountryField
from django_countries.widgets import CountrySelectWidget  # ✅ Import CountrySelectWidget


LANGUAGE_CHOICES = [
    ('en', 'English'),
    ('fr', 'French'),
    ('de', 'German'),
    ('es', 'Spanish'),
    ('it', 'Italian'),
    # Add more languages as needed
]

class VocabularyWordForm(forms.ModelForm):
    class Meta:
        model = VocabularyWord
        fields = ['word', 'translation']  # Fields for individual words

class TeacherRegistrationForm(UserCreationForm):
    full_name = forms.CharField(label="Full Name", max_length=100, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"class": "form-control"}))
    username = forms.CharField(label="Username", max_length=50, widget=forms.TextInput(attrs={"class": "form-control"}))
    password = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    country = CountryField(blank_label="Select a country").formfield(
        widget=CountrySelectWidget(attrs={"class": "form-control"})
    )

    class Meta:
        model = User
        fields = ['full_name', 'email', 'username', 'password1', 'password2', 'country']


class VocabularyListForm(forms.ModelForm):
    source_language = forms.ChoiceField(choices=LANGUAGE_CHOICES, label="Source Language")
    target_language = forms.ChoiceField(choices=LANGUAGE_CHOICES, label="Target Language")

    class Meta:
        model = VocabularyList
        fields = ['name', 'source_language', 'target_language']

class BulkAddWordsForm(forms.Form):
    words = forms.CharField(
        widget=forms.Textarea,
        help_text="Add words in the format: word,translation (one pair per line)."
    )

class ClassForm(forms.ModelForm):
    language = forms.ChoiceField(choices=LANGUAGE_CHOICES)  # Add dropdown

    class Meta:
        model = Class
        fields = ['name', 'language', 'icon']  # Exclude 'students'

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'password1', 'password2']  # Add any additional fields here

class ShareClassForm(forms.Form):
    username = forms.CharField(
        max_length=50,
        label="Enter the username of the teacher to share with:",
        widget=forms.TextInput(attrs={'placeholder': 'Teacher username'}),
        required=True
    )

class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = [
            "name",
            "vocab_list",
            "deadline",
            "target_points",
            "include_flashcards",
            "include_matchup",
            "include_fill_gap",
            "include_destroy_wall",
            "include_unscramble",
        ]
        widgets = {
            "deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

