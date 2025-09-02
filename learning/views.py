from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, get_user_model
from django.db.models import Sum
from .models import Progress, VocabularyWord, VocabularyList, User, Class, Student, School, Assignment, AssignmentProgress, Trophy, StudentTrophy, ReadingLabText, AssignmentAttempt, GrammarLadder, LadderItem
from .forms import VocabularyListForm, CustomUserCreationForm, BulkAddWordsForm, ClassForm, ShareClassForm, TeacherRegistrationForm
from django.contrib import messages
from django.http import HttpResponseRedirect
from .utils import generate_student_username, generate_random_password
import datetime
from datetime import datetime
import random
from django.utils import timezone
from django.db.models import Q
from django.urls import reverse
from functools import wraps
from django.http import HttpResponseForbidden, Http404, HttpResponseBadRequest
import re
from django.views.decorators.http import require_POST

import json
from .decorators import student_login_required
from django.utils.timezone import now
from random import sample
from random import shuffle
from django.views.decorators.csrf import csrf_exempt
from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
import stripe
from django.conf import settings
from django.views import View
import requests
from .models import Announcement
from django.core.paginator import Paginator
import google.generativeai as genai
import math
import re
from .spaced_repetition import get_due_words, schedule_review, _get_user_from_student
from collections import defaultdict

# Configure Gemini API
genai.configure(api_key="AIzaSyAhBjjphW7nVHETfDtewuy_qiFXspa1yO4")


User = get_user_model()

def landing_page(request):
    """Landing page for users to choose login options."""
    return render(request, 'learning/landing_page.html')

def teacher_logout(request):
    # Clear all session data
    request.session.flush()
    # Optionally, call Django's logout to clear the auth user (if used)
    logout(request)
    return HttpResponseRedirect('/')


@login_required
def teacher_dashboard(request):
    if not request.user.is_teacher:
        return redirect("login")

    # Fetch the teacher's generated texts
    reading_lab_texts = ReadingLabText.objects.filter(teacher=request.user).order_by('-created_at')

    # Fetch data for vocabulary lists, classes, and students
    vocab_lists = VocabularyList.objects.filter(teacher=request.user)
    classes = Class.objects.filter(teachers=request.user)
    students = Student.objects.filter(classes__in=classes).distinct()

    # Annotate each class with live and expired assignments
    for class_instance in classes:
        class_instance.live_assignments = Assignment.objects.filter(
            class_assigned=class_instance, deadline__gte=datetime.now()
        )
        class_instance.expired_assignments = Assignment.objects.filter(
            class_assigned=class_instance, deadline__lt=datetime.now()
        )

    # Debugging output (optional)
    print("Classes:", classes)
    print("Students QuerySet:", students)
    for student in students:
        print(f"Student: {student.first_name} {student.last_name}, Classes: {student.classes.all()}")

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

    # Leaderboard by Class: For each class, paginate its student list (10 per page)
    by_class_leaderboards = []
    for class_instance in classes:
        students_in_class = class_instance.students.order_by('-total_points')
        # Use a unique query parameter for each class based on its id
        page_number = request.GET.get(f'class_{class_instance.id}_page', 1)
        paginator = Paginator(students_in_class, 10)
        leaderboard_page = paginator.get_page(page_number)
        by_class_leaderboards.append({
            'class_instance': class_instance,
            'leaderboard_page': leaderboard_page,
        })

    return render(request, "learning/teacher_dashboard.html", {
        "user": request.user,
        "vocab_lists": vocab_lists,
        "classes": classes,
        "students": students,
        "announcements": announcements,
        "reading_lab_texts": reading_lab_texts,
        "overall_leaderboard_page": overall_leaderboard_page,
        "by_class_leaderboards": by_class_leaderboards,
    })




@login_required
def add_vocabulary_list(request):
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
def edit_vocabulary_list_details(request, list_id):
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
def add_words_to_list(request, list_id):
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    if request.method == 'POST':
        form = BulkAddWordsForm(request.POST)
        if form.is_valid():
            words_input = form.cleaned_data['words']
            words_pairs = [line.split(',') for line in words_input.splitlines() if ',' in line]
            for word, translation in words_pairs:
                VocabularyWord.objects.create(
                    list=vocab_list,
                    word=word.strip(),
                    translation=translation.strip()
                )
            messages.success(request, "Words added successfully!")
            return redirect('teacher_dashboard')
    else:
        form = BulkAddWordsForm()
    return render(request, 'learning/add_words_to_list.html', {'form': form, 'vocab_list': vocab_list})

@login_required
def edit_vocabulary_words(request, list_id):
    """Allows teachers to edit or delete words in a vocabulary list."""
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    words = vocab_list.words.all()

    if request.method == 'POST':
        action = request.POST.get("action")
        
        if action == "save":
            # Save updated words
            for word in words:
                word_id = f"word_{word.id}"
                translation_id = f"translation_{word.id}"

                new_word = request.POST.get(word_id)
                new_translation = request.POST.get(translation_id)

                if new_word and new_translation:
                    word.word = new_word.strip()
                    word.translation = new_translation.strip()
                    word.save()

            messages.success(request, "Words updated successfully!")
            return redirect('edit_vocabulary_words', list_id=list_id)

        elif action == "bulk_delete":
            # Bulk delete selected words
            selected_word_ids = request.POST.getlist("selected_words")
            VocabularyWord.objects.filter(id__in=selected_word_ids).delete()
            messages.success(request, "Selected words deleted successfully!")
            return redirect('edit_vocabulary_words', list_id=list_id)

    return render(request, 'learning/edit_vocabulary_words.html', {
        'vocab_list': vocab_list,
        'words': words,
    })


@login_required
def view_vocabulary_words(request, list_id):
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    words = vocab_list.words.all()
    return render(request, 'learning/view_vocabulary_words.html', {'vocab_list': vocab_list, 'words': words})

@login_required
def delete_vocabulary_word(request, word_id):
    word = get_object_or_404(VocabularyWord, id=word_id)
    if request.method == 'POST':
        word.delete()
        messages.success(request, "Word deleted successfully!")
        return redirect('edit_vocabulary_words', list_id=word.list.id)
    return render(request, 'learning/delete_vocabulary_word.html', {'word': word})

@login_required
def bulk_delete_words(request, list_id):
    vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)
    if request.method == 'POST':
        word_ids = request.POST.getlist('selected_words')
        VocabularyWord.objects.filter(id__in=word_ids).delete()
        messages.success(request, "Selected words deleted successfully!")
        return redirect('edit_vocabulary_words', list_id=list_id)
    return render(request, 'learning/bulk_delete_words.html', {'vocab_list': vocab_list, 'words': vocab_list.words.all()})

@login_required
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

@login_required
def create_class(request):
    """
    Allows teachers to create a new class.
    """
    if request.method == "POST":
        form = ClassForm(request.POST, request.FILES)
        if form.is_valid():
            class_instance = form.save(commit=False)

            # Ensure the logged-in user has a school and assign it to the class
            if hasattr(request.user, 'school') and request.user.school:
                class_instance.school = request.user.school
                print(f"Assigned school: {class_instance.school}")
            else:
                print("Error: User does not have an associated school.")
                messages.error(request, "You must belong to a school to create a class.")
                return redirect("create_class")

            # Save the class instance
            try:
                class_instance.save()
                class_instance.teachers.add(request.user)  # Add the logged-in user as a teacher
                messages.success(request, "Class created successfully!")
                return redirect("teacher_dashboard")
            except Exception as e:
                print(f"Error saving class: {e}")
                messages.error(request, f"Error saving class: {e}")
        else:
            print("Form is not valid:", form.errors)
            messages.error(request, "Form submission is invalid. Please correct the errors below.")

    else:
        form = ClassForm()

    return render(request, "learning/create_class.html", {"form": form})





