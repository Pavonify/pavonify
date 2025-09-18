from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, logout, get_user_model
from django.db.models import Sum, Count, F, Subquery, OuterRef, Q
from django.db.models.functions import Coalesce
from django.contrib import messages
from django.http import (
    HttpResponseRedirect,
    HttpResponseForbidden,
    Http404,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.serializers.json import DjangoJSONEncoder
from django.core.paginator import Paginator
from django.templatetags.static import static
from django.utils import timezone
from django.utils.timezone import now
from django.utils.http import url_has_allowed_host_and_scheme
from functools import wraps
import csv
import datetime
from datetime import datetime, timedelta
import random
import json
import math
import re
import requests
import stripe
import google.generativeai as genai
from collections import defaultdict
from django.conf import settings
from typing import Any, Dict, List, Optional

from .decorators import student_login_required
from .utils import generate_student_username, generate_random_password
from .memory import memory_meter
from .spaced_repetition import get_due_words, schedule_review, _get_user_from_student

from .models import (
    Progress,
    VocabularyWord,
    VocabularyList,
    User,
    Class,
    Student,
    School,
    Assignment,
    AssignmentProgress,
    Trophy,
    StudentTrophy,
    ReadingLabText,
    AssignmentAttempt,
    GrammarLadder,
    LadderItem,
    Announcement,
)
from achievements.models import Trophy as AchievementTrophy, TrophyUnlock
from achievements.services.evaluator import read_metric

# Configure Stripe and Gemini
stripe.api_key = settings.STRIPE_SECRET_KEY
genai.configure(api_key=getattr(settings, "GEMINI_API_KEY", ""))

User = get_user_model()


# ----------------------------
# Trophy helpers
# ----------------------------

def _trophy_icon_url(icon_value: Any) -> str:
    """Return a usable icon URL for either legacy or achievements trophies."""

    if icon_value:
        try:
            url = icon_value.url  # type: ignore[attr-defined]
        except (AttributeError, ValueError):  # pragma: no cover - defensive
            url = None
        if url:
            return url
    if isinstance(icon_value, str) and icon_value and icon_value != "trophy":
        return static(f"trophies/{icon_value}.png")
    return static("trophies/default_trophy.png")


def _trophy_progress(user: User, trophy: AchievementTrophy, unlocked: bool) -> Optional[Dict[str, Any]]:
    """Build a simple progress snapshot for a trophy if supported."""

    threshold = trophy.threshold
    if unlocked:
        if isinstance(threshold, (int, float)) and threshold:
            target = float(threshold)
            return {"current": target, "target": target, "percentage": 100.0}
        return None

    if trophy.comparator != "gte":
        return None

    if not isinstance(threshold, (int, float)) or not threshold:
        return None

    target = float(threshold)
    if target <= 0:
        return None

    value = read_metric(user, trophy.metric, trophy.window, {})
    if not isinstance(value, (int, float)):
        return None

    percentage = max(0.0, min(100.0, (value / target) * 100.0))
    return {"current": float(value), "target": target, "percentage": percentage}


# ----------------------------
# Landing / Auth Utilities
# ----------------------------

def landing_page(request):
    """Landing page for users to choose login options."""
    return render(request, 'learning/landing_page.html')


def teacher_logout(request):
    request.session.flush()
    logout(request)
    return HttpResponseRedirect('/')


def student_logout(request):
    request.session.flush()
    logout(request)
    return HttpResponseRedirect('/')


# ----------------------------
# Teacher Dashboard
# ----------------------------

@login_required
@user_passes_test(lambda u: u.is_teacher)
def worksheet_lab_view(request):
    vocab_list_id = request.GET.get('vocab_list')
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    # Fetch words related to the selected vocabulary list
    words_queryset = vocab_list.words.all()
    words = [{'word': word.word, 'translation': word.translation} for word in words_queryset]

    # Serialize the words to JSON
    words_json = json.dumps(words)

    # Get the user's premium status (safe check if attribute missing)
    is_premium = getattr(request.user, "is_premium", False) if request.user.is_authenticated else False

    return render(request, 'learning/worksheet_lab.html', {
        'vocab_list': vocab_list,
        'words_json': words_json,
        'is_premium': is_premium,
    })

@login_required
def teacher_dashboard(request):
    if not request.user.is_teacher:
        return redirect("login")

    reading_lab_texts = ReadingLabText.objects.filter(teacher=request.user).order_by('-created_at')
    vocab_lists = VocabularyList.objects.filter(teacher=request.user)
    classes = Class.objects.filter(teachers=request.user).distinct()

    # --- Student filtering and sorting ---
    selected_class_id = request.GET.get("class_id")
    sort_by = request.GET.get("sort", "alphabetical")

    students = Student.objects.filter(classes__in=classes).distinct()
    if selected_class_id:
        students = students.filter(classes__id=selected_class_id)

    if sort_by == "last_login":
        students = students.order_by("-last_login")
    elif sort_by == "points":
        students = students.order_by("-total_points")
    else:  # alphabetical
        students = students.order_by("last_name", "first_name")

    # Annotate each class with live and expired assignments
    current_time = now()
    for class_instance in classes:
        class_instance.live_assignments = Assignment.objects.filter(
            class_assigned=class_instance,
            deadline__gte=current_time,
            is_closed=False,
        )
        class_instance.expired_assignments = (
            Assignment.objects.filter(class_assigned=class_instance)
            .filter(Q(deadline__lt=current_time) | Q(is_closed=True))
        )

    # Attach unattached classes to each vocabulary list
    for vocab_list in vocab_lists:
        vocab_list.unattached_classes = classes.exclude(
            id__in=vocab_list.classes.values_list("id", flat=True)
        )

    # Announcements Pagination (3 posts per page)
    announcements_list = Announcement.objects.all()
    announcements_paginator = Paginator(announcements_list, 3)
    announcements_page_number = request.GET.get("page")
    announcements = announcements_paginator.get_page(announcements_page_number)

    # Overall Leaderboard: Paginate teacher's students ordered by total_points (10 per page)
    overall_leaderboard_list = students.order_by('-total_points')
    overall_page_number = request.GET.get('overall_page', 1)
    overall_paginator = Paginator(overall_leaderboard_list, 10)
    overall_leaderboard_page = overall_paginator.get_page(overall_page_number)

    # Leaderboard by Class (10 per page per class)
    by_class_leaderboards = []
    for class_instance in classes:
        students_in_class = class_instance.students.order_by('-total_points')
        page_number = request.GET.get(f'class_{class_instance.id}_page', 1)
        paginator = Paginator(students_in_class, 10)
        leaderboard_page = paginator.get_page(page_number)
        by_class_leaderboards.append({
            'class_instance': class_instance,
            'leaderboard_page': leaderboard_page,
        })

    # Quick overview data
    inactive_threshold = now() - timedelta(days=7)
    inactive_students = students.filter(
        Q(last_login__lt=inactive_threshold) | Q(last_login__isnull=True)
    ).order_by('last_name', 'first_name')

    pending_assignments = []
    active_assignments = Assignment.objects.filter(
        class_assigned__in=classes,
        deadline__gte=current_time,
        is_closed=False,
    )
    for assignment in active_assignments:
        total_students = assignment.class_assigned.students.count()
        completed = AssignmentProgress.objects.filter(
            assignment=assignment, completed=True
        ).count()
        pending_count = total_students - completed
        if pending_count > 0:
            pending_assignments.append({
                "assignment": assignment,
                "pending": pending_count,
            })

    return render(request, "learning/teacher_dashboard.html", {
        "user": request.user,
        "vocab_lists": vocab_lists,
        "classes": classes,
        "students": students,
        "selected_class_id": selected_class_id,
        "sort_by": sort_by,
        "announcements": announcements,
        "reading_lab_texts": reading_lab_texts,
        "overall_leaderboard_page": overall_leaderboard_page,
        "by_class_leaderboards": by_class_leaderboards,
        "pending_assignments": pending_assignments,
        "inactive_students": inactive_students,
    })


# ----------------------------
# Vocabulary Lists / Words
# ----------------------------

@login_required
@user_passes_test(lambda u: u.is_teacher)
def add_vocabulary_list(request):
    from .forms import VocabularyListForm
    if request.method == 'POST':
        form = VocabularyListForm(request.POST)
        if form.is_valid():
            vocab_list = form.save(commit=False)
            vocab_list.teacher = request.user
            vocab_list.save()
            messages.success(request, "Vocabulary list created successfully!")
            return redirect('teacher_dashboard')
    else:
        form = VocabularyListForm()
    return render(request, 'learning/add_vocabulary_list.html', {'form': form})


@login_required
@user_passes_test(lambda u: u.is_teacher)
def edit_vocabulary_list_details(request, list_id):
    from .forms import VocabularyListForm
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    if request.method == 'POST':
        form = VocabularyListForm(request.POST, instance=vocab_list)
        if form.is_valid():
            form.save()
            messages.success(request, "List details updated successfully!")
            return redirect('teacher_dashboard')
    else:
        form = VocabularyListForm(instance=vocab_list)
    return render(request, 'learning/edit_vocabulary_list_details.html', {'form': form, 'vocab_list': vocab_list})


@login_required
@user_passes_test(lambda u: u.is_teacher)
def add_words_to_list(request, list_id):
    from .forms import BulkAddWordsForm
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    if request.method == 'POST':
        form = BulkAddWordsForm(request.POST)
        if form.is_valid():
            word_pairs = form.cleaned_data['words']
            vocab_words = [
                VocabularyWord(list=vocab_list, word=w, translation=t)
                for w, t in word_pairs
                if w and t
            ]
            VocabularyWord.objects.bulk_create(vocab_words)
            messages.success(request, "Words added successfully!")
            return redirect('teacher_dashboard')
    else:
        form = BulkAddWordsForm()
    return render(
        request,
        'learning/add_words_to_list.html',
        {'form': form, 'vocab_list': vocab_list},
    )


@login_required
@user_passes_test(lambda u: u.is_teacher)
def edit_vocabulary_words(request, list_id):
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    words = vocab_list.words.all()

    if request.method == 'POST':
        action = request.POST.get("action")

        if action == "save":
            for word in words:
                word_id = f"word_{word.id}"
                translation_id = f"translation_{word.id}"
                new_word = request.POST.get(word_id)
                new_translation = request.POST.get(translation_id)

                if new_word is not None:
                    word.word = new_word.strip()
                if new_translation is not None:
                    word.translation = new_translation.strip()

                remove_image = request.POST.get(f"remove_image_{word.id}") == "on"
                image_approved = request.POST.get(f"image_approved_{word.id}") == "on"
                if remove_image:
                    word.image_url = None
                    word.image_thumb_url = None
                    word.image_source = ""
                    word.image_attribution = ""
                    word.image_license = ""
                    word.image_approved = False
                elif word.image_url:
                    word.image_approved = image_approved
                else:
                    word.image_approved = False

                clear_fact = request.POST.get(f"clear_fact_{word.id}") == "on"
                fact_text = (request.POST.get(f"fact_text_{word.id}") or "").strip()
                fact_type_value = (request.POST.get(f"fact_type_{word.id}") or "").strip().lower()
                fact_approved = request.POST.get(f"fact_approved_{word.id}") == "on"
                confidence_raw = request.POST.get(f"fact_confidence_{word.id}")

                if clear_fact:
                    word.word_fact_text = ""
                    word.word_fact_type = ""
                    word.word_fact_confidence = None
                    word.word_fact_approved = False
                else:
                    word.word_fact_text = fact_text
                    valid_types = {"etymology", "idiom", "trivia"}
                    if fact_type_value in valid_types:
                        word.word_fact_type = fact_type_value
                    elif not fact_text:
                        word.word_fact_type = ""
                    else:
                        previous = (word.word_fact_type or "").lower()
                        word.word_fact_type = previous if previous in valid_types else "trivia"

                    if confidence_raw is not None:
                        confidence_raw = confidence_raw.strip()
                        if confidence_raw:
                            try:
                                word.word_fact_confidence = float(confidence_raw)
                            except ValueError:
                                pass
                        elif not fact_text:
                            word.word_fact_confidence = None

                    word.word_fact_approved = bool(fact_text) and fact_approved

                word.save()
            messages.success(request, "Words updated successfully!")
            return redirect('edit_vocabulary_words', list_id=list_id)

        elif action == "bulk_delete":
            selected_word_ids = request.POST.getlist("selected_words")
            VocabularyWord.objects.filter(id__in=selected_word_ids).delete()
            messages.success(request, "Selected words deleted successfully!")
            return redirect('edit_vocabulary_words', list_id=list_id)

    return render(request, 'learning/edit_vocabulary_words.html', {
        'vocab_list': vocab_list,
        'words': words,
    })


@login_required
@user_passes_test(lambda u: u.is_teacher)
def view_vocabulary_words(request, list_id):
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    words = vocab_list.words.all()
    return render(request, 'learning/view_vocabulary_words.html', {'vocab_list': vocab_list, 'words': words})


@login_required
@user_passes_test(lambda u: u.is_teacher)
def delete_vocabulary_word(request, word_id):
    word = get_object_or_404(VocabularyWord, id=word_id)
    if request.method == 'POST':
        word.delete()
        messages.success(request, "Word deleted successfully!")
        return redirect('edit_vocabulary_words', list_id=word.list.id)
    return render(request, 'learning/delete_vocabulary_word.html', {'word': word})


@login_required
@user_passes_test(lambda u: u.is_teacher)
def bulk_delete_words(request, list_id):
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    if request.method == 'POST':
        word_ids = request.POST.getlist('selected_words')
        VocabularyWord.objects.filter(id__in=word_ids).delete()
        messages.success(request, "Selected words deleted successfully!")
        return redirect('edit_vocabulary_words', list_id=list_id)
    return render(request, 'learning/bulk_delete_words.html', {'vocab_list': vocab_list, 'words': vocab_list.words.all()})


@login_required
@user_passes_test(lambda u: u.is_teacher)
def delete_vocabulary_list(request, pk):
    vocab_list = get_object_or_404(VocabularyList, pk=pk, teacher=request.user)
    if request.method == 'POST':
        vocab_list.delete()
        messages.success(request, "Vocabulary list deleted successfully!")
        return redirect('teacher_dashboard')
    return render(request, 'learning/delete_vocabulary_list.html', {'vocab_list': vocab_list})


def leaderboard(request):
    leaderboard_data = Progress.objects.values('student__username').annotate(
        total_points=Sum('points')
    ).order_by('-total_points')
    return render(request, 'learning/leaderboard.html', {'leaderboard': leaderboard_data})


# ----------------------------
# Classes & Students
# ----------------------------

@login_required
def create_class(request):
    from .forms import ClassForm
    if request.method == "POST":
        form = ClassForm(request.POST, request.FILES)
        if form.is_valid():
            class_instance = form.save(commit=False)
            if hasattr(request.user, 'school') and request.user.school:
                class_instance.school = request.user.school
            else:
                messages.error(request, "You must belong to a school to create a class.")
                return redirect("create_class")

            try:
                class_instance.save()
                class_instance.teachers.add(request.user)
                messages.success(request, "Class created successfully!")
                return redirect("teacher_dashboard")
            except Exception as e:
                messages.error(request, f"Error saving class: {e}")
        else:
            messages.error(request, "Form submission is invalid. Please correct the errors below.")
    else:
        form = ClassForm()
    return render(request, "learning/create_class.html", {"form": form})


@login_required
def edit_class(request, class_id):
    current_class = get_object_or_404(Class, id=class_id)
    students = current_class.students.all()

    if request.method == "POST":
        if "delete_selected" in request.POST:
            selected_students = request.POST.getlist("selected_students")
            Student.objects.filter(id__in=selected_students).delete()
            messages.success(request, "Selected students have been deleted.")
        return redirect("edit_class", class_id=class_id)

    return render(request, "learning/edit_class.html", {
        "class_instance": current_class,
        "students": students,
    })


@login_required
def add_students(request, class_id):
    current_class = get_object_or_404(Class, id=class_id)
    if request.method == "POST":
        bulk_data = request.POST.get("bulk_data", "").strip()
        if not bulk_data:
            messages.error(request, "No student data provided.")
            return redirect("add_students", class_id=class_id)

        school_to_assign = current_class.school if current_class.school else request.user.school

        created_students = []
        attached_existing = 0
        already_in_class = 0

        reader = csv.reader(bulk_data.splitlines())
        for line_number, row in enumerate(reader, start=1):
            if not row or not any(cell.strip() for cell in row):
                continue

            if len(row) < 4:
                messages.error(
                    request,
                    f"Line {line_number}: expected 4 values (First Name, Surname, Year Group, Date of Birth).",
                )
                continue

            first_name, last_name, year_group_raw, dob_raw = [cell.strip() for cell in row[:4]]

            if not all([first_name, last_name, year_group_raw, dob_raw]):
                messages.error(
                    request,
                    f"Line {line_number}: missing required values. Please provide First Name, Surname, Year Group, and Date of Birth.",
                )
                continue

            try:
                year_group = int(year_group_raw)
            except ValueError:
                messages.error(
                    request,
                    f"Line {line_number}: year group '{year_group_raw}' must be a number.",
                )
                continue

            try:
                dob = datetime.strptime(dob_raw, "%d/%m/%Y").date()
            except ValueError:
                messages.error(
                    request,
                    f"Line {line_number}: date of birth '{dob_raw}' is invalid. Use DD/MM/YYYY format.",
                )
                continue

            try:
                username = generate_student_username(first_name, last_name, dob=dob)
            except (TypeError, ValueError) as exc:
                messages.error(request, f"Line {line_number}: could not generate username - {exc}.")
                continue

            password = generate_random_password()
            student, created = Student.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "year_group": year_group,
                    "date_of_birth": dob,
                    "password": password,
                    "school": school_to_assign,
                },
            )

            if not created and student.school != school_to_assign:
                messages.error(
                    request,
                    f"Line {line_number}: student '{username}' belongs to a different school and cannot be added.",
                )
                continue

            updated_fields: List[str] = []
            if not created:
                if student.first_name != first_name:
                    student.first_name = first_name
                    updated_fields.append("first_name")
                if student.last_name != last_name:
                    student.last_name = last_name
                    updated_fields.append("last_name")
                if student.year_group != year_group:
                    student.year_group = year_group
                    updated_fields.append("year_group")
                if student.date_of_birth != dob:
                    student.date_of_birth = dob
                    updated_fields.append("date_of_birth")
                if updated_fields:
                    student.save(update_fields=updated_fields)

            was_already_in_class = current_class.students.filter(id=student.id).exists()
            current_class.students.add(student)

            if created:
                created_students.append(student)
            elif was_already_in_class:
                already_in_class += 1
            else:
                attached_existing += 1

        if created_students:
            messages.success(
                request,
                (
                    f"Created {len(created_students)} new student account"
                    f"{'s' if len(created_students) != 1 else ''}. "
                    "You can review usernames and passwords from the class page."
                ),
            )

        if attached_existing:
            messages.success(
                request,
                f"Added {attached_existing} existing student{'s' if attached_existing != 1 else ''} to the class.",
            )

        if already_in_class:
            messages.info(
                request,
                f"{already_in_class} student{'s' if already_in_class != 1 else ''} were already enrolled and were skipped.",
            )

        if not created_students and not attached_existing and not already_in_class:
            messages.warning(
                request,
                "No students were added. Please check the data provided and try again.",
            )

        return redirect("teacher_dashboard")

    return render(request, "learning/add_students.html", {"class_instance": current_class})


