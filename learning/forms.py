from django import forms
from .models import (
    VocabularyWord,
    VocabularyList,
    Class,
    User,
    Student,
    Assignment,
    Tag,
    School,
)
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
    SCHOOL_OPTIONS = (
        ("create", "Create New School"),
        ("join", "Join Existing School"),
    )

    full_name = forms.CharField(label="Full Name", max_length=100, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"class": "form-control"}))
    username = forms.CharField(label="Username", max_length=50, widget=forms.TextInput(attrs={"class": "form-control"}))
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    school_option = forms.ChoiceField(
        choices=SCHOOL_OPTIONS,
        initial="create",
        widget=forms.RadioSelect,
        label="School Membership",
    )
    school_name = forms.CharField(
        label="School Name",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Greenfield Academy"}),
    )
    school_code = forms.CharField(
        label="School Code",
        max_length=6,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter invitation code"}),
    )
    country = CountryField(blank_label="Select a country").formfield(
            layout="{country}",
            choices=CountryField().choices,  # Explicitly set the choices
            attrs={"class": "form-control"}
    )

    class Meta:
        model = User  # Ensure you're using your custom User model
        fields = [
            "full_name",
            "email",
            "username",
            "password1",
            "password2",
            "country",
        ]

    def clean_email(self):
        """
        Ensures the email is unique before saving.
        """
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        option = cleaned_data.get("school_option")
        school_name = (cleaned_data.get("school_name") or "").strip()
        school_code = (cleaned_data.get("school_code") or "").strip().upper()

        if option == "create":
            if not school_name:
                self.add_error("school_name", "Please enter the name of your school.")
        elif option == "join":
            if not school_code:
                self.add_error("school_code", "Please enter the school invitation code.")
            else:
                try:
                    cleaned_data["selected_school"] = School.objects.get(school_code__iexact=school_code)
                except School.DoesNotExist:
                    self.add_error("school_code", "We couldn't find a school with that code.")
        return cleaned_data

    def save(self, commit=True):
        """Saves the teacher and attaches them to the appropriate school."""

        user = super().save(commit=False)
        user.is_teacher = True

        full_name = self.cleaned_data["full_name"].strip()
        if " " in full_name:
            user.first_name, user.last_name = full_name.split(" ", 1)
        else:
            user.first_name = full_name
            user.last_name = ""

        user.premium_expiration = now()

        option = self.cleaned_data.get("school_option")
        if option == "create":
            school = School.objects.create(name=self.cleaned_data["school_name"].strip())
            user.school = school
            user.is_school_lead = True
        elif option == "join":
            school = self.cleaned_data.get("selected_school")
            if school is None:
                raise ValueError("School must be resolved during form cleaning")
            user.school = school
            user.is_school_lead = False

        if commit:
            user.save()
        return user


class VocabularyListForm(forms.ModelForm):
    source_language = forms.ChoiceField(choices=LANGUAGE_CHOICES, label="Source Language")
    target_language = forms.ChoiceField(choices=LANGUAGE_CHOICES, label="Target Language")
    tag_names = forms.CharField(
        required=False,
        label="Tags",
        help_text="Separate multiple tags with commas.",
    )
    shared_with_school = forms.BooleanField(
        required=False,
        label="Shared with School",
        help_text="Share this list with every teacher at your school.",
    )

    def __init__(self, *args, teacher=None, **kwargs):
        self.teacher = teacher
        super().__init__(*args, **kwargs)

        if self.instance.pk and not self.teacher:
            self.teacher = self.instance.teacher

        if self.teacher:
            existing_tags = Tag.objects.filter(teacher=self.teacher).order_by("name")
            if existing_tags.exists():
                tag_list = ", ".join(existing_tags.values_list("name", flat=True))
                self.fields["tag_names"].help_text = (
                    "Separate multiple tags with commas. Existing tags: " + tag_list
                )

        if self.instance.pk:
            current_tags = self.instance.tags.order_by("name").values_list("name", flat=True)
            self.initial["tag_names"] = ", ".join(current_tags)

        if not getattr(self.teacher, "school", None):
            self.fields["shared_with_school"].disabled = True
            self.fields["shared_with_school"].help_text = (
                "Join or create a school account to enable sharing."
            )

    def clean_tag_names(self):
        raw_tags = self.cleaned_data.get("tag_names", "")
        if not raw_tags:
            return []

        tag_names = []
        for tag in raw_tags.split(","):
            cleaned = tag.strip()
            if cleaned and cleaned not in tag_names:
                tag_names.append(cleaned)
        return tag_names

    def _save_tags(self, instance):
        tag_names = self.cleaned_data.get("tag_names", [])
        teacher = self.teacher or getattr(instance, "teacher", None)
        if teacher is None:
            return

        tags = []
        for name in tag_names:
            tag, _ = Tag.objects.get_or_create(teacher=teacher, name=name)
            tags.append(tag)
        instance.tags.set(tags)

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            self._save_tags(instance)
        return instance

    def save_tags(self, instance):
        self._save_tags(instance)

    class Meta:
        model = VocabularyList
        fields = ['name', 'source_language', 'target_language', 'shared_with_school']

class BulkAddWordsForm(forms.Form):
    MAX_WORDS = 300
    MAX_LENGTH = 100

    words = forms.CharField(
        widget=forms.Textarea,
        help_text=f"Add up to {MAX_WORDS} words in the format: word,translation (one pair per line)."
    )

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
            "deadline": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deadline"].input_formats = ["%Y-%m-%dT%H:%M"]