@login_required
def edit_class(request, class_id):
    """
    Allows editing of a class, showing all students with their details.
    """
    current_class = get_object_or_404(Class, id=class_id)
    students = current_class.students.all()

    if request.method == "POST":
        if "delete_selected" in request.POST:
            selected_students = request.POST.getlist("selected_students")
            Student.objects.filter(id__in=selected_students).delete()
            messages.success(request, "Selected students have been deleted.")
        else:
            # Handle other form submissions, if any
            pass

        return redirect("edit_class", class_id=class_id)

    for student in students:
        print(student.id)

    return render(
        request,
        "learning/edit_class.html",
        {
            "class_instance": current_class,
            "students": students,
        },
    )


@login_required
def add_students(request, class_id):
    """
    Adds students to a class from bulk input.
    """
    current_class = get_object_or_404(Class, id=class_id)

    # Print the class ID for debugging
    print(f"Class ID: {current_class.id}")

    if request.method == "POST":
        bulk_data = request.POST.get("bulk_data", "").strip()
        if not bulk_data:
            messages.error(request, "No student data provided.")
            return redirect("add_students", class_id=class_id)

        # Determine the school to assign:
        # Use the current class's school if it exists; otherwise, fallback to the teacher's school.
        school_to_assign = current_class.school if current_class.school else request.user.school

        for line in bulk_data.splitlines():
            try:
                # Expect each line to contain: first_name, last_name, year_group, dob
                first_name, last_name, year_group, dob = line.split(",")
                username = generate_student_username(first_name, last_name, dob)
                password = generate_random_password()

                student, created = Student.objects.get_or_create(
                    username=username,
                    defaults={
                        "first_name": first_name.strip(),
                        "last_name": last_name.strip(),
                        "year_group": int(year_group.strip()),
                        "date_of_birth": datetime.strptime(dob.strip(), "%d/%m/%Y").date(),
                        "password": password,
                        "school": school_to_assign,
                    },
                )
                current_class.students.add(student)
                if created:
                    messages.success(request, f"Student {first_name.strip()} added successfully.")
            except ValueError as e:
                messages.error(request, f"Error processing line '{line}': {e}")

        return redirect("teacher_dashboard")

    return render(request, "learning/add_students.html", {"class_instance": current_class})
def generate_student_username(first_name, last_name, dob):
    """
    Generates a username using first name, first two letters of the last name, and date of birth.
    """
    try:
        # Parse dob from string to datetime
        dob_obj = datetime.strptime(dob.strip(), "%d/%m/%Y").date()
        return f"{first_name.lower()}{last_name[:2].lower()}{dob_obj.day:02d}{dob_obj.month:02d}"
    except ValueError:
        raise ValueError(f"Invalid date format for DOB: {dob}. Expected format: dd/mm/yyyy")

def generate_random_password():
    return str(random.randint(1000, 9999))

@login_required
def edit_student(request, student_id):
    """
    Allows editing of a specific student's details.
    """
    student = get_object_or_404(Student, id=student_id)

    if request.method == "POST":
        student.first_name = request.POST.get("first_name", student.first_name)
        student.last_name = request.POST.get("last_name", student.last_name)
        student.year_group = request.POST.get("year_group", student.year_group)
        student.date_of_birth = request.POST.get("date_of_birth", student.date_of_birth)
        student.save()
        return redirect("edit_class", student.classes.first().id)

    return render(request, "learning/edit_student.html", {"student": student})


@login_required
def delete_student(request, student_id):
    """
    Deletes a student based on their UUID.
    """
    student = get_object_or_404(Student, id=student_id)
    associated_class = student.classes.first()
    if associated_class:
        class_id = associated_class.id
        student.delete()
        return redirect("edit_class", class_id)  # Redirect to the class page
    else:
        student.delete()
        return redirect("teacher_dashboard")  # Redirect to dashboard if no class is associated

def delete_class(request, class_id):
    class_obj = get_object_or_404(Class, id=class_id)

    # De-associate students from this class
    for student in class_obj.students.all():
        student.classes.remove(class_obj)

    # Delete the class
    class_obj.delete()

    # Redirect to the teacher dashboard
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
    """
    De-associates a teacher from a class using UUID, ensuring at least one teacher remains.
    """
    class_instance = get_object_or_404(Class, id=class_id)
    teacher = get_object_or_404(User, id=teacher_id)

    if class_instance.teachers.count() <= 1:
        messages.error(
            request,
            "Cannot remove the last teacher from the class. At least one teacher must remain associated."
        )
    elif teacher in class_instance.teachers.all():
        class_instance.teachers.remove(teacher)
        messages.success(request, f"{teacher.username} has been removed from the class.")
    else:
        messages.error(request, f"{teacher.username} is not associated with this class.")

    return redirect('share_class', class_id=class_id)

def student_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        next_url = request.GET.get("next", "")  # Fetch the next URL

        try:
            student = Student.objects.get(username=username)
            if student.password == password:  # Replace with secure password checks
                request.session['student_id'] = str(student.id)  # Set session
                student.last_login = now()
                student.save()
                # Redirect to next_url or dashboard if next_url is empty
                return redirect(next_url if next_url else 'student_dashboard')
            else:
                messages.error(request, "Invalid username or password.")
        except Student.DoesNotExist:
            messages.error(request, "Student not found.")

    return render(request, "learning/student_login.html")

from django.shortcuts import render, get_object_or_404, redirect
from django.utils.timezone import now
from django.db.models import Sum
from .models import Student, Class, Assignment, AssignmentProgress, VocabularyList

def student_dashboard(request):
    # Ensure the student is logged in
    student_id = request.session.get("student_id")
    if not student_id:
        return redirect("student_login")

    # Fetch the student and their classes
    student = get_object_or_404(Student, id=student_id)
    classes = student.classes.all()  # Get all classes the student is part of

    # Attach live and expired assignments with progress tracking
    for class_instance in classes:
        # Live assignments (deadline has not passed)
        live_assignments = Assignment.objects.filter(
            class_assigned=class_instance, deadline__gte=now()
        )

        # Expired assignments (deadline has passed)
        expired_assignments = Assignment.objects.filter(
            class_assigned=class_instance, deadline__lt=now()
        )

        # Process live assignments
        for assignment in live_assignments:
            progress = AssignmentProgress.objects.filter(student=student, assignment=assignment).first()
            assignment.student_progress = progress.points_earned if progress else 0
            assignment.target_points = assignment.target_points or 1
            assignment.progress_percentage = (assignment.student_progress / assignment.target_points) * 100
            assignment.is_complete = assignment.student_progress >= assignment.target_points

        # Process expired assignments
        for assignment in expired_assignments:
            progress = AssignmentProgress.objects.filter(student=student, assignment=assignment).first()
            assignment.student_progress = progress.points_earned if progress else 0
            assignment.target_points = assignment.target_points or 1
            assignment.progress_percentage = (assignment.student_progress / assignment.target_points) * 100
            assignment.is_complete = assignment.student_progress >= assignment.target_points

        # Assign processed assignments back to the class instance
        class_instance.live_assignments = live_assignments
        class_instance.expired_assignments = expired_assignments

    # Fetch vocabulary lists linked to the student's classes
    vocab_lists = VocabularyList.objects.filter(classes__in=classes).distinct()

    leaderboard_categories = [
        {"category": "total_points", "icon": "🔥", "title": "Total Points"},
        {"category": "monthly_points", "icon": "📅", "title": "Monthly Points"},
        {"category": "weekly_points", "icon": "📆", "title": "Weekly Points"},
    ]

    return render(request, "learning/student_dashboard.html", {
        "student": student,
        "classes": classes,
        "vocab_lists": vocab_lists,
        "leaderboard_categories": leaderboard_categories,
    })