@login_required
def edit_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        year_group_raw = request.POST.get("year_group", "").strip()
        dob_raw = request.POST.get("date_of_birth", "").strip()
        username_raw = request.POST.get("username", "").strip()
        password_raw = request.POST.get("password", "").strip()

        errors = False
        original_values = {
            "first_name": student.first_name,
            "last_name": student.last_name,
            "year_group": student.year_group,
            "date_of_birth": student.date_of_birth,
            "username": student.username,
            "password": student.password,
        }

        if not first_name:
            messages.error(request, "First name is required.")
            errors = True
        if not last_name:
            messages.error(request, "Last name is required.")
            errors = True

        year_group = student.year_group
        if not year_group_raw:
            messages.error(request, "Year group is required.")
            errors = True
        else:
            try:
                year_group = int(year_group_raw)
                if year_group <= 0:
                    raise ValueError
            except ValueError:
                messages.error(request, "Year group must be a positive number.")
                errors = True

        date_of_birth = student.date_of_birth
        if not dob_raw:
            messages.error(request, "Date of birth is required.")
            errors = True
        else:
            try:
                date_of_birth = datetime.strptime(dob_raw, "%Y-%m-%d").date()
            except ValueError:
                messages.error(request, "Date of birth must be in YYYY-MM-DD format.")
                errors = True

        username = student.username
        if not username_raw:
            messages.error(request, "Username is required.")
            errors = True
        else:
            username = username_raw.lower()
            if (
                Student.objects.filter(username=username)
                .exclude(id=student.id)
                .exists()
            ):
                messages.error(request, "That username is already in use by another student.")
                errors = True

        password = student.password
        if not password_raw:
            messages.error(request, "Password is required.")
            errors = True
        else:
            password = password_raw

        # Update the in-memory student object so the form reflects attempted changes
        if first_name:
            student.first_name = first_name
        if last_name:
            student.last_name = last_name
        student.year_group = year_group
        student.date_of_birth = date_of_birth
        if username_raw:
            student.username = username
        if password_raw:
            student.password = password

        if errors:
            return render(request, "learning/edit_student.html", {"student": student})

        updated_fields: List[str] = []
        if student.first_name != original_values["first_name"]:
            updated_fields.append("first_name")
        if student.last_name != original_values["last_name"]:
            updated_fields.append("last_name")
        if student.year_group != original_values["year_group"]:
            updated_fields.append("year_group")
        if student.date_of_birth != original_values["date_of_birth"]:
            updated_fields.append("date_of_birth")
        if student.username != original_values["username"]:
            updated_fields.append("username")
        if student.password != original_values["password"]:
            updated_fields.append("password")

        if updated_fields:
            student.save(update_fields=updated_fields)

        messages.success(request, "Student details updated successfully.")

        associated_class = student.classes.first()
        if associated_class:
            return redirect("edit_class", associated_class.id)
        return redirect("teacher_dashboard")
    return render(request, "learning/edit_student.html", {"student": student})


