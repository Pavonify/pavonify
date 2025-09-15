from django import forms
from .models import VocabularyWord, VocabularyList, Class, User, Student, Assignment
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone
from datetime import timedelta
from django.utils.timezone import now, timedelta
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
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    country = CountryField(blank_label="Select a country").formfield(
            layout="{country}",
            choices=CountryField().choices,  # Explicitly set the choices
            attrs={"class": "form-control"}
    )

    class Meta:
        model = User  # Ensure you're using your custom User model
        fields = ["full_name", "email", "username", "password1", "password2", "country"]

    def clean_email(self):
        """
        Ensures the email is unique before saving.
        """
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def save(self, commit=True):
        """
        Saves the teacher as a basic (non-premium) user.
        """
        user = super().save(commit=False)
        user.is_teacher = True  # ✅ Set as a teacher
        user.first_name, user.last_name = self.cleaned_data["full_name"].split(" ", 1) if " " in self.cleaned_data["full_name"] else (self.cleaned_data["full_name"], "")
        user.premium_expiration = now()  # ✅ Ensures they start as Basic
        if commit:
            user.save()
        return user


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

    MAX_WORDS = 100
    MAX_LENGTH = 100

    def clean_words(self):
        """Validate and normalize bulk word input."""
        raw = self.cleaned_data["words"]
        lines = [line.strip() for line in raw.splitlines() if line.strip()]

        if len(lines) > self.MAX_WORDS:
            raise forms.ValidationError(
                f"You can only add up to {self.MAX_WORDS} words at once."
            )

        pairs = []
        for line in lines:
            if "," not in line:
                continue
            word, translation = [
                part.strip()[: self.MAX_LENGTH] for part in line.split(",", 1)
            ]
            pairs.append((word, translation))

        return pairs

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
        ]
        widgets = {
            "deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