def my_words(request):
    """Display all vocabulary words available to the logged-in student."""
    student_id = request.session.get("student_id")
    if not student_id:
        return redirect("student_login")

    student = get_object_or_404(Student, id=student_id)
    words = VocabularyWord.objects.filter(
        list__classes__in=student.classes.all()
    ).distinct()

    return render(request, "learning/my_words.html", {
        "student": student,
        "words": words,
    })



def student_logout(request):
    # Clear all session data
    request.session.flush()
    # Optionally, call Django's logout to clear the auth user (if used)
    logout(request)
    return HttpResponseRedirect('/')


@login_required
def attach_vocab_list(request, vocab_list_id):
    """Attach a vocabulary list to a class."""
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id, teacher=request.user)

    if request.method == "POST":
        class_id = request.POST.get("class_id")
        if class_id:
            class_instance = get_object_or_404(Class, id=class_id, teachers=request.user)
            vocab_list.classes.add(class_instance)  # Attach the vocabulary list to the class
            class_instance.vocabulary_lists.add(vocab_list)
            messages.success(request, f"'{vocab_list.name}' has been successfully attached to '{class_instance.name}'.")

    return redirect("teacher_dashboard")

@login_required
def view_class(request, class_id):
    class_instance = get_object_or_404(Class, id=class_id, students=request.user)
    vocab_lists = class_instance.vocabulary_lists.all()
    return render(request, "learning/view_class.html", {
        "class_instance": class_instance,
        "vocab_lists": vocab_lists,
    })

@login_required
def view_vocabulary(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    return render(request, 'learning/view_vocabulary.html', {'vocab_list': vocab_list})


@login_required
def view_attached_vocab(request, class_id):
    # Get the class instance by its id.
    class_instance = get_object_or_404(Class, id=class_id)
    
    if request.method == "POST":
        # Get the vocabulary list id from the form.
        vocab_list_id = request.POST.get("vocab_list_id")
        if vocab_list_id:
            # Retrieve the vocabulary list.
            vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
            # Remove the association from both sides.
            class_instance.vocabulary_lists.remove(vocab_list)
            vocab_list.classes.remove(class_instance)
            messages.success(request, f"Vocabulary list '{vocab_list.name}' has been disassociated from class '{class_instance.name}'.")
        else:
            messages.error(request, "No vocabulary list selected.")
        return redirect("view_attached_vocab", class_id=class_id)
    
    # Retrieve all vocabulary lists attached to this class.
    attached_vocab_lists = class_instance.vocabulary_lists.all()
    
    # Debug output:
    print(f"DEBUG: Class {class_instance.id} now has {attached_vocab_lists.count()} vocabulary list(s) attached.")

    return render(request, "learning/view_attached_vocab.html", {
        "class_instance": class_instance,
        "attached_vocab_lists": attached_vocab_lists,
    })


@student_login_required
def practice_session(request, vocab_list_id):
    """Rotate through practice activities using a session-based queue."""
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    # Ensure the student has access to this vocabulary list
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    queue_key = f"practice_queue_{vocab_list_id}"
    activity_key = f"practice_activity_{vocab_list_id}"

    queue = request.session.get(queue_key, [])
    if not queue:
        words = get_due_words(student, vocab_list, limit=20)
        queue = [w.id for w in words]
        request.session[queue_key] = queue

    activities = ["flashcard", "typing", "matchup"]
    idx = request.session.get(activity_key, 0)
    activity = activities[idx]
    request.session[activity_key] = (idx + 1) % len(activities)

    def _fetch_words(ids):
        word_objs = VocabularyWord.objects.filter(id__in=ids)
        return [{"id": w.id, "word": w.word, "translation": w.translation} for w in word_objs]

    if activity == "matchup":
        needed = 5
        if len(queue) < needed:
            more = get_due_words(student, vocab_list, limit=needed - len(queue))
            queue.extend([w.id for w in more])
            request.session[queue_key] = queue
        word_ids = queue[:needed]
        request.session[queue_key] = queue[needed:]
        words = _fetch_words(word_ids)
        source_words = words
        target_words = words[:]
        random.shuffle(target_words)
    else:
        if not queue:
            more = get_due_words(student, vocab_list, limit=20)
            queue.extend([w.id for w in more])
            request.session[queue_key] = queue
        word_id = queue.pop(0)
        request.session[queue_key] = queue
        words = _fetch_words([word_id])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        payload = {"activity": activity, "words": words}
        if activity == "matchup":
            payload.update({"source_words": source_words, "target_words": target_words})
        return JsonResponse(payload)

    template_map = {
        "flashcard": "learning/flashcard_mode.html",
        "typing": "learning/gap_fill_mode.html",
        "matchup": "learning/match_up_mode.html",
    }

    context = {"vocab_list": vocab_list, "student": student}
    if activity == "matchup":
        context.update({"source_words": source_words, "target_words": target_words})
    else:
        context["words"] = words
    return render(request, template_map[activity], context)
@student_login_required
def flashcard_mode(request, vocab_list_id):
    # Debugging session and user data
    print("Session student_id:", request.session.get('student_id'))

    try:
        # Fetch the student instance from the session
        student = Student.objects.get(id=request.session.get('student_id'))
    except Student.DoesNotExist:
        return redirect("student_login")

    # Fetch the vocabulary list
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    # Ensure the student has access to this vocabulary list
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
        # If assignment_id is provided, fetch the assignment and its vocab list
        assignment = get_object_or_404(Assignment, id=assignment_id)
        vocab_list = assignment.vocab_list
    elif vocab_list_id:
        # If vocab_list_id is provided, fetch the vocab list directly
        vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
        assignment = None  # No assignment in this case
    else:
        # If neither is provided, raise a 404
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
    # Fetch the vocabulary list
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    # Ensure the student has access to this vocabulary list
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/gap_fill_mode.html", {
        "vocab_list": vocab_list,
        "words": words,
    })


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
    if request.method == "POST":
        form = TeacherRegistrationForm(request.POST)

        # Check if form is valid
        if form.is_valid():
            user = form.save(commit=False)  # Save user instance without committing
            
            # Assign default school if none is provided
            user.school, _ = School.objects.get_or_create(name="Default School")

            user.save()  # Save user with assigned school

            # ✅ Add 1 free Pavonicoin for testing
            user.add_credits(1)  

            login(request, user)  # Auto-login new teacher
            
            messages.success(request, "Your account has been created successfully! You have received 1 free Pavonicoin to test the Reading Lab.")
            return redirect("teacher_dashboard")

        else:
            messages.error(request, "There were errors in the form. Please correct them.")
            print(form.errors)  # 🔴 Debugging: Print form errors to the terminal

    else:
        form = TeacherRegistrationForm()

    return render(request, "learning/register_teacher.html", {
        "form": form
    })