@login_required
def delete_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    associated_class = student.classes.first()
    if associated_class:
        class_id = associated_class.id
        student.delete()
        return redirect("edit_class", class_id)
    else:
        student.delete()
        return redirect("teacher_dashboard")


def delete_class(request, class_id):
    class_obj = get_object_or_404(Class, id=class_id)
    for student in class_obj.students.all():
        student.classes.remove(class_obj)
    class_obj.delete()
    return redirect('teacher_dashboard')


@login_required
def share_class(request, class_id):
    class_instance = get_object_or_404(Class, id=class_id)
    if request.method == 'POST':
        username = request.POST.get('username')
        try:
            teacher = User.objects.get(username=username)
            if teacher in class_instance.teachers.all():
                messages.error(request, f"{username} is already associated with this class.")
            else:
                class_instance.teachers.add(teacher)
                messages.success(request, f"{username} has been successfully added to the class.")
        except User.DoesNotExist:
            messages.error(request, f"User with username {username} does not exist.")
        return redirect('share_class', class_id=class_id)

    return render(request, 'learning/share_class.html', {'class_instance': class_instance})


@login_required
def remove_teacher_from_class(request, class_id, teacher_id):
    class_instance = get_object_or_404(Class, id=class_id)
    teacher = get_object_or_404(User, id=teacher_id)

    if class_instance.teachers.count() <= 1:
        messages.error(request, "Cannot remove the last teacher from the class. At least one teacher must remain associated.")
    elif teacher in class_instance.teachers.all():
        class_instance.teachers.remove(teacher)
        messages.success(request, f"{teacher.username} has been removed from the class.")
    else:
        messages.error(request, f"{teacher.username} is not associated with this class.")

    return redirect('share_class', class_id=class_id)


# ----------------------------
# Student Auth & Dashboard
# ----------------------------

def student_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        next_url = request.GET.get("next", "")

        try:
            student = Student.objects.get(username=username)
            if student.password == password:  # NOTE: replace with secure auth later
                request.session['student_id'] = str(student.id)
                student.last_login = now()
                student.save()
                return redirect(next_url if next_url else 'student_dashboard')
            else:
                messages.error(request, "Invalid username or password.")
        except Student.DoesNotExist:
            messages.error(request, "Student not found.")

    return render(request, "learning/student_login.html")


def student_dashboard(request):
    student_id = request.session.get("student_id")
    if not student_id:
        return redirect("student_login")

    student = get_object_or_404(Student, id=student_id)
    classes = student.classes.all()

    current_time = now()
    for class_instance in classes:
        for class_student in class_instance.students.all():
            class_student.reset_periodic_points()
        live_assignments = Assignment.objects.filter(
            class_assigned=class_instance,
            deadline__gte=current_time,
            is_closed=False,
        )
        expired_assignments = (
            Assignment.objects.filter(class_assigned=class_instance)
            .filter(Q(deadline__lt=current_time) | Q(is_closed=True))
        )

        for assignment in live_assignments:
            progress = AssignmentProgress.objects.filter(student=student, assignment=assignment).first()
            assignment.student_progress = progress.points_earned if progress else 0
            assignment.target_points = assignment.target_points or 1
            assignment.progress_percentage = (assignment.student_progress / assignment.target_points) * 100
            assignment.is_complete = progress.completed if progress else False

        for assignment in expired_assignments:
            progress = AssignmentProgress.objects.filter(student=student, assignment=assignment).first()
            assignment.student_progress = progress.points_earned if progress else 0
            assignment.target_points = assignment.target_points or 1
            assignment.progress_percentage = (assignment.student_progress / assignment.target_points) * 100
            assignment.is_complete = progress.completed if progress else False

        class_instance.live_assignments = live_assignments
        class_instance.expired_assignments = expired_assignments
        class_instance.leaderboards = {
            "total_points": class_instance.students.order_by("-total_points"),
            "monthly_points": class_instance.students.order_by("-monthly_points"),
            "weekly_points": class_instance.students.order_by("-weekly_points"),
        }

    vocab_lists = VocabularyList.objects.filter(classes__in=classes).distinct()
    leaderboard_categories = [
        {"category": "total_points", "icon": "🔥", "title": "Total Points"},
        {"category": "monthly_points", "icon": "📅", "title": "Monthly Points"},
        {"category": "weekly_points", "icon": "📆", "title": "Weekly Points"},
    ]

    user = _get_user_from_student(student)
    achievement_unlocks = list(
        TrophyUnlock.objects.filter(user=user)
        .select_related("trophy")
        .order_by("-earned_at")
    )
    total_achievements = AchievementTrophy.objects.count()

    recent_trophies: List[Dict[str, Any]] = [
        {
            "name": unlock.trophy.name,
            "description": unlock.trophy.description,
            "icon_url": _trophy_icon_url(unlock.trophy.icon),
            "earned_at": unlock.earned_at,
        }
        for unlock in achievement_unlocks[:5]
    ]

    unlocked_count = len(achievement_unlocks)
    popup_payload: List[Dict[str, Any]] = []
    popup_tracker: List[str] = []
    seen_popup_ids = set(request.session.get("seen_trophy_popup_ids", []))

    for unlock in achievement_unlocks:
        popup_key = f"ach-{unlock.pk}"
        popup_tracker.append(popup_key)
        if popup_key not in seen_popup_ids:
            popup_payload.append(
                {
                    "name": unlock.trophy.name,
                    "description": unlock.trophy.description,
                    "icon": _trophy_icon_url(unlock.trophy.icon),
                }
            )

    if not achievement_unlocks:
        legacy_unlocks = list(
            student.trophies.select_related("trophy").order_by("-earned_at")
        )
        recent_trophies = [
            {
                "name": legacy.trophy.name,
                "description": legacy.trophy.description,
                "icon_url": _trophy_icon_url(legacy.trophy.icon),
                "earned_at": legacy.earned_at,
            }
            for legacy in legacy_unlocks[:5]
        ]
        unlocked_count = len(legacy_unlocks)

        for legacy in legacy_unlocks:
            popup_key = f"legacy-{legacy.pk}"
            popup_tracker.append(popup_key)
            if popup_key not in seen_popup_ids:
                popup_payload.append(
                    {
                        "name": legacy.trophy.name,
                        "description": legacy.trophy.description,
                        "icon": _trophy_icon_url(legacy.trophy.icon),
                    }
                )

    request.session["seen_trophy_popup_ids"] = list(dict.fromkeys(popup_tracker))
    new_trophies_json = json.dumps(popup_payload)

    return render(request, "learning/student_dashboard.html", {
        "student": student,
        "classes": classes,
        "vocab_lists": vocab_lists,
        "leaderboard_categories": leaderboard_categories,
        "recent_trophies": recent_trophies,
        "achievement_total": total_achievements,
        "unlocked_trophy_count": unlocked_count,
        "new_trophies_json": new_trophies_json,
    })


# ----------------------------
# Student Word Views & Practice
# ----------------------------


def student_trophies(request):
    student_id = request.session.get("student_id")
    if not student_id:
        return redirect("student_login")

    student = get_object_or_404(Student, id=student_id)
    user = _get_user_from_student(student)

    achievement_definitions = list(
        AchievementTrophy.objects.all().order_by("category", "name")
    )
    unlocks = list(
        TrophyUnlock.objects.filter(user=user)
        .select_related("trophy")
        .order_by("-earned_at")
    )
    unlock_map = {unlock.trophy_id: unlock for unlock in unlocks}

    trophies: List[Dict[str, Any]] = []
    for trophy in achievement_definitions:
        unlock = unlock_map.get(trophy.id)
        unlocked = unlock is not None
        trophies.append(
            {
                "id": trophy.id,
                "name": trophy.name,
                "category": trophy.category,
                "description": trophy.description,
                "icon_url": _trophy_icon_url(trophy.icon),
                "unlocked": unlocked,
                "earned_at": unlock.earned_at if unlock else None,
                "progress": _trophy_progress(user, trophy, unlocked),
            }
        )

    achievements_available = bool(achievement_definitions)

    if not achievements_available:
        legacy_unlocks = list(
            student.trophies.select_related("trophy").order_by("-earned_at")
        )
        trophies = [
            {
                "id": str(legacy.trophy_id),
                "name": legacy.trophy.name,
                "category": getattr(legacy.trophy, "category", "Legacy"),
                "description": legacy.trophy.description,
                "icon_url": _trophy_icon_url(legacy.trophy.icon),
                "unlocked": True,
                "earned_at": legacy.earned_at,
                "progress": None,
            }
            for legacy in legacy_unlocks
        ]

    unlocked_count = sum(1 for trophy in trophies if trophy["unlocked"])
    total_count = len(trophies)
    unlocked_trophies = [trophy for trophy in trophies if trophy["unlocked"]]
    locked_trophies = [trophy for trophy in trophies if not trophy["unlocked"]]

    return render(
        request,
        "learning/student_trophies.html",
        {
            "student": student,
            "trophies": trophies,
            "unlocked_count": unlocked_count,
            "total_count": total_count,
            "achievements_available": achievements_available,
            "unlocked_trophies": unlocked_trophies,
            "locked_trophies": locked_trophies,
        },
    )


