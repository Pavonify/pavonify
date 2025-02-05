from django.contrib import admin
from django.db.models import Sum
from django import forms
from django.utils import timezone
from datetime import timedelta
from django.utils.html import format_html
from .models import (
    School, User, Class, Student, VocabularyList, VocabularyWord,
    Progress, Assignment, AssignmentProgress, Trophy, StudentTrophy

)

@admin.register(Trophy)
class TrophyAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'display_icon', 'points_required', 'streak_required', 'assignment_count_required', 'is_hidden')
    search_fields = ('name', 'description')
    list_filter = ('is_hidden', 'points_required', 'streak_required', 'assignment_count_required')

    def display_icon(self, obj):
        if obj.icon:
            return format_html('<img src="{}" width="30" height="30" style="border-radius:5px;" />', obj.icon.url)
        return "No Icon"
    
    display_icon.short_description = "Icon"

@admin.register(StudentTrophy)
class StudentTrophyAdmin(admin.ModelAdmin):
    list_display = ('student', 'trophy', 'earned_at')
    search_fields = ('student__first_name', 'student__last_name', 'trophy__name')
    list_filter = ('earned_at',)

# **📌 School Admin**
@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'key', 'created_at')
    search_fields = ('name', 'location')


# **📌 Class Admin**
@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'language', 'school', 'teacher_list')
    search_fields = ('name', 'language')
    list_filter = ('school',)

    def teacher_list(self, obj):
        return ", ".join([teacher.username for teacher in obj.teachers.all()])
    teacher_list.short_description = "Teachers"


# **📌 Student Admin**
@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'username', 'year_group', 'school', 'total_points')
    search_fields = ('first_name', 'last_name', 'username')
    list_filter = ('year_group', 'school')
    ordering = ('last_name', 'first_name')


# **📌 Vocabulary List Admin**
@admin.register(VocabularyList)
class VocabularyListAdmin(admin.ModelAdmin):
    list_display = ('name', 'source_language', 'target_language', 'teacher')
    search_fields = ('name', 'source_language', 'target_language')
    list_filter = ('source_language', 'target_language')


# **📌 Vocabulary Word Admin**
@admin.register(VocabularyWord)
class VocabularyWordAdmin(admin.ModelAdmin):
    list_display = ('word', 'translation', 'vocab_list_name')
    search_fields = ('word', 'translation')

    def vocab_list_name(self, obj):
        return obj.list.name if obj.list else "N/A"
    vocab_list_name.short_description = "Vocabulary List"


# **📌 Assignment Progress Admin**
@admin.register(AssignmentProgress)
class AssignmentProgressAdmin(admin.ModelAdmin):
    list_display = ('student', 'assignment', 'points_earned', 'time_spent', 'completed_status')
    search_fields = ('student__username', 'assignment__name')
    list_filter = ('assignment', 'student')

    def completed_status(self, obj):
        return "✅ Completed" if obj.points_earned >= obj.assignment.target_points else "❌ In Progress"
    completed_status.short_description = "Status"


from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum
from .models import Assignment, AssignmentProgress


# ✅ Check if AssignmentProgress is already registered before registering it again
if admin.site.is_registered(AssignmentProgress):
    admin.site.unregister(AssignmentProgress)


# ✅ Assignment Admin - Now Includes Listening Modes
@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'class_assigned', 'deadline', 'target_points', 'teacher')
    list_filter = ('class_assigned', 'deadline')
    search_fields = ('name',)

    fields = (
        'name', 'class_assigned', 'vocab_list', 'deadline', 'target_points',
        'include_flashcards', 'points_per_flashcard',
        'include_matchup', 'points_per_matchup',
        'include_fill_gap', 'points_per_fill_gap',
        'include_destroy_wall', 'points_per_destroy_wall',
        'include_unscramble', 'points_per_unscramble',
        'include_listening_dictation', 'points_per_listening_dictation',  # ✅ Listening Dictation added
        'include_listening_translation', 'points_per_listening_translation',  # ✅ Listening Translation added
        'teacher',
        'display_student_progress'
    )

    readonly_fields = ('display_student_progress',)

    def display_student_progress(self, obj):
        """Generate a progress table for students assigned to this assignment."""
        students = obj.class_assigned.students.all()
        student_progress = AssignmentProgress.objects.filter(assignment=obj)

        if not students:
            return "No students assigned."

        table_html = "<table style='border-collapse: collapse; width:100%; border: 1px solid #ccc;'>"
        table_html += "<tr style='background-color:#f5f5f5;'><th style='border-bottom: 1px solid #ccc; padding: 5px; text-align: left;'>Student</th><th style='border-bottom: 1px solid #ccc; padding: 5px; text-align: left;'>Progress</th></tr>"

        for student in students:
            progress = student_progress.filter(student=student).aggregate(total=Sum('points_earned'))['total'] or 0
            progress_color = "green" if progress >= obj.target_points else "red"
            table_html += f"<tr><td style='padding: 5px;'>{student.first_name} {student.last_name}</td><td style='color:{progress_color}; padding: 5px;'><strong>{progress} / {obj.target_points}</strong></td></tr>"

        table_html += "</table>"

        return format_html(table_html)

    display_student_progress.short_description = "Student Progress Table"


# ✅ Now Safely Register AssignmentProgress Without Duplication
class AssignmentProgressAdmin(admin.ModelAdmin):
    list_display = ('student', 'assignment', 'points_earned')
    list_filter = ('assignment',)
    search_fields = ('student__first_name', 'student__last_name', 'assignment__name')

    fields = ('student', 'assignment', 'points_earned')
    list_editable = ('points_earned',)  # ✅ Allows direct editing of points in the admin panel


admin.site.register(AssignmentProgress, AssignmentProgressAdmin)  # ✅ Ensuring safe registration



class UserAdminForm(forms.ModelForm):
    is_premium = forms.BooleanField(required=False, label="Premium Status")

    class Meta:
        model = User
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super(UserAdminForm, self).__init__(*args, **kwargs)
        # Set the initial value for is_premium field based on the current premium_expiration
        if self.instance and self.instance.pk:
            self.fields['is_premium'].initial = self.instance.is_premium

    def save(self, commit=True):
        instance = super().save(commit=False)
        # If the checkbox is checked and the expiration is not in the future,
        # upgrade to premium (e.g. 30 days from now)
        if self.cleaned_data.get('is_premium'):
            if instance.premium_expiration <= timezone.now():
                instance.premium_expiration = timezone.now() + timedelta(days=30)
        else:
            # Otherwise, set the expiration to now (Basic)
            instance.premium_expiration = timezone.now()
        if commit:
            instance.save()
        return instance


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    form = UserAdminForm
    list_display = ('username', 'is_student', 'is_teacher', 'is_lead_teacher', 'school', 'premium_expiration', 'is_premium_display')
    list_filter = ('school', 'is_student', 'is_teacher', 'is_lead_teacher')
    search_fields = ('username', 'first_name', 'last_name')
    
    def is_premium_display(self, obj):
        return obj.is_premium
    is_premium_display.boolean = True  # This tells the admin to display as a tick/cross
    is_premium_display.short_description = "Premium"