def lead_teacher_login(request):
    # Placeholder for Lead Teacher Login
    return render(request, "learning/lead_teacher_login.html")

def teacher_upgrade(request):
    """ Redirect to the upgrade tab inside the dashboard """
    return redirect('/teacher-dashboard/#teacher-upgrade')


def school_signup(request):
    # Placeholder for School Signup (Eventually a payment page)
    return render(request, "learning/school_signup.html")

def class_leaderboard(request, class_id):
    class_instance = get_object_or_404(Class, id=class_id)
    students = class_instance.students.all()

    leaderboard_data = {
        "total": students.order_by('-total_points')[:10],
        "weekly": students.order_by('-weekly_points')[:10],
        "monthly": students.order_by('-monthly_points')[:10],
    }

    return render(request, "learning/class_leaderboard.html", {
        "class_instance": class_instance,
        "leaderboard_data": leaderboard_data,
    })

@csrf_exempt
def update_points(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method"})

    try:
        data = json.loads(request.body)
        student_id = request.session.get("student_id")
        points = data.get("points", 0)

        if student_id is not None and points is not None:
            student = Student.objects.get(id=student_id)
            student.total_points += points
            student.weekly_points += points
            student.monthly_points += points
            student.save()

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

@student_login_required
def destroy_the_wall(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    # Ensure the student has access to this vocabulary list
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    words_objs = get_due_words(student, vocab_list, limit=30)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, "learning/destroy_the_wall.html", {
        "vocab_list": vocab_list,
        "words_json": json.dumps(words),
        "student": student,
    })


@student_login_required
def unscramble_the_word(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))
    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})
    return render(request, "learning/unscramble_the_word.html", {
        "vocab_list": vocab_list,
        "words_json": json.dumps(words, cls=DjangoJSONEncoder),
        "student": student,
    })