# ----------------------------
# Student Word Views & Practice
# ----------------------------

@student_login_required
def my_words(request):
    """Display a student's vocabulary words with optional search and sort."""
    student_id = request.session.get("student_id")
    student = get_object_or_404(Student, id=student_id)
    user = _get_user_from_student(student)

    progress_qs = Progress.objects.filter(student=user).select_related("word", "word__list")

    class_id = request.GET.get("class")
    list_id = request.GET.get("list")
    if class_id:
        progress_qs = progress_qs.filter(word__list__classes__id=class_id)
    if list_id:
        progress_qs = progress_qs.filter(word__list__id=list_id)

    search_query = request.GET.get("search")
    if search_query:
        progress_qs = progress_qs.filter(
            Q(word__word__icontains=search_query) | Q(word__translation__icontains=search_query)
        )

    progress_data = []
    now = timezone.now()
    for prog in progress_qs:
        total_attempts = prog.correct_attempts + prog.incorrect_attempts
        memory_percent, memory_color = memory_meter(prog, now=now)
        progress_data.append(
            {
                "text": prog.word.word,
                "translation": prog.word.translation,
                "list": prog.word.list,
                "last_seen": prog.last_seen,
                "total_attempts": total_attempts,
                "memory_percent": memory_percent,
                "memory_color": memory_color,
            }
        )

    classes = student.classes.all()
    vocab_lists = (
        VocabularyList.objects.filter(words__progress__student=user).distinct()
    )

    sort_key = request.GET.get("sort")
    if sort_key == "last_seen":
        progress_data.sort(
            key=lambda x: x["last_seen"] or datetime.min, reverse=True
        )
    elif sort_key == "attempts":
        progress_data.sort(
            key=lambda x: x["total_attempts"], reverse=True
        )
    elif sort_key == "memory":
        progress_data.sort(
            key=lambda x: x["memory_percent"], reverse=True
        )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        for item in progress_data:
            item["last_seen"] = (
                item["last_seen"].isoformat() if item["last_seen"] else None
            )
            item["list"] = item["list"].name
        return JsonResponse({"words": progress_data})

    grouped = defaultdict(list)
    for item in progress_data:
        grouped[item["list"]].append(
            {
                "text": item["text"],
                "last_seen": item["last_seen"],
                "total_attempts": item["total_attempts"],
                "memory_percent": item["memory_percent"],
                "memory_color": item["memory_color"],
            }
        )

    grouped_progress = sorted(grouped.items(), key=lambda kv: kv[0].name)

    return render(
        request,
        "learning/my_words.html",
        {
            "student": student,
            "grouped_progress": grouped_progress,
            "classes": classes,
            "vocab_lists": vocab_lists,
            "selected_class": class_id,
            "selected_list": list_id,
        },
    )


def get_words(request):
    vocabulary_list_id = request.GET.get("vocabulary_list_id")
    words = VocabularyWord.objects.filter(list_id=vocabulary_list_id).values("id", "word")
    return JsonResponse({"words": list(words)})


@student_login_required
def practice_session(request, vocab_list_id):
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    queue_key = f"practice_queue_{vocab_list_id}"
    queue = request.session.get(queue_key, [])
    if queue and "activities" not in queue[0]:
        queue = []

    def _image_payload(word: VocabularyWord) -> Optional[Dict[str, str]]:
        if not word.image_url or not word.image_approved:
            return None
        return {
            "url": word.image_url,
            "thumb": word.image_thumb_url or word.image_url,
            "source": word.image_source or "",
            "attribution": word.image_attribution or "",
            "license": word.image_license or "",
            "alt": word.word,
        }
    exposure_activities = ["show_word", "flashcard"]
    testing_activities = ["typing", "fill_gaps", "multiple_choice", "true_false"]
    matchup_key = f"matchup_shown_{vocab_list_id}"

    def _init_queue():
        words = get_due_words(student, vocab_list, limit=3)
        q = []
        for w in words:
            acts = exposure_activities + random.sample(testing_activities, len(testing_activities))
            q.append({"id": w.id, "step": 0, "activities": acts})
        random.shuffle(q)
        return q

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("next"):
        if not queue:
            queue = _init_queue()
            request.session[matchup_key] = []
        if not queue:
            return JsonResponse({"completed": True})

        shown_matchups = request.session.get(matchup_key, [])
        warmed = [
            item
            for item in queue
            if item["step"] >= len(exposure_activities) and item["id"] not in shown_matchups
        ]
        if len(warmed) >= 5 and random.random() < 0.3:
            selected = random.sample(warmed, 5)
            ids = [i["id"] for i in selected]
            words = VocabularyWord.objects.filter(id__in=ids)
            shown_matchups.extend(ids)
            request.session[matchup_key] = shown_matchups
            request.session[queue_key] = queue
            payload = {
                "type": "match_up",
                "words": [
                    {
                        "id": w.id,
                        "word": w.word,
                        "translation": w.translation,
                        "image": _image_payload(w),
                    }
                    for w in words
                ],
            }
            return JsonResponse(payload)

        item = queue.pop(0)
        word = VocabularyWord.objects.get(id=item["id"])
        activity = item["activities"][item["step"]]
        image_data = _image_payload(word)

        if item["step"] + 1 < len(item["activities"]):
            item["step"] += 1
            queue.append(item)
            random.shuffle(queue)
        request.session[queue_key] = queue

        if activity == "show_word":
            payload = {
                "type": "show_word",
                "word_id": word.id,
                "prompt": word.translation,
                "answer": word.word,
            }
        elif activity == "flashcard":
            payload = {
                "type": "flashcard",
                "word_id": word.id,
                "prompt": word.word,
                "answer": word.translation,
            }
        elif activity == "typing":
            if random.choice([True, False]):
                prompt, answer = word.word, word.translation
                answer_language = "target"
            else:
                prompt, answer = word.translation, word.word
                answer_language = "source"
            payload = {
                "type": "typing",
                "word_id": word.id,
                "prompt": prompt,
                "answer": answer,
                "answer_language": answer_language,
            }
        elif activity == "fill_gaps":
            if random.choice([True, False]):
                source, target = word.translation, word.word
                answer_language = "source"
            else:
                source, target = word.word, word.translation
                answer_language = "target"
            masked = list(target)
            indices = list(range(len(masked)))
            random.shuffle(indices)
            for i in indices[: len(masked) // 2]:
                if masked[i].isalpha():
                    masked[i] = "_"
            payload = {
                "type": "fill_gaps",
                "word_id": word.id,
                "prompt": "".join(masked),
                "translation": source,
                "answer": target,
                "answer_language": answer_language,
            }
        elif activity == "multiple_choice":
            if random.choice([True, False]):
                prompt = word.word
                answer = word.translation
                distractors = list(
                    VocabularyWord.objects.filter(list=vocab_list)
                    .exclude(id=word.id)
                    .values_list("translation", flat=True)
                )
            else:
                prompt = word.translation
                answer = word.word
                distractors = list(
                    VocabularyWord.objects.filter(list=vocab_list)
                    .exclude(id=word.id)
                    .values_list("word", flat=True)
                )
            random.shuffle(distractors)
            options = distractors[:3] + [answer]
            random.shuffle(options)
            payload = {
                "type": "multiple_choice",
                "word_id": word.id,
                "prompt": prompt,
                "options": options,
                "answer": answer,
            }
        elif activity == "true_false":
            if random.choice([True, False]):
                prompt, correct_answer = word.word, word.translation
                pool = VocabularyWord.objects.filter(list=vocab_list).exclude(id=word.id).values_list(
                    "translation", flat=True
                )
            else:
                prompt, correct_answer = word.translation, word.word
                pool = VocabularyWord.objects.filter(list=vocab_list).exclude(id=word.id).values_list(
                    "word", flat=True
                )
            translations = list(pool)
            shown = correct_answer
            if translations and random.choice([True, False]):
                shown = random.choice(translations)
            payload = {
                "type": "true_false",
                "word_id": word.id,
                "prompt": prompt,
                "shown_translation": shown,
                "answer": shown == correct_answer,
            }
        else:
            payload = {"type": "unknown"}

        if image_data:
            payload["image"] = image_data
        return JsonResponse(payload)

    if not queue:
        queue = _init_queue()
        request.session[queue_key] = queue

    return render(request, "learning/practice_session.html", {"vocab_list": vocab_list})


@student_login_required
def flashcard_mode(request, vocab_list_id):
    try:
        student = Student.objects.get(id=request.session.get('student_id'))
    except Student.DoesNotExist:
        return redirect("student_login")

    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/flashcard_mode.html", {
        "vocab_list": vocab_list,
        "words": words,
        "student": student,
    })


def match_up_mode(request, vocab_list_id=None, assignment_id=None):
    if assignment_id:
        assignment = get_object_or_404(Assignment, id=assignment_id)
        vocab_list = assignment.vocab_list
    elif vocab_list_id:
        vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
        assignment = None
    else:
        raise Http404("No assignment or vocab list specified.")

    student = get_object_or_404(Student, id=request.session.get('student_id'))

    words_objs = get_due_words(student, vocab_list, limit=10)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    source_words = words
    target_words = words[:]
    random.shuffle(target_words)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/match_up_mode.html", {
        "vocab_list": vocab_list,
        "source_words": source_words,
        "target_words": target_words,
        "student": student,
    })


@student_login_required
def gap_fill_mode(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/gap_fill_mode.html", {"vocab_list": vocab_list, "words": words})


@csrf_exempt
@require_POST
def update_progress(request):
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    try:
        data = json.loads(request.body.decode())
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    word_id = data.get("word_id")
    correct = data.get("correct")
    if word_id is None or correct is None:
        return JsonResponse({"error": "Missing parameters"}, status=400)
    schedule_review(student, word_id, bool(correct))
    return JsonResponse({"status": "ok"})


# ----------------------------
# Lead Teacher / Admin
# ----------------------------

@login_required
def lead_teacher_dashboard(request):
    if not request.user.is_lead_teacher:
        return redirect("login")

    school = request.user.school
    teachers = User.objects.filter(school=school, is_teacher=True)
    students = Student.objects.filter(school=school)
    vocab_lists = VocabularyList.objects.filter(teacher__school=school)

    return render(request, "learning/lead_teacher_dashboard.html", {
        "school": school,
        "teachers": teachers,
        "students": students,
        "vocab_lists": vocab_lists,
    })


def register_teacher(request):
    from .forms import TeacherRegistrationForm
    if request.method == "POST":
        form = TeacherRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.school, _ = School.objects.get_or_create(name="Default School")
            user.save()
            user.add_credits(1)  # free Pavonicoin
            login(request, user)
            messages.success(request, "Your account has been created successfully! You have received 1 free Pavonicoin to test the Reading Lab.")
            return redirect("teacher_dashboard")
        else:
            messages.error(request, "There were errors in the form. Please correct them.")
    else:
        form = TeacherRegistrationForm()

    return render(request, "learning/register_teacher.html", {"form": form})


def lead_teacher_login(request):
    return render(request, "learning/lead_teacher_login.html")


def teacher_upgrade(request):
    return redirect('/teacher-dashboard/#teacher-upgrade')


def school_signup(request):
    return render(request, "learning/school_signup.html")


# ----------------------------
# Class Leaderboard (Teacher)
# ----------------------------

@login_required
def class_leaderboard(request, class_id):
    class_instance = get_object_or_404(Class, id=class_id)
    if request.user not in class_instance.teachers.all():
        return HttpResponseForbidden("You do not have permission to view this class leaderboard.")

    category = request.GET.get("category", "total_points")
    if category not in {"total_points", "weekly_points", "monthly_points"}:
        category = "total_points"

    students_qs = class_instance.students.all()
    for student in students_qs:
        student.reset_periodic_points()
    students = students_qs.order_by(f"-{category}")
    column_labels = {
        "total_points": "Total Points",
        "weekly_points": "Weekly Points",
        "monthly_points": "Monthly Points",
    }

    context = {
        "class_instance": class_instance,
        "students": students,
        "current_category": category,
        "column_label": column_labels[category],
    }
    return render(request, "learning/class_leaderboard.html", context)


@login_required
def refresh_leaderboard(request, class_id):
    class_instance = get_object_or_404(Class, id=class_id)
    if request.user not in class_instance.teachers.all():
        return HttpResponseForbidden("You do not have permission to view this class leaderboard.")

    category = request.GET.get("category", "total_points")
    if category not in {"total_points", "weekly_points", "monthly_points"}:
        category = "total_points"

    students_qs = class_instance.students.all()
    for student in students_qs:
        student.reset_periodic_points()
    students = students_qs.order_by(f"-{category}")
    column_labels = {
        "total_points": "Total Points",
        "weekly_points": "Weekly Points",
        "monthly_points": "Monthly Points",
    }

    return render(request, "learning/leaderboard_fragment.html", {
        "class_instance": class_instance,
        "students": students,
        "current_category": category,
        "column_label": column_labels[category],
    })


# ----------------------------
# Assignments
# ----------------------------

@login_required
def create_assignment(request, class_id):
    class_assigned = get_object_or_404(Class, id=class_id)
    vocab_lists = class_assigned.vocabulary_lists.all()  # linked to this class

    if request.method == "POST":
        name = request.POST.get("name")
        vocab_list_id = request.POST.get("vocab_list")
        deadline = request.POST.get("deadline")
        target_points = int(request.POST.get("target_points"))

        # FIX: ensure the M2M is checked against `classes` not `linked_classes`
        vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id, classes=class_assigned)

        Assignment.objects.create(
            name=name,
            class_assigned=class_assigned,
            vocab_list=vocab_list,
            deadline=deadline,
            target_points=target_points,
            teacher=request.user,
        )
        messages.success(request, "Assignment created successfully!")
        return redirect("teacher_dashboard")

    return render(request, "learning/create_assignment.html", {
        "class_assigned": class_assigned,
        "vocab_lists": vocab_lists,
    })


@csrf_exempt
def update_assignment_points(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            assignment_id = data.get("assignment_id")
            points = int(data.get("points"))

            student_id = request.session.get("student_id")
            if not (assignment_id and points and student_id):
                return JsonResponse({"success": False, "error": "Invalid data"})

            student = get_object_or_404(Student, id=student_id)
            assignment = get_object_or_404(Assignment, id=assignment_id)

            assignment_progress, _ = AssignmentProgress.objects.get_or_create(student=student, assignment=assignment)
            assignment_progress.update_progress(points, timedelta())

            student.add_points(points)
            new_trophies = check_and_award_trophies(student)

            return JsonResponse({
                "success": True,
                "new_total_points": student.total_points,
                "current_assignment_points": assignment_progress.points_earned,
                "new_trophies": new_trophies,
            })

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e), "new_trophies": []})

    return JsonResponse({"success": False, "error": "Invalid request method", "new_trophies": []})


@login_required
def delete_assignment(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    if request.user != assignment.teacher:
        messages.error(request, "You are not authorized to delete this assignment.")
        return redirect("teacher_dashboard")

    assignment.delete()
    messages.success(request, "Assignment deleted successfully.")
    return redirect("teacher_dashboard")


@login_required
@require_POST
def close_assignment(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)

    if request.user != assignment.teacher:
        messages.error(request, "You are not authorized to close this assignment.")
        return redirect("teacher_dashboard")

    if assignment.is_closed:
        messages.info(request, "This assignment is already closed.")
    else:
        assignment.is_closed = True
        assignment.save(update_fields=["is_closed"])
        messages.success(request, "Assignment closed successfully.")

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)

    return redirect("teacher_dashboard")


@student_login_required
def assignment_page(request, assignment_id):
    student_id = request.session.get("student_id")
    if not student_id:
        return redirect("student_login")

    student = get_object_or_404(Student, id=student_id)
    assignment = get_object_or_404(Assignment, id=assignment_id)

    if assignment.is_closed:
        messages.info(request, "This assignment has been closed by your teacher.")
        return redirect("student_dashboard")

    if not assignment.class_assigned.students.filter(id=student.id).exists():
        return render(request, "learning/access_denied.html", status=403)
    progress, _ = AssignmentProgress.objects.get_or_create(student=student, assignment=assignment)

    return render(request, "learning/assignment_practice_session.html", {
        "assignment": assignment,
        "vocab_list": assignment.vocab_list,
        "student": student,
        "total_points": assignment.target_points,
        "current_points": progress.points_earned,
    })


def access_denied(request):
    return render(request, "learning/access_denied.html")


@student_login_required
def gap_fill_mode_assignment(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    vocab_list = assignment.vocab_list

    words_objs = get_due_words(student, vocab_list, limit=20)
    words_list = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words_list})

    assignment_progress = AssignmentProgress.objects.filter(assignment=assignment, student=student).first()
    current_points = assignment_progress.points_earned if assignment_progress else 0

    return render(request, "learning/assignment_modes/gap_fill_mode_assignment.html", {
        "assignment": assignment,
        "words_json": json.dumps(words_list),
        "student": student,
        "total_points": assignment.target_points,
        "current_points": current_points,
        "source_language": vocab_list.source_language,
        "target_language": vocab_list.target_language,
        "points": assignment.points_per_fill_gap,
    })


@student_login_required
def destroy_wall_mode_assignment(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    vocab_list = assignment.vocab_list

    words_objs = get_due_words(student, vocab_list, limit=30)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    context = {
        "assignment": assignment,
        "words_json": json.dumps(words),
        "student": student,
        "points": assignment.points_per_destroy_wall,
    }
    return render(request, "learning/assignment_modes/destroy_the_wall_assignment.html", context)


def match_up_mode_assignment(request, vocab_list_id=None, assignment_id=None):
    if assignment_id:
        assignment = get_object_or_404(Assignment, id=assignment_id)
        vocab_list = assignment.vocab_list
    elif vocab_list_id:
        vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
        assignment = None
    else:
        raise Http404("No assignment or vocab list specified.")

    student = get_object_or_404(Student, id=request.session.get('student_id'))

    words_objs = get_due_words(student, vocab_list, limit=10)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    source_words = words
    target_words = words[:]
    random.shuffle(target_words)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    context = {
        "vocab_list": vocab_list,
        "source_words": source_words,
        "target_words": target_words,
        "student": student,
        "assignment": assignment,
        "points": assignment.points_per_matchup if assignment else 0,
    }
    return render(request, "learning/assignment_modes/match_up_mode_assignment.html", context)


@student_login_required
def unscramble_the_word_assignment(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    vocab_list = assignment.vocab_list

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/assignment_modes/unscramble_the_word_assignment.html", {
        "assignment": assignment,
        "words_json": json.dumps(words),
        "student": student,
        "points": assignment.points_per_unscramble,
    })


@student_login_required
def flashcard_mode_assignment(request, assignment_id):
    try:
        student = Student.objects.get(id=request.session.get('student_id'))
    except Student.DoesNotExist:
        return redirect("student_login")

    assignment = get_object_or_404(Assignment, id=assignment_id)
    vocab_list = assignment.vocab_list

    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/assignment_modes/flashcard_mode_assignment.html", {
        "vocab_list": vocab_list,
        "words": words,
        "student": student,
    })


# ----------------------------
# Assignment Attempts & Analytics
# ----------------------------

@student_login_required
@require_POST
def log_assignment_attempt(request):
    try:
        data = json.loads(request.body)
        assignment_id = data.get("assignment_id")
        word_id = data.get("word_id")
        is_correct = data.get("is_correct")

        if assignment_id is None or word_id is None or is_correct is None:
            return HttpResponseBadRequest("Missing required parameters.")

        assignment = get_object_or_404(Assignment, id=assignment_id)
        student = get_object_or_404(Student, id=request.session.get("student_id"))

        if not assignment.class_assigned.students.filter(id=student.id).exists():
            return HttpResponseForbidden("You are not enrolled in this class.")

        vocab_word = get_object_or_404(VocabularyWord, id=word_id)
        mode = data.get("mode")
        if not mode:
            return HttpResponseBadRequest("Missing mode parameter.")

        AssignmentAttempt.objects.create(
            student=student,
            assignment=assignment,
            vocabulary_word=vocab_word,
            mode=mode,
            is_correct=is_correct
        )
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