@login_required
def create_assignment(request, class_id):
    class_assigned = get_object_or_404(Class, id=class_id)
    # Use the ManyToMany relationship to get only vocab lists linked to this class.
    vocab_lists = class_assigned.vocabulary_lists.all()

    if request.method == "POST":
        name = request.POST.get("name")
        vocab_list_id = request.POST.get("vocab_list")  # Only defined in POST
        deadline = request.POST.get("deadline")
        target_points = int(request.POST.get("target_points"))

        include_flashcards = "include_flashcards" in request.POST
        points_per_flashcard = int(request.POST.get("points_per_flashcard", 1)) if include_flashcards else 0

        include_matchup = "include_matchup" in request.POST
        points_per_matchup = int(request.POST.get("points_per_matchup", 1)) if include_matchup else 0

        include_fill_gap = "include_fill_gap" in request.POST
        points_per_fill_gap = int(request.POST.get("points_per_fill_gap", 1)) if include_fill_gap else 0

        include_destroy_wall = "include_destroy_wall" in request.POST
        points_per_destroy_wall = int(request.POST.get("points_per_destroy_wall", 1)) if include_destroy_wall else 0

        include_unscramble = "include_unscramble" in request.POST
        points_per_unscramble = int(request.POST.get("points_per_unscramble", 1)) if include_unscramble else 0

        include_listening_dictation = "include_listening_dictation" in request.POST
        points_per_listening_dictation = int(request.POST.get("points_per_listening_dictation", 1)) if include_listening_dictation else 0

        include_listening_translation = "include_listening_translation" in request.POST
        points_per_listening_translation = int(request.POST.get("points_per_listening_translation", 1)) if include_listening_translation else 0

        # Ensure the vocabulary list is linked to this class
        vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id, linked_classes=class_assigned)

        Assignment.objects.create(
            name=name,
            class_assigned=class_assigned,
            vocab_list=vocab_list,
            deadline=deadline,
            target_points=target_points,
            include_flashcards=include_flashcards,
            points_per_flashcard=points_per_flashcard,
            include_matchup=include_matchup,
            points_per_matchup=points_per_matchup,
            include_fill_gap=include_fill_gap,
            points_per_fill_gap=points_per_fill_gap,
            include_destroy_wall=include_destroy_wall,
            points_per_destroy_wall=points_per_destroy_wall,
            include_unscramble=include_unscramble,
            points_per_unscramble=points_per_unscramble,
            include_listening_dictation=include_listening_dictation,
            points_per_listening_dictation=points_per_listening_dictation,
            include_listening_translation=include_listening_translation,
            points_per_listening_translation=points_per_listening_translation,
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

            # Update Assignment Progress
            assignment_progress, created = AssignmentProgress.objects.get_or_create(
                student=student, assignment=assignment
            )
            assignment_progress.points_earned += points
            assignment_progress.save()

            # Update Student's Total Points
            student.total_points += points
            student.save()

            # Award any trophies the student qualifies for
            new_trophies = check_and_award_trophies(student)

            return JsonResponse({
                "success": True,
                "new_total_points": student.total_points,
                "current_assignment_points": assignment_progress.points_earned,
                "new_trophies": new_trophies  # ✅ Include this so the frontend knows about new trophies
            })

        except Exception as e:
            return JsonResponse({
                "success": False,
                "error": str(e),
                "new_trophies": []  # ✅ Ensure we always return a list, even in case of an error
            })
    
    return JsonResponse({
        "success": False,
        "error": "Invalid request method",
        "new_trophies": []  # ✅ Prevents reference errors
    })



@login_required
def delete_assignment(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    if request.user != assignment.teacher:
        messages.error(request, "You are not authorized to delete this assignment.")
        return redirect("teacher_dashboard")

    assignment.delete()
    messages.success(request, "Assignment deleted successfully.")
    return redirect("teacher_dashboard")

@student_login_required
def assignment_page(request, assignment_id):
    student_id = request.session.get("student_id")
    if not student_id:
        return redirect("student_login")

    # Fetch the student and assignment
    student = get_object_or_404(Student, id=student_id)
    assignment = get_object_or_404(Assignment, id=assignment_id)

    # Check if the assignment is assigned to the student's class
    if not assignment.class_assigned.students.filter(id=student.id).exists():
        # If the assignment is not assigned to the student, redirect or show an error
        return render(request, "learning/access_denied.html", status=403)

    # Calculate assignment progress
    total_points = assignment.target_points
    current_points = AssignmentProgress.objects.filter(
        assignment=assignment, student=student
    ).aggregate(total=Sum('points_earned')).get('total', 0) or 0

    # Map modes to their respective URLs
    mode_url_map = {
        "flashcards": "flashcard_mode_assignment",
        "matchup": "match_up_mode_assignment",
        "fill the gap": "gap_fill_mode_assignment",
        "destroy the wall": "destroy_wall_mode_assignment",
        "unscramble": "unscramble_the_word_assignment",
    }

    # Determine which modes are included
    modes = []
    if assignment.include_flashcards:
        modes.append(("flashcards", reverse("flashcard_mode_assignment", kwargs={"assignment_id": assignment.id})))
    if assignment.include_matchup:
        modes.append(("match up", reverse("match_up_mode_assignment", kwargs={"assignment_id": assignment.id})))
    if assignment.include_fill_gap:
        modes.append(("fill the gap", reverse("gap_fill_mode_assignment", kwargs={"assignment_id": assignment.id})))
    if assignment.include_destroy_wall:
        modes.append(("destroy the wall", reverse("destroy_wall_mode_assignment", kwargs={"assignment_id": assignment.id})))
    if assignment.include_unscramble:
        modes.append(("unscramble", reverse("unscramble_the_word_assignment", kwargs={"assignment_id": assignment.id})))

    # Pass all required data to the template
    return render(request, "learning/assignment_page.html", {
        "assignment": assignment,
        "modes": modes,
        "student": student,
        "total_points": total_points,
        "current_points": current_points,
    })

def access_denied(request):
    """
    Renders the access denied page when a student tries to access an unauthorized assignment.
    """
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

    # Fetch assignment progress for current points (if any)
    assignment_progress = AssignmentProgress.objects.filter(
        assignment=assignment, student=student
    ).first()
    current_points = assignment_progress.points_earned if assignment_progress else 0

    return render(request, "learning/assignment_modes/gap_fill_mode_assignment.html", {
        "assignment": assignment,
        "words_json": json.dumps(words_list),  # Pass JSON-encoded words (with id)
        "student": student,
        "total_points": assignment.target_points,
        "current_points": current_points,
        "source_language": vocab_list.source_language,
        "target_language": vocab_list.target_language,
        # Points awarded per correct gap-fill attempt.
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
        # If assignment_id is provided, fetch the assignment and its vocab list
        assignment = get_object_or_404(Assignment, id=assignment_id)
        vocab_list = assignment.vocab_list
    elif vocab_list_id:
        # If vocab_list_id is provided, fetch the vocab list directly
        vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
        assignment = None  # No assignment in this case
    else:
        # If neither is provided, raise a 404
        raise Http404("No assignment or vocab list specified.")

    student = get_object_or_404(Student, id=request.session.get('student_id'))

    # Fetch all words in the vocabulary list
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
        "assignment": assignment,  # Pass the assignment to the template
        # If an assignment is provided, pass its per-match points value explicitly.
        "points": assignment.points_per_matchup if assignment else 0,
    }

    return render(request, "learning/assignment_modes/match_up_mode_assignment.html", context)


def check_and_award_trophies(student):
    """Check if a student qualifies for new trophies and award them."""

    trophies = Trophy.objects.all()
    earned_trophies = set(StudentTrophy.objects.filter(student=student).values_list("trophy_id", flat=True))

    for trophy in trophies:
        if trophy.id in earned_trophies:  
            continue  # Skip if the student already has this trophy

        if trophy.points_required and student.total_points >= trophy.points_required:
            StudentTrophy.objects.create(student=student, trophy=trophy)

        elif trophy.streak_required:
            # Calculate streak based on last login
            recent_days = [
                student.last_login - timedelta(days=i) for i in range(trophy.streak_required)
            ]
            if all(day.date() in student.attendance_dates() for day in recent_days):
                StudentTrophy.objects.create(student=student, trophy=trophy)

        elif trophy.assignment_count_required and student.assignments_completed >= trophy.assignment_count_required:
            StudentTrophy.objects.create(student=student, trophy=trophy)

        elif trophy.game_type and student.games_played.filter(game_type=trophy.game_type).count() >= 50:
            StudentTrophy.objects.create(student=student, trophy=trophy)

    return

def check_and_award_trophies(student):
    new_trophies = []

    # Streak Awards
    streak_awards = {
        3: "Warm-Up",
        7: "On Fire!",
        30: "Unstoppable!",
        100: "Legendary Commitment!",
    }
    for days, trophy_name in streak_awards.items():
        if student.current_streak >= days:
            trophy, _ = Trophy.objects.get_or_create(name=trophy_name, defaults={"description": f"Awarded for a {days}-day streak!"})
            _, created = StudentTrophy.objects.get_or_create(student=student, trophy=trophy)
            if created:
                new_trophies.append(trophy_name)

    # Points Milestones
    points_awards = {
        500: "Rising Star",
        1000: "Language Warrior",
        5000: "Master Linguist",
        10000: "Polyglot Prodigy",
    }
    for points, trophy_name in points_awards.items():
        if student.total_points >= points:
            trophy, _ = Trophy.objects.get_or_create(name=trophy_name, defaults={"description": f"Earned {points} points!"})
            _, created = StudentTrophy.objects.get_or_create(student=student, trophy=trophy)
            if created:
                new_trophies.append(trophy_name)

    # Assignment Mastery
    assignments_awards = {
        5: "Diligent Scholar",
        20: "Task Crusher",
        50: "Perfectionist",
    }
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

@student_login_required
def unscramble_the_word_assignment(request, assignment_id):
    # Get the assignment
    assignment = get_object_or_404(Assignment, id=assignment_id)

    # Ensure the student is logged in
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    # Fetch the associated vocabulary list
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
    print("Session student_id:", request.session.get('student_id'))

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


stripe.api_key = settings.STRIPE_SECRET_KEY  # Ensure this is set in settings.py

@csrf_exempt
def create_checkout_session(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request, POST required"}, status=400)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": "price_1QpQcMJYDgv8Jx3VdIdRmwsL",
                "quantity": 1,
            }],
            mode="subscription",
            success_url="https://www.pavonify.com/payment-success/",
            cancel_url="https://www.pavonify.com/teacher-dashboard/",
            client_reference_id=str(request.user.id),  # Pass teacher's ID here
            subscription_data={
                "metadata": {
                    "teacher_id": str(request.user.id)
                }
            },
        )
        return JsonResponse({"sessionId": session.id})

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
            # Retrieve stored metadata
            email = session.customer_email
            username = session.metadata.get("username")
            password = session.metadata.get("password")  # Get stored password

            if not email or not password:
                return redirect("register-fail")  # Prevent account creation if missing data

            # Create the teacher account with the given password
            user, created = User.objects.get_or_create(email=email, username=username)
            if created:
                user.set_password(password)  # Set actual password
                user.save()

                # Create Teacher Profile
                Teacher.objects.create(user=user, is_premium=True)

            return redirect("dashboard")  # Redirect to teacher dashboard
        else:
            return redirect("register-fail")
    except stripe.error.StripeError:
        return redirect("register-fail")


@login_required
def worksheet_lab_view(request):
    vocab_list_id = request.GET.get('vocab_list')
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

    # Fetch words related to the selected vocabulary list
    words_queryset = vocab_list.words.all()
    words = [{'word': word.word, 'translation': word.translation} for word in words_queryset]

    # Serialize the words to JSON
    words_json = json.dumps(words)

    # Get the user's premium status
    is_premium = request.user.is_premium if request.user.is_authenticated else False

    # Render the worksheet lab page with the selected vocabulary list, its words, and user status
    return render(request, 'learning/worksheet_lab.html', {
        'vocab_list': vocab_list,
        'words_json': words_json,
        'is_premium': is_premium,  # Pass the premium status to the template
    })


@student_login_required
def listening_dictation_view(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))


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