@login_required
def assignment_analytics(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)

    if not request.user.is_authenticated or not getattr(request.user, "is_teacher", False):
        return HttpResponseForbidden("You do not have permission to view this assignment's analytics.")
    if assignment.teacher_id != request.user.id and not assignment.class_assigned.teachers.filter(id=request.user.id).exists():
        return HttpResponseForbidden("You do not have permission to view this assignment's analytics.")

    progress_list = AssignmentProgress.objects.filter(assignment=assignment)

    attempts = list(
        AssignmentAttempt.objects.filter(assignment=assignment)
        .select_related("student", "vocabulary_word")
        .order_by("timestamp")
    )

    # Student summary
    student_summary = {}
    for att in attempts:
        sid = att.student.id
        wid = att.vocabulary_word.id
        s = student_summary.setdefault(sid, {"student": att.student, "words": {}})
        if wid not in s["words"]:
            s["words"][wid] = {"word": att.vocabulary_word.translation, "wrong": 0, "aced": False}
        if not s["words"][wid]["aced"]:
            if att.is_correct:
                s["words"][wid]["aced"] = True
            else:
                s["words"][wid]["wrong"] += 1

    student_summary_list = []
    for s in student_summary.values():
        words_aced, attempts_wrong = [], []
        for data in s["words"].values():
            if data["aced"]:
                words_aced.append(data["word"])
                if data["wrong"] > 0:
                    attempts_wrong.append((data["word"], data["wrong"]))
        student_summary_list.append({
            "student": s["student"],
            "words_aced": words_aced,
            "attempts_wrong": attempts_wrong,
        })

    # Word summary
    word_summary_dict = {}
    for att in attempts:
        wid = att.vocabulary_word.id
        w = word_summary_dict.setdefault(wid, {
            "word": att.vocabulary_word.translation,
            "wrong_attempts": 0,
            "total_attempts": 0,
            "students": set(),
        })
        w["total_attempts"] += 1
        if not att.is_correct:
            w["wrong_attempts"] += 1
            w["students"].add(att.student.id)

    word_summary_list = []
    for w in word_summary_dict.values():
        total = w["total_attempts"]
        percentage = (w["wrong_attempts"] / total) * 100 if total else 0
        word_summary_list.append({
            "word": w["word"],
            "wrong_attempts": w["wrong_attempts"],
            "students_difficulty": len(w["students"]),
            "difficulty_percentage": percentage,
        })

    # Feedback
    first_attempts = {}
    for att in attempts:
        key = (att.student.id, att.vocabulary_word.id)
        if key not in first_attempts:
            first_attempts[key] = att.is_correct

    easy_words, difficult_words = [], []
    for (sid, wid), is_correct in first_attempts.items():
        word_text = word_summary_dict[wid]["word"]
        if is_correct:
            easy_words.append(word_text)
        else:
            difficult_words.append(word_text)

    word_cloud_easy = list(set(easy_words))
    word_cloud_difficult = list(set(difficult_words))

    top_difficult_words = sorted(word_summary_list, key=lambda x: x["students_difficulty"], reverse=True)[:10]

    context = {
        "assignment": assignment,
        "progress_list": progress_list,
        "student_summary": student_summary_list,
        "word_summary": word_summary_list,
        "word_cloud_easy": word_cloud_easy,
        "word_cloud_difficult": word_cloud_difficult,
        "top_difficult_words": top_difficult_words,
    }

    return render(request, "learning/assignment_analytics.html", context)


# ----------------------------
# Trophies
# ----------------------------

def check_and_award_trophies(student):
    new_trophies = []

    # Streak Awards
    streak_awards = {3: "Warm-Up", 7: "On Fire!", 30: "Unstoppable!", 100: "Legendary Commitment!"}
    for days, trophy_name in streak_awards.items():
        if student.current_streak >= days:
            trophy, _ = Trophy.objects.get_or_create(name=trophy_name, defaults={"description": f"Awarded for a {days}-day streak!"})
            _, created = StudentTrophy.objects.get_or_create(student=student, trophy=trophy)
            if created:
                new_trophies.append(trophy_name)

    # Points Milestones
    points_awards = {500: "Rising Star", 1000: "Language Warrior", 5000: "Master Linguist", 10000: "Polyglot Prodigy"}
    for points, trophy_name in points_awards.items():
        if student.total_points >= points:
            trophy, _ = Trophy.objects.get_or_create(name=trophy_name, defaults={"description": f"Earned {points} points!"})
            _, created = StudentTrophy.objects.get_or_create(student=student, trophy=trophy)
            if created:
                new_trophies.append(trophy_name)

    # Assignment Mastery
    assignments_awards = {5: "Diligent Scholar", 20: "Task Crusher", 50: "Perfectionist"}
    for count, trophy_name in assignments_awards.items():
        if student.assignments_completed >= count:
            trophy, _ = Trophy.objects.get_or_create(name=trophy_name, defaults={"description": f"Completed {count} assignments!"})
            _, created = StudentTrophy.objects.get_or_create(student=student, trophy=trophy)
            if created:
                new_trophies.append(trophy_name)

    # Game Achievements
    game_awards = {
        "flashcard_games_played": (100, "Flashcard Pro"),
        "match_up_games_played": (50, "Puzzle Master"),
        "destroy_wall_games_played": (50, "Wall Destroyer"),
    }
    for field, (threshold, trophy_name) in game_awards.items():
        if getattr(student, field, 0) >= threshold:
            trophy, _ = Trophy.objects.get_or_create(name=trophy_name, defaults={"description": f"Played {threshold} times!"})
            _, created = StudentTrophy.objects.get_or_create(student=student, trophy=trophy)
            if created:
                new_trophies.append(trophy_name)

    return new_trophies


# ----------------------------
# Payments / Subscriptions
# ----------------------------

@csrf_exempt
def create_checkout_session(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request, POST required"}, status=400)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": "price_1QpQcMJYDgv8Jx3VdIdRmwsL", "quantity": 1}],
            mode="subscription",
            success_url="https://www.pavonify.com/payment-success/",
            cancel_url="https://www.pavonify.com/teacher-dashboard/",
            client_reference_id=str(request.user.id),
            subscription_data={"metadata": {"teacher_id": str(request.user.id)}},
        )
        return JsonResponse({"checkout_url": session.url})
    except stripe.error.StripeError as e:
        return JsonResponse({"error": str(e)}, status=400)


def payment_success(request):
    return render(request, "learning/payment_success.html")


@csrf_exempt
def register_success(request):
    session_id = request.GET.get("session_id")
    if not session_id:
        return redirect("register-fail")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == "paid":
            email = session.customer_email
            username = session.metadata.get("username")
            password = session.metadata.get("password")

            if not email or not password:
                return redirect("register-fail")

            user, created = User.objects.get_or_create(email=email, username=username)
            if created:
                user.set_password(password)
                user.save()
                Teacher.objects.create(user=user, is_premium=True)

            return redirect("dashboard")
        else:
            return redirect("register-fail")
    except stripe.error.StripeError:
        return redirect("register-fail")


@login_required
def teacher_account_settings(request):
    if request.method == "POST":
        request.user.first_name = request.POST.get("first_name", request.user.first_name)
        request.user.last_name = request.POST.get("last_name", request.user.last_name)
        request.user.email = request.POST.get("email", request.user.email)
        new_password = request.POST.get("password")
        if new_password:
            request.user.set_password(new_password)
        request.user.save()
        return redirect("teacher_dashboard")
    return render(request, "teacher_dashboard.html")


@login_required
def teacher_cancel_subscription(request):
    teacher = request.user
    if teacher.subscription_id:
        try:
            stripe.Subscription.modify(teacher.subscription_id, cancel_at_period_end=True)
            teacher.subscription_cancelled = True
            teacher.save()
            messages.success(
                request,
                f"Your subscription is set to cancel at the end of the current period. Your premium benefits will end on {teacher.premium_expiration.strftime('%B %d, %Y')}."
            )
        except stripe.error.StripeError as e:
            messages.error(request, f"An error occurred while canceling your subscription: {e.user_message}")
    else:
        messages.error(request, "No active subscription was found.")
    return redirect("teacher_dashboard")


@login_required
def buy_pavicoins(request):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': 'price_1QyTOsJYDgv8Jx3V96D0iJoR', 'quantity': 1}],
            mode='payment',
            success_url=request.build_absolute_uri(reverse('pavicoins_success')),
            cancel_url=request.build_absolute_uri(reverse('teacher_dashboard')),
            metadata={'user_id': request.user.id},
        )
        return redirect(session.url)
    except stripe.error.StripeError as e:
        messages.error(request, f"Stripe error: {str(e)}")
        return redirect('teacher_dashboard')


@login_required
def pavicoins_success(request):
    messages.success(request, "Purchase successful! 20 Pavonicoins have been added to your account.")
    return redirect('teacher_dashboard')


def delete_teacher_account(request):
    if request.method == "POST" and request.user.is_authenticated:
        user = request.user
        user.delete()
        logout(request)
        return JsonResponse({"success": True})
    return JsonResponse({"success": False}, status=400)


# ----------------------------
# Reading Lab
# ----------------------------

EXAM_BOARD_TOPICS = {
    "iGCSE Cambridge": [
        "Everyday Activities",
        "Personal and Social Life",
        "The World Around Us",
        "The World of Work",
        "The International World"
    ],
    "GCSE AQA": [
        "Identity and Culture",
        "Local, National, International, and Global Areas of Interest",
        "Current and Future Study and Employment"
    ],
    "GCSE Edexcel": [
        "Identity and Culture",
        "Local Area, Holiday, and Travel",
        "School",
        "Future Aspirations, Study, and Work",
        "International and Global Dimension"
    ],
    "IB MYP": [
        "Identities and Relationships",
        "Personal and Cultural Expression",
        "Orientation in Space and Time",
        "Scientific and Technical Innovation",
        "Globalization and Sustainability",
        "Fairness and Development"
    ],
    "IB DP": [
        "Identities",
        "Experiences",
        "Human Ingenuity",
        "Social Organization",
        "Sharing the Planet"
    ],
    "A Level Edexcel": [
        "Changes in Society",
        "Political and Artistic Culture in the Target Language-speaking World",
        "Multiculturalism and Immigration",
        "Historical Developments and Resistance Movements"
    ],
    "A Level AQA": [
        "Aspects of Society: Current Trends",
        "Aspects of Society: Current Issues",
        "Artistic Culture in the Target Language-speaking World",
        "Aspects of Political Life in the Target Language-speaking World"
    ]
}

LANGUAGE_MAP = {
    'en': 'English',
    'de': 'German',
    'fr': 'French',
    'sp': 'Spanish',
    'it': 'Italian',
}


@login_required
def reading_lab(request):
    if request.method == "POST":
        if not request.user.is_teacher or request.user.ai_credits <= 0:
            return render(request, "error.html", {"message": "You do not have enough AI credits or are not a teacher."})

        vocabulary_list_id = request.POST.get("vocabulary_list")
        selected_word_ids = request.POST.getlist("selected_words")
        exam_board = request.POST.get("exam_board")
        topic = request.POST.get("topic")
        custom_topic = request.POST.get("custom_topic")
        if custom_topic:
            topic = custom_topic
        level = request.POST.get("level")
        word_count = int(request.POST.get("word_count", 100))
        tenses = request.POST.getlist("tenses")

        vocabulary_list = VocabularyList.objects.get(id=vocabulary_list_id)
        selected_words = VocabularyWord.objects.filter(id__in=selected_word_ids)

        source_lang_code = vocabulary_list.source_language
        target_lang_code = vocabulary_list.target_language
        source_lang_name = LANGUAGE_MAP.get(source_lang_code, 'Unknown')
        target_lang_name = LANGUAGE_MAP.get(target_lang_code, 'Unknown')

        selected_pairs = ", ".join([f"{w.word} = {w.translation}" for w in selected_words])

        prompt = (
            f"Generate a parallel text in {source_lang_name} and {target_lang_name} "
            f"on the topic of {topic}. The text should be at {level} level. "
            f"The word count should be approximately {word_count} words."
        )
        if tenses:
            prompt += f" The text should be written in the following tense(s): {', '.join(tenses)}."

        prompt += (
            f" Here are the vocabulary pairs: {selected_pairs}. "
            f"In the {source_lang_name} text, incorporate the source words exactly as given. "
            f"In the {target_lang_name} text, incorporate the provided translations exactly. "
            "Do not provide any alternative translations."
        )
        prompt += " Separate the source and target texts with '==='."

        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        generated_text = response.text

        text_parts = generated_text.split("===")
        if len(text_parts) < 2:
            return render(request, "error.html", {"message": "The generated text is not in the expected format."})

        source_text, target_text = text_parts[0].strip(), text_parts[1].strip()

        reading_lab_text = ReadingLabText(
            teacher=request.user,
            vocabulary_list=vocabulary_list,
            exam_board=exam_board,
            topic=topic,
            level=level,
            word_count=word_count,
            generated_text_source=source_text,
            generated_text_target=target_text,
        )
        reading_lab_text.save()
        reading_lab_text.selected_words.set(selected_words)

        request.user.deduct_credit()

        return redirect("reading_lab_display", reading_lab_text.id)

    exam_board_topics_json = json.dumps(EXAM_BOARD_TOPICS)
    vocabulary_lists = VocabularyList.objects.filter(teacher=request.user)
    return render(request, "learning/reading_lab.html", {
        "vocabulary_lists": vocabulary_lists,
        "exam_boards": list(EXAM_BOARD_TOPICS.keys()),
        "exam_board_topics_json": exam_board_topics_json
    })


# Helpers for activity generation
def remove_language_labels(text):
    pattern = re.compile(r"(?i)(English|German|French|Spanish|Italian):\s*")
    return pattern.sub("", text)


def remove_double_asterisks(text):
    return text.replace("**", "")