@student_login_required
def listening_dictation_assignment(request, assignment_id):
    """
    Assignment mode for Listening Dictation. Fetches words from the associated vocabulary list.
    """
    assignment = get_object_or_404(Assignment, id=assignment_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    # Fetch the associated vocabulary list
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
    # Get the assignment object
    assignment = get_object_or_404(Assignment, id=assignment_id)
    
    # Get the student
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    # Get the vocabulary list assigned to this assignment
    vocab_list = assignment.vocab_list

    words_objs = get_due_words(student, vocab_list, limit=20)
    words = [{"id": w.id, "word": w.word, "translation": w.translation} for w in words_objs]
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"words": words})

    return render(request, 'learning/assignment_modes/listening_translation_assignment.html', {
        'assignment': assignment,
        'vocab_list': vocab_list,
        'words_json': json.dumps(words),
        'target_language': vocab_list.target_language,
        'student': student,
        'weekly_points': student.weekly_points,
        'total_points': student.total_points,
        'points': assignment.points_per_listening_translation,
    })



def custom_404_view(request, exception):
    return render(request, '404.html', status=404)

@login_required
def teacher_account_settings(request):
    if request.method == "POST":
        request.user.first_name = request.POST.get("first_name", request.user.first_name)
        request.user.last_name = request.POST.get("last_name", request.user.last_name)
        request.user.email = request.POST.get("email", request.user.email)
        
        new_password = request.POST.get("password")
        if new_password:
            request.user.set_password(new_password)  # Securely update the password
        
        request.user.save()
        return redirect("teacher_dashboard")  # Redirect to prevent resubmission

    return render(request, "teacher_dashboard.html")

@login_required
def teacher_cancel_subscription(request):
    teacher = request.user
    if teacher.subscription_id:
        try:
            # Set the subscription to cancel at the end of the current period
            stripe.Subscription.modify(
                teacher.subscription_id,
                cancel_at_period_end=True
            )
            # Mark the subscription as canceled in the database.
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


# Hardcoded exam board topics
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


import json
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

# Example language code -> name map
LANGUAGE_MAP = {
    'en': 'English',
    'de': 'German',
    'fr': 'French',
    'sp': 'Spanish',
    'it': 'Italian',
}

import json
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

# Map language codes to full names
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
        # Ensure the user is a teacher and has AI credits
        if not request.user.is_teacher or request.user.ai_credits <= 0:
            return render(request, "error.html", {"message": "You do not have enough AI credits or are not a teacher."})

        # Get form data
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

        # Fetch selected vocabulary list and words
        vocabulary_list = VocabularyList.objects.get(id=vocabulary_list_id)
        selected_words = VocabularyWord.objects.filter(id__in=selected_word_ids)

        # Prepare language names from codes
        source_lang_code = vocabulary_list.source_language  # e.g., 'en'
        target_lang_code = vocabulary_list.target_language  # e.g., 'de'
        source_lang_name = LANGUAGE_MAP.get(source_lang_code, 'Unknown')
        target_lang_name = LANGUAGE_MAP.get(target_lang_code, 'Unknown')

        # Create a string of vocabulary pairs: "easy = einfach, happy = glücklich, ..."
        selected_pairs = ", ".join([f"{w.word} = {w.translation}" for w in selected_words])

        # Build the initial prompt
        prompt = (
            f"Generate a parallel text in {source_lang_name} and {target_lang_name} "
            f"on the topic of {topic}. The text should be at {level} level. "
            f"The word count should be approximately {word_count} words."
        )
        if tenses:
            prompt += f" The text should be written in the following tense(s): {', '.join(tenses)}."

        # Instruct the model to use the provided vocabulary pairs exactly.
        prompt += (
            f" Here are the vocabulary pairs: {selected_pairs}. "
            f"In the {source_lang_name} text, incorporate the source words exactly as given. "
            f"In the {target_lang_name} text, incorporate the provided translations exactly. "
            "Do not provide any alternative translations."
        )
        prompt += " Separate the source and target texts with '==='."

        # Call Gemini API using the appropriate model name
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        generated_text = response.text

        # Debug output
        print("Generated Text:", generated_text)

        # Split the generated text using the custom delimiter
        text_parts = generated_text.split("===")
        if len(text_parts) < 2:
            return render(request, "error.html", {"message": "The generated text is not in the expected format."})

        source_text, target_text = text_parts[0].strip(), text_parts[1].strip()

        # Save the generated texts to the database
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

        # Deduct 1 AI credit from the teacher
        request.user.deduct_credit()

        return redirect("reading_lab_display", reading_lab_text.id)

    # For GET requests, display the form
    exam_board_topics_json = json.dumps(EXAM_BOARD_TOPICS)
    vocabulary_lists = VocabularyList.objects.filter(teacher=request.user)
    return render(request, "learning/reading_lab.html", {
        "vocabulary_lists": vocabulary_lists,
        "exam_boards": list(EXAM_BOARD_TOPICS.keys()),
        "exam_board_topics_json": exam_board_topics_json
    })



@login_required
def reading_lab_display(request, text_id):
    # Fetch the generated text
    reading_lab_text = ReadingLabText.objects.get(id=text_id)
    return render(request, "learning/reading_lab_display.html", {
        "reading_lab_text": reading_lab_text,
    })


@student_login_required
def my_words(request):
    """Display a student's progress grouped by vocabulary list."""
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

    grouped = defaultdict(list)
    for prog in progress_qs:
        total_attempts = prog.correct_attempts + prog.incorrect_attempts
        memory_percent = int(prog.correct_attempts / total_attempts * 100) if total_attempts > 0 else 0
        if memory_percent >= 80:
            color = "high"
        elif memory_percent >= 50:
            color = "medium"
        else:
            color = "low"
        grouped[prog.word.list].append({
            "text": prog.word.word,
            "last_seen": prog.last_seen,
            "total_attempts": total_attempts,
            "memory_percent": memory_percent,
            "memory_color": color,
        })

    classes = student.classes.all()
    vocab_lists = VocabularyList.objects.filter(words__progress__student=user).distinct()

    context = {
        "grouped_progress": grouped.items(),
        "classes": classes,
        "vocab_lists": vocab_lists,
        "selected_class": class_id,
        "selected_list": list_id,
    }

    return render(request, "learning/my_words.html", context)

def get_words(request):
    """ AJAX endpoint to fetch words for a selected vocabulary list """
    vocabulary_list_id = request.GET.get("vocabulary_list_id")
    words = VocabularyWord.objects.filter(list_id=vocabulary_list_id).values("id", "word")
    return JsonResponse({"words": list(words)})

def delete_reading_lab_text(request, text_id):
    if request.method == "POST":
        text = get_object_or_404(ReadingLabText, id=text_id)
        text.delete()
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Invalid request"}, status=400)



# Helper: remove lines like "English:", "German:", etc.
def remove_language_labels(text):
    pattern = re.compile(r"(?i)(English|German|French|Spanish|Italian):\s*")
    return pattern.sub("", text)

# Helper: remove all "**"
def remove_double_asterisks(text):
    return text.replace("**", "")

# 1) Cloze (Gap-Fill) Helper
def generate_cloze(text, num_words_to_remove=10):
    words = text.split()
    # If the text is too short, adjust how many words to remove
    if len(words) < num_words_to_remove:
        num_words_to_remove = max(1, len(words) // 2)
    indices = random.sample(range(len(words)), num_words_to_remove)
    indices.sort()

    cloze_words = words.copy()
    for i in indices:
        cloze_words[i] = "_____"

    cloze_text = " ".join(cloze_words)
    answer_key = [words[i] for i in indices]

    result = (
        "Cloze Activity:\n\n"
        + cloze_text
        + "\n\nAnswer Key:\n"
        + ", ".join(answer_key)
    )
    return result

# 2) Reorder Paragraph Helper
def generate_reorder_activity(text, num_chunks=10):
    # Try splitting text into sentences first
    sentences = [s.strip() for s in text.split('.') if s.strip()]
    if len(sentences) >= num_chunks:
        chunks = sentences[:num_chunks]
    else:
        # If not enough sentences, split by words into roughly equal chunks
        words = text.split()
        chunk_size = math.ceil(len(words) / num_chunks)
        chunks = [
            " ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)
        ]

    original_order = list(range(1, len(chunks) + 1))
    scrambled = list(zip(original_order, chunks))
    random.shuffle(scrambled)

    scrambled_text = "\n".join([f"{i}. {chunk}" for i, chunk in scrambled])
    correct_order = "\n".join([
        f"{i}. {chunk}" for i, chunk in sorted(scrambled, key=lambda x: x[0])
    ])

    return (
        "Reorder Activity:\n\n"
        "Scrambled Chunks:\n"
        + scrambled_text
        + "\n\nCorrect Order (for teacher reference):\n"
        + correct_order
    )

@login_required
def reading_lab_display(request, text_id):
    reading_lab_text = get_object_or_404(ReadingLabText, id=text_id, teacher=request.user)

    # Activities
    cloze_source = None
    cloze_target = None
    reorder_target = None
    tangled_translation = None
    comprehension_questions = None

    # Teacher's coin count
    coins_left = request.user.ai_credits

    if request.method == "POST":
        # Check if user has at least 1 Pavonicoin
        if request.user.ai_credits < 1:
            return render(request, "error.html", {
                "message": "You do not have enough Pavonicoins to generate activities."
            })

        # 1) Cloze - source language
        cloze_source_tmp = generate_cloze(reading_lab_text.generated_text_source, 10)
        cloze_source_tmp = remove_language_labels(cloze_source_tmp)
        cloze_source_tmp = remove_double_asterisks(cloze_source_tmp)
        cloze_source = cloze_source_tmp

        # 2) Cloze - target language
        cloze_target_tmp = generate_cloze(reading_lab_text.generated_text_target, 10)
        cloze_target_tmp = remove_language_labels(cloze_target_tmp)
        cloze_target_tmp = remove_double_asterisks(cloze_target_tmp)
        cloze_target = cloze_target_tmp

        # 3) Reorder the target paragraph
        reorder_target_tmp = generate_reorder_activity(reading_lab_text.generated_text_target, 10)
        reorder_target_tmp = remove_language_labels(reorder_target_tmp)
        reorder_target_tmp = remove_double_asterisks(reorder_target_tmp)
        reorder_target = reorder_target_tmp

        # 4) Tangled Translation (AI-based)
        # Instruct the model to chunk each text in 5-10 words and alternate.
        tangled_prompt = (
            "Combine the source text and target text into one tangled paragraph, mixing them at the "
            "sentence or phrase level. This activity is based on the EPI activity Tangled Translation.  " 
            "About half of the text should be in the source language, "
            "and half in the target language. Keep the same meaning. After '===', show the "
            "correct separation: first the entire source text, then the entire target text. "
            "Do not label lines with any language names, and remove any '**' asterisks.\n\n"
            f"Source text:\n{reading_lab_text.generated_text_source}\n\n"
            f"Target text:\n{reading_lab_text.generated_text_target}"
        )
        model = genai.GenerativeModel('gemini-2.0-flash')
        tangled_response = model.generate_content(tangled_prompt)
        tangled_tmp = remove_language_labels(tangled_response.text)
        tangled_tmp = remove_double_asterisks(tangled_tmp)
        tangled_translation = tangled_tmp

        # 5) Comprehension & Grammar Questions (AI-based)
        # 5-10 Qs in both source & target languages, plus vocab/grammar
        comp_prompt = (
            "Based on the following parallel text, create 5-10 comprehension questions. "
            "For each question, provide it in the source language and then in the target language. "
            "Then create some vocabulary and grammar questions about the text, with answers. "
            "Do not label lines with any language name or add 'English:' or 'German:' etc.\n\n"
            f"Source text:\n{reading_lab_text.generated_text_source}\n\n"
            f"Target text:\n{reading_lab_text.generated_text_target}"
        )
        comp_response = model.generate_content(comp_prompt)
        comp_tmp = remove_language_labels(comp_response.text)
        comp_tmp = remove_double_asterisks(comp_tmp)
        comprehension_questions = comp_tmp

        # Deduct 1 Pavonicoin total
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

@login_required
def buy_pavicoins(request):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': 'price_1QyTOsJYDgv8Jx3V96D0iJoR',  # Your Stripe price ID
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.build_absolute_uri(reverse('pavicoins_success')),
            cancel_url=request.build_absolute_uri(reverse('teacher_dashboard')),
            metadata={'user_id': request.user.id},  # Store user info for later updates
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

@login_required
def class_leaderboard(request, class_id):
    # Fetch the class instance and verify that the logged-in teacher is assigned to it.
    class_instance = get_object_or_404(Class, id=class_id)
    if request.user not in class_instance.teachers.all():
        return HttpResponseForbidden("You do not have permission to view this class leaderboard.")
    
    # Get all students in the class, ordered by total_points descending.
    students = class_instance.students.all().order_by('-total_points')
    
    context = {
        "class_instance": class_instance,
        "students": students,
    }
    return render(request, "learning/class_leaderboard.html", context)

@login_required
def refresh_leaderboard(request, class_id):
    # This view returns only the leaderboard table fragment.
    class_instance = get_object_or_404(Class, id=class_id)
    if request.user not in class_instance.teachers.all():
        return HttpResponseForbidden("You do not have permission to view this class leaderboard.")
    
    students = class_instance.students.all().order_by('-total_points')
    
    return render(request, "learning/leaderboard_fragment.html", {
         "class_instance": class_instance,
         "students": students,
    })


@student_login_required
@csrf_exempt  # Ensure your AJAX requests include the CSRF token; remove if not needed
def log_assignment_attempt(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST requests are allowed.")
    
    try:
        data = json.loads(request.body)
        assignment_id = data.get("assignment_id")
        word_id = data.get("word_id")
        is_correct = data.get("is_correct")
        
        # Validate required fields
        if assignment_id is None or word_id is None or is_correct is None:
            return HttpResponseBadRequest("Missing required parameters.")
        
        assignment = get_object_or_404(Assignment, id=assignment_id)
        student = get_object_or_404(Student, id=request.session.get("student_id"))
        vocab_word = get_object_or_404(VocabularyWord, id=word_id)

        mode = data.get("mode")
        if not mode:
            return HttpResponseBadRequest("Missing mode parameter.")
        
        # Create the assignment attempt record.
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
    # Fetch the assignment
    assignment = get_object_or_404(Assignment, id=assignment_id)
    
    # Security: Check that the logged-in teacher is the owner of the assignment
    if request.user != assignment.teacher:
        return HttpResponseForbidden("You do not have permission to view this assignment's analytics.")
    # Also ensure the assignment's class is among the teacher's classes.
    if not assignment.class_assigned.teachers.filter(id=request.user.id).exists():
        return HttpResponseForbidden("You do not have permission to view this assignment's analytics.")
    
    # Overview: Get progress for each student for this assignment.
    progress_list = AssignmentProgress.objects.filter(assignment=assignment)
    
    # Get all attempts for this assignment, ordered by timestamp.
    attempts = list(
        AssignmentAttempt.objects.filter(assignment=assignment)
        .select_related("vocabulary_word")
        .order_by("timestamp")
    )
    
    # --- Student Summary Aggregation ---
    student_summary = {}
    for att in attempts:
        student_id = att.student.id
        word_id = att.vocabulary_word.id
        if student_id not in student_summary:
            student_summary[student_id] = {
                "student": att.student,
                "words": {}  # keyed by word_id with data: target word, wrong count, aced flag
            }
        if word_id not in student_summary[student_id]["words"]:
            # Use the target word (translation) here:
            student_summary[student_id]["words"][word_id] = {"word": att.vocabulary_word.translation, "wrong": 0, "aced": False}
        if not student_summary[student_id]["words"][word_id]["aced"]:
            if att.is_correct:
                student_summary[student_id]["words"][word_id]["aced"] = True
            else:
                student_summary[student_id]["words"][word_id]["wrong"] += 1

    student_summary_list = []
    for s in student_summary.values():
        words_aced = []
        attempts_wrong = []
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
    
    # --- Word Summary Aggregation ---
    word_summary_dict = {}
    for att in attempts:
        word_id = att.vocabulary_word.id
        if word_id not in word_summary_dict:
            # Use the target word (translation) instead of the source word
            word_summary_dict[word_id] = {"word": att.vocabulary_word.translation, "wrong_attempts": 0, "students": set()}
        if not att.is_correct:
            word_summary_dict[word_id]["wrong_attempts"] += 1
            word_summary_dict[word_id]["students"].add(att.student.id)
    word_summary_list = []
    for w in word_summary_dict.values():
        word_summary_list.append({
            "word": w["word"],
            "wrong_attempts": w["wrong_attempts"],
            "students_difficulty": len(w["students"]),
        })
    
    # --- Feedback Aggregation ---
    first_attempts = {}
    for att in attempts:
        key = (att.student.id, att.vocabulary_word.id)
        if key not in first_attempts:
            first_attempts[key] = att.is_correct

    easy_words = []
    difficult_words = []
    for key, is_correct in first_attempts.items():
        word_id = key[1]
        if word_id in word_summary_dict:
            # Again, use the target word
            word_text = word_summary_dict[word_id]["word"]
            if is_correct:
                easy_words.append(word_text)
            else:
                difficult_words.append(word_text)
    word_cloud_easy = list(set(easy_words))
    word_cloud_difficult = list(set(difficult_words))
    
    # Top 10 Difficult Words by distinct student count.
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


from django.db.models import Count

@login_required
def grammar_lab(request):
    # Annotate ladders with the number of LadderItems
    ladders = GrammarLadder.objects.filter(teacher=request.user).annotate(rung_count=Count("items")).order_by("-created_at")

    
    coins_left = request.user.ai_credits

    if request.method == "POST":
        # 1. Permissions & coins check
        if not request.user.is_teacher or request.user.ai_credits < 1:
            messages.error(request, "You do not have enough Pavonicoins or you are not a teacher.")
            return redirect("grammar_lab")

        # 2. Collect form data
        name = request.POST.get("ladder_name")
        prompt = request.POST.get("grammar_prompt")
        language = request.POST.get("language")

        if not name or not prompt or not language:
            messages.error(request, "Please complete all fields.")
            return redirect("grammar_lab")

        # 3. 🎯 Construct focused AI prompt
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

        # 4. 🔥 Call Gemini API
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(full_prompt)
            raw_output = response.text.strip()
        except Exception as e:
            messages.error(request, f"AI generation failed: {e}")
            return redirect("grammar_lab")

        # 5. Parse AI response
        parsed_items = []
        for line in raw_output.splitlines():
            if "=" in line:
                parts = line.split("=")
                if len(parts) == 2:
                    phrase = parts[0].strip()
                    correctness = parts[1].strip().lower()
                    is_correct = correctness == "correct"
                    parsed_items.append((phrase, is_correct))

        # 6. Validate and filter
        total_items = len(parsed_items)
        if total_items < 100:
            messages.error(request, f"❌ AI returned too few results ({total_items}). Please try again or refine your prompt.")
            return redirect("grammar_lab")
        if total_items > 750:
            parsed_items = parsed_items[:750]  # Cap at 750

        correct_count = sum(1 for _, c in parsed_items if c)
        incorrect_count = sum(1 for _, c in parsed_items if not c)
        if abs(correct_count - incorrect_count) > total_items * 0.25:  # max 25% imbalance
            messages.error(request, "AI returned an unbalanced set of correct and incorrect phrases. Try again or adjust the prompt.")
            return redirect("grammar_lab")

        # 7. Save Grammar Ladder
        ladder = GrammarLadder.objects.create(
            teacher=request.user,
            name=name,
            prompt=prompt,
            language=language
        )

        # 8. Save Ladder Items
        for phrase, is_correct in parsed_items:
            LadderItem.objects.create(
                ladder=ladder,
                phrase=phrase,
                is_correct=is_correct
            )

        # 9. Deduct Pavonicoin
        request.user.deduct_credit()

        # 10. Success message and redirect
        messages.success(request, f"✅ Grammar Ladder created with {total_items} phrases!")
        return redirect("grammar_lab")

    # GET request: render the page
    return render(request, "learning/grammar_lab.html", {
        "ladders": ladders,
        "coins_left": coins_left
    })


@require_POST
@login_required
def delete_ladder(request, ladder_id):
    ladder = get_object_or_404(GrammarLadder, id=ladder_id, teacher=request.user)
    ladder.delete()
    return redirect("grammar_lab")

from django.forms import modelformset_factory
from .models import GrammarLadder, LadderItem

@login_required
def grammar_ladder_detail(request, ladder_id):
    ladder = get_object_or_404(GrammarLadder, id=ladder_id, teacher=request.user)

    LadderItemFormSet = modelformset_factory(
        LadderItem,
        fields=("phrase", "is_correct"),
        extra=0,
        can_delete=True  # 🔥 Enables row deletion
    )

    if request.method == "POST":
        print("DEBUG POST:", request.POST)

        formset = LadderItemFormSet(request.POST, queryset=ladder.items.all())
        if formset.is_valid():
            print("✅ Formset is valid")
            print(f"Deleting {len(formset.deleted_forms)} rows")

            for form in formset.deleted_forms:
                print("Marked for deletion:", form.cleaned_data.get("phrase"))

            formset.save()
            messages.success(request, "Ladder items updated.")
            return redirect("grammar_ladder_detail", ladder_id=ladder_id)
        else:
            print("❌ Formset is invalid")
            print(formset.errors)

    else:
        formset = LadderItemFormSet(queryset=ladder.items.all())

    return render(request, "learning/grammar_ladder_detail.html", {
        "ladder": ladder,
        "formset": formset,
    })