def generate_cloze(text, num_words_to_remove=10):
    words = text.split()
    if len(words) < num_words_to_remove:
        num_words_to_remove = max(1, len(words) // 2)
    indices = random.sample(range(len(words)), num_words_to_remove)
    indices.sort()
    cloze_words = words.copy()
    for i in indices:
        cloze_words[i] = "_____"
    cloze_text = " ".join(cloze_words)
    answer_key = [words[i] for i in indices]
    result = "Cloze Activity:\n\n" + cloze_text + "\n\nAnswer Key:\n" + ", ".join(answer_key)
    return result


def generate_reorder_activity(text, num_chunks=10):
    sentences = [s.strip() for s in text.split('.') if s.strip()]
    if len(sentences) >= num_chunks:
        chunks = sentences[:num_chunks]
    else:
        words = text.split()
        chunk_size = math.ceil(len(words) / num_chunks)
        chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

    original_order = list(range(1, len(chunks) + 1))
    scrambled = list(zip(original_order, chunks))
    random.shuffle(scrambled)

    scrambled_text = "\n".join([f"{i}. {chunk}" for i, chunk in scrambled])
    correct_order = "\n".join([f"{i}. {chunk}" for i, chunk in sorted(scrambled, key=lambda x: x[0])])

    return (
        "Reorder Activity:\n\n"
        "Scrambled Chunks:\n" + scrambled_text +
        "\n\nCorrect Order (for teacher reference):\n" + correct_order
    )


@login_required
def reading_lab_display(request, text_id):
    reading_lab_text = get_object_or_404(ReadingLabText, id=text_id, teacher=request.user)

    cloze_source = None
    cloze_target = None
    reorder_target = None
    tangled_translation = None
    comprehension_questions = None
    coins_left = request.user.ai_credits

    if request.method == "POST":
        if request.user.ai_credits < 1:
            return render(request, "error.html", {"message": "You do not have enough Pavonicoins to generate activities."})

        cloze_source_tmp = generate_cloze(reading_lab_text.generated_text_source, 10)
        cloze_source = remove_double_asterisks(remove_language_labels(cloze_source_tmp))

        cloze_target_tmp = generate_cloze(reading_lab_text.generated_text_target, 10)
        cloze_target = remove_double_asterisks(remove_language_labels(cloze_target_tmp))

        reorder_target_tmp = generate_reorder_activity(reading_lab_text.generated_text_target, 10)
        reorder_target = remove_double_asterisks(remove_language_labels(reorder_target_tmp))

        tangled_prompt = (
            "Combine the source text and target text into one tangled paragraph, mixing them at the "
            "sentence or phrase level. This activity is based on the EPI activity Tangled Translation. "
            "About half of the text should be in the source language, and half in the target language. "
            "Keep the same meaning. After '===', show the correct separation: first the entire source text, "
            "then the entire target text. Do not label lines with any language names, and remove any '**' asterisks.\n\n"
            f"Source text:\n{reading_lab_text.generated_text_source}\n\n"
            f"Target text:\n{reading_lab_text.generated_text_target}"
        )
        model = genai.GenerativeModel('gemini-2.0-flash')
        tangled_response = model.generate_content(tangled_prompt)
        tangled_translation = remove_double_asterisks(remove_language_labels(tangled_response.text))

        comp_prompt = (
            "Based on the following parallel text, create 5-10 comprehension questions. "
            "For each question, provide it in the source language and then in the target language. "
            "Then create some vocabulary and grammar questions about the text, with answers. "
            "Do not label lines with any language name or add 'English:' or 'German:' etc.\n\n"
            f"Source text:\n{reading_lab_text.generated_text_source}\n\n"
            f"Target text:\n{reading_lab_text.generated_text_target}"
        )
        comp_response = model.generate_content(comp_prompt)
        comprehension_questions = remove_double_asterisks(remove_language_labels(comp_response.text))

        request.user.deduct_credit()
        coins_left = request.user.ai_credits

    return render(request, "learning/reading_lab_display.html", {
        "reading_lab_text": reading_lab_text,
        "coins_left": coins_left,
        "cloze_source": cloze_source,
        "cloze_target": cloze_target,
        "reorder_target": reorder_target,
        "tangled_translation": tangled_translation,
        "comprehension_questions": comprehension_questions,
    })


# ----------------------------
# Grammar Ladder
# ----------------------------

@login_required
def grammar_lab(request):
    ladders = GrammarLadder.objects.filter(teacher=request.user).annotate(rung_count=Count("items")).order_by("-created_at")
    coins_left = request.user.ai_credits

    if request.method == "POST":
        if not request.user.is_teacher or request.user.ai_credits < 1:
            messages.error(request, "You do not have enough Pavonicoins or you are not a teacher.")
            return redirect("grammar_lab")

        name = request.POST.get("ladder_name")
        prompt = request.POST.get("grammar_prompt")
        language = request.POST.get("language")

        if not name or not prompt or not language:
            messages.error(request, "Please complete all fields.")
            return redirect("grammar_lab")

        full_prompt = (
            f"You are a grammar teaching assistant. Your task is to generate as many short, realistic and varied phrases "
            f"or sentences in {language} as possible (up to 1000), that focus *only* on the grammar topic: \"{prompt}\".\n\n"
            f"⚠️ Each example must test understanding of this grammar point. Do not include errors related to other grammar topics "
            f"(e.g. noun gender, spelling, or articles).\n"
            f"✅ All correct sentences must be genuinely grammatically correct.\n"
            f"❌ All incorrect sentences must contain a single, realistic grammar mistake related only to the target grammar point.\n\n"
            f"✍️ Output format:\n"
            f"Each line must contain exactly one sentence or phrase, followed by =correct or =incorrect.\n"
            f"No explanations. No titles. No examples. No numbering.\n"
            f"Only output real {language} sentences. Do not include the word 'PHRASE'.\n\n"
            f"Bad:\nPHRASE=correct ❌\n"
            f"Good:\nIch habe gegessen=correct ✅\nIch hat gegessen=incorrect ✅\n"
        )

        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(full_prompt)
            raw_output = response.text.strip()
        except Exception as e:
            messages.error(request, f"AI generation failed: {e}")
            return redirect("grammar_lab")

        parsed_items = []
        for line in raw_output.splitlines():
            if "=" in line:
                parts = line.split("=")
                if len(parts) == 2:
                    phrase = parts[0].strip()
                    correctness = parts[1].strip().lower()
                    is_correct = correctness == "correct"
                    parsed_items.append((phrase, is_correct))

        total_items = len(parsed_items)
        if total_items < 100:
            messages.error(request, f"❌ AI returned too few results ({total_items}). Please try again or refine your prompt.")
            return redirect("grammar_lab")
        if total_items > 750:
            parsed_items = parsed_items[:750]

        correct_count = sum(1 for _, c in parsed_items if c)
        incorrect_count = sum(1 for _, c in parsed_items if not c)
        if abs(correct_count - incorrect_count) > total_items * 0.25:
            messages.error(request, "AI returned an unbalanced set of correct and incorrect phrases. Try again or adjust the prompt.")
            return redirect("grammar_lab")

        ladder = GrammarLadder.objects.create(teacher=request.user, name=name, prompt=prompt, language=language)

        for phrase, is_correct in parsed_items:
            LadderItem.objects.create(ladder=ladder, phrase=phrase, is_correct=is_correct)

        request.user.deduct_credit()
        messages.success(request, f"✅ Grammar Ladder created with {total_items} phrases!")
        return redirect("grammar_lab")

    return render(request, "learning/grammar_lab.html", {"ladders": ladders, "coins_left": coins_left})


@require_POST
@login_required
def delete_ladder(request, ladder_id):
    ladder = get_object_or_404(GrammarLadder, id=ladder_id, teacher=request.user)
    ladder.delete()
    return redirect("grammar_lab")


from django.forms import modelformset_factory

@login_required
def grammar_ladder_detail(request, ladder_id):
    ladder = get_object_or_404(GrammarLadder, id=ladder_id, teacher=request.user)

    LadderItemFormSet = modelformset_factory(
        LadderItem, fields=("phrase", "is_correct"), extra=0, can_delete=True
    )

    if request.method == "POST":
        formset = LadderItemFormSet(request.POST, queryset=ladder.items.all())
        if formset.is_valid():
            formset.save()
            messages.success(request, "Ladder items updated.")
            return redirect("grammar_ladder_detail", ladder_id=ladder_id)
    else:
        formset = LadderItemFormSet(queryset=ladder.items.all())

    return render(request, "learning/grammar_ladder_detail.html", {
        "ladder": ladder,
        "formset": formset,
    })

@require_POST
@login_required
def delete_reading_lab_text(request, text_id):
    """
    Delete a ReadingLabText (teacher-only).
    Expects a POST to /reading-lab/<text_id>/delete/ or similar route.
    Returns JSON {"success": True} on success.
    """
    text = get_object_or_404(ReadingLabText, id=text_id, teacher=request.user)
    text.delete()
    return JsonResponse({"success": True})

@login_required
@user_passes_test(lambda u: u.is_teacher)
def worksheet_lab_view(request):
    vocab_list_id = request.GET.get('vocab_list')
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    # Fetch words related to the selected vocabulary list
    words_queryset = vocab_list.words.all()
    words = [{'word': word.word, 'translation': word.translation} for word in words_queryset]

    # Serialize the words to JSON
    words_json = json.dumps(words)

    # Get the user's premium status (safe even if field doesn’t exist)
    is_premium = getattr(request.user, "is_premium", False)

    return render(request, 'learning/worksheet_lab.html', {
        'vocab_list': vocab_list,
        'words_json': words_json,
        'is_premium': is_premium,
    })

def custom_404_view(request, exception=None):
    """Project-wide 404 handler."""
    return render(request, "404.html", status=404)

def progress_dashboard(request):
    """Aggregate and display overall progress for a logged-in student."""
    student_id = request.session.get("student_id")
    if not student_id:
        return redirect("student_login")

    student = get_object_or_404(Student, id=student_id)
    trophies = student.trophies.select_related("trophy")

    context = {
        "student": student,
        "total_points": student.total_points,
        "monthly_points": student.monthly_points,
        "weekly_points": student.weekly_points,
        "current_streak": student.current_streak,
        "highest_streak": student.highest_streak,
        "trophies": trophies,
        "trophy_count": trophies.count(),
        "total_pct": min(student.total_points, 100),
        "monthly_pct": min(student.monthly_points, 100),
        "weekly_pct": min(student.weekly_points, 100),
    }
    return render(request, "learning/progress_dashboard.html", context)

@login_required
@user_passes_test(lambda u: u.is_teacher)
def attach_vocab_list(request, class_id=None, vocab_list_id=None):
    """Attach a vocabulary list to a class for the logged-in teacher."""

    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    # Accept identifiers from either the URL kwargs or the submitted form.
    class_id = class_id or request.POST.get("class_id") or request.POST.get("class")
    vocab_list_id = (
        vocab_list_id
        or request.POST.get("vocab_list_id")
        or request.POST.get("vocab_list")
    )

    if not class_id or not vocab_list_id:
        messages.error(request, "Please select both a class and a vocabulary list.")
        return redirect("teacher_dashboard")

    # Ensure the logged-in teacher owns both resources involved in the attachment.
    class_instance = get_object_or_404(Class, id=class_id, teachers=request.user)
    vocab_list = get_object_or_404(
        VocabularyList, id=vocab_list_id, teacher=request.user
    )

    class_instance.vocabulary_lists.add(vocab_list)
    vocab_list.classes.add(class_instance)

    messages.success(
        request,
        f"'{vocab_list.name}' has been successfully attached to '{class_instance.name}'."
    )
    return redirect("teacher_dashboard")

@login_required
def view_vocabulary(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    return render(request, 'learning/view_vocabulary.html', {'vocab_list': vocab_list})

@login_required
@user_passes_test(lambda u: u.is_teacher)
def view_attached_vocab(request, class_id):
    # Get the class instance and ensure the logged-in teacher has access
    class_instance = get_object_or_404(Class, id=class_id)
    if request.user not in class_instance.teachers.all():
        return HttpResponseForbidden("You do not have permission to manage this class.")

    if request.method == "POST":
        vocab_list_id = request.POST.get("vocab_list_id")
        if vocab_list_id:
            vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
            class_instance.vocabulary_lists.remove(vocab_list)
            vocab_list.classes.remove(class_instance)
            messages.success(
                request,
                f"Vocabulary list '{vocab_list.name}' has been disassociated from class '{class_instance.name}'."
            )
        else:
            messages.error(request, "No vocabulary list selected.")
        return redirect("view_attached_vocab", class_id=class_id)

    attached_vocab_lists = class_instance.vocabulary_lists.all()
    # Optional debug
    # print(f"DEBUG: Class {class_instance.id} has {attached_vocab_lists.count()} vocabulary list(s) attached.")

    return render(request, "learning/view_attached_vocab.html", {
        "class_instance": class_instance,
        "attached_vocab_lists": attached_vocab_lists,
    })

@csrf_exempt
def update_points(request):
    """
    Add points to the currently logged-in student (session-based) and award any trophies.
    Body: {"points": <int>}
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method"})

    try:
        data = json.loads(request.body)
        student_id = request.session.get("student_id")
        points = data.get("points", 0)

        if student_id is not None and points is not None:
            student = get_object_or_404(Student, id=student_id)
            student.add_points(points)

            new_trophies = check_and_award_trophies(student)

            return JsonResponse({
                "success": True,
                "weekly_points": student.weekly_points,
                "total_points": student.total_points,
                "new_trophies": new_trophies,
            })
        else:
            return JsonResponse({"success": False, "error": "Invalid student ID or points"})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

@require_POST
def update_mini_game_1_best_streak(request):
    """Persist a student's best streak for the Peacock Feeding Frenzy mini-game."""
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON payload"}, status=400)

    student_id = request.session.get("student_id")
    if not student_id:
        return JsonResponse({"success": False, "error": "Student not authenticated"}, status=403)

    best_streak = payload.get("best_streak")
    if best_streak is None:
        return JsonResponse({"success": False, "error": "Missing best streak"}, status=400)

    try:
        best_streak_value = int(best_streak)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Best streak must be an integer"}, status=400)

    if best_streak_value < 0:
        return JsonResponse({"success": False, "error": "Best streak cannot be negative"}, status=400)

    student = get_object_or_404(Student, id=student_id)

    if best_streak_value > student.mini_game_1_best_streak:
        student.mini_game_1_best_streak = best_streak_value
        student.save(update_fields=["mini_game_1_best_streak"])

    return JsonResponse({
        "success": True,
        "best_streak": student.mini_game_1_best_streak,
    })


@student_login_required
def mini_game_1(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=30)
    words = [
        {"id": w.id, "word": w.word, "translation": w.translation}
        for w in words_objs
    ]

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(
        request,
        "learning/mini_game_1.html",
        {
            "vocab_list": vocab_list,
            "words_json": json.dumps(words, cls=DjangoJSONEncoder),
            "student": student,
        },
    )


@student_login_required
def destroy_the_wall(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    # Ensure the student has access to this vocabulary list
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=30)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]

    # AJAX feed for the game
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    # Page render
    return render(request, "learning/destroy_the_wall.html", {
        "vocab_list": vocab_list,
        "words_json": json.dumps(words),
        "student": student,
    })

@student_login_required
def unscramble_the_word(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    # optional: ensure access
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]

    # AJAX feed
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    # Page render
    return render(request, "learning/unscramble_the_word.html", {
        "vocab_list": vocab_list,
        "words_json": json.dumps(words, cls=DjangoJSONEncoder),
        "student": student,
    })

@student_login_required
def listening_dictation_assignment(request, assignment_id):
    """
    Assignment mode for Listening Dictation. Fetches words from the assignment's vocabulary list.
    """
    assignment = get_object_or_404(Assignment, id=assignment_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    vocab_list = assignment.vocab_list

    # Ensure student has access to this vocabulary list
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/assignment_modes/listening_dictation_assignment.html", {
        "assignment": assignment,
        "vocab_list": vocab_list,
        "words_json": json.dumps(words),
        "target_language": vocab_list.target_language,
        "points": assignment.points_per_listening_dictation,
    })


@student_login_required
def listening_translation_assignment(request, assignment_id):
    """
    Assignment mode for Listening Translation. Fetches words from the assignment's vocabulary list.
    """
    assignment = get_object_or_404(Assignment, id=assignment_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    vocab_list = assignment.vocab_list

    # Ensure student has access to this vocabulary list
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/assignment_modes/listening_translation_assignment.html", {
        "assignment": assignment,
        "vocab_list": vocab_list,
        "words_json": json.dumps(words),
        "target_language": vocab_list.target_language,
        "student": student,
        "weekly_points": student.weekly_points,
        "total_points": student.total_points,
        "points": assignment.points_per_listening_translation,
    })

@student_login_required
def listening_dictation_view(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    # optional access check (keeps behavior consistent with other views)
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, 'learning/listening_dictation.html', {
        'vocab_list': vocab_list,
        'words_json': json.dumps(words),
        'target_language': vocab_list.target_language,
        'student': student,
        'weekly_points': student.weekly_points,
        'total_points': student.total_points,
    })


@student_login_required
def listening_translation_view(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, 'learning/listening_translation.html', {
        'vocab_list': vocab_list,
        'words_json': json.dumps(words),
        'target_language': vocab_list.target_language,
        'student': student,
        'weekly_points': student.weekly_points,
        'total_points': student.total_points,
    })
