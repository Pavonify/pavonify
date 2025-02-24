from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, get_user_model
from django.db.models import Sum
from .models import Progress, VocabularyWord, VocabularyList, User, Class, Student, School, Assignment, AssignmentProgress, Trophy, StudentTrophy, ReadingLabText
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
from django.http import HttpResponseForbidden, Http404
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

    # Fetch data
    vocab_lists = VocabularyList.objects.filter(teacher=request.user)
    classes = Class.objects.filter(teachers=request.user)  # Use 'teachers' field instead of 'teacher'
    students = Student.objects.filter(classes__in=classes).distinct()

    for class_instance in classes:
        # Annotate live and expired assignments for each class
        class_instance.live_assignments = Assignment.objects.filter(
            class_assigned=class_instance, deadline__gte=datetime.now()
        )
        class_instance.expired_assignments = Assignment.objects.filter(
            class_assigned=class_instance, deadline__lt=datetime.now()
        )

    # Debugging Output
    print("Classes:", classes)
    print("Students QuerySet:", students)
    for student in students:
        print(f"Student: {student.first_name} {student.last_name}, Classes: {student.classes.all()}")

    # Attach unattached classes
    for vocab_list in vocab_lists:
        vocab_list.unattached_classes = classes.exclude(
            id__in=vocab_list.classes.values_list("id", flat=True)
        )

    """ Renders teacher dashboard with the latest announcements """
    announcements_list = Announcement.objects.all()
    paginator = Paginator(announcements_list, 3)  # Show 3 posts per page

    page_number = request.GET.get("page")
    announcements = paginator.get_page(page_number)



    return render(request, "learning/teacher_dashboard.html", {
        "user": request.user,
        "vocab_lists": vocab_lists,
        "classes": classes,
        "students": students,
        "announcements": announcements,
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

    # Serialize words for JavaScript
    words = list(vocab_list.words.values('word', 'translation'))
    random.shuffle(words)  # Shuffle the words list to randomize

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

    # Fetch all words in the vocabulary list
    all_words = list(vocab_list.words.all())

    # Randomly sample 10 words or less if the list contains fewer than 10
    words = sample(all_words, min(len(all_words), 10))

    # Separate source and target words, shuffle targets for the match-up
    source_words = words[:]
    target_words = words[:]
    random.shuffle(target_words)

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

    # Randomly shuffle the words in the vocabulary list
    words = list(vocab_list.words.values('word', 'translation'))
    random.shuffle(words)

    return render(request, "learning/gap_fill_mode.html", {
        "vocab_list": vocab_list,
        "words": json.dumps(words),  # Serialize as JSON
    })


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

        # Get the reCAPTCHA response token
        recaptcha_response = request.POST.get("g-recaptcha-response")
        if not recaptcha_response:
            messages.error(request, "reCAPTCHA validation failed. Please try again.")
            return render(request, "learning/register_teacher.html", {"form": form})

        # Verify reCAPTCHA with Google
        recaptcha_data = {
            "secret": settings.RECAPTCHA_SECRET_KEY,
            "response": recaptcha_response,
        }
        r = requests.post("https://www.google.com/recaptcha/api/siteverify", data=recaptcha_data)
        result = r.json()

        if not result.get("success") or result.get("score", 0) < 0.5:
            messages.error(request, "Failed reCAPTCHA verification. Please try again.")
            return render(request, "learning/register_teacher.html", {"form": form})
        
        # Check if form is valid
        if form.is_valid():
            user = form.save(commit=False)  # Save user instance without committing
            
            # Assign default school if none is provided
            user.school, _ = School.objects.get_or_create(name="Default School")

            user.save()  # Save user with assigned school
            login(request, user)  # Auto-login new teacher
            
            messages.success(request, "Your account has been created successfully!")
            return redirect("teacher_dashboard")

        else:
            messages.error(request, "There were errors in the form. Please correct them.")
            print(form.errors)  # 🔴 Debugging: Print form errors to the terminal

    else:
        form = TeacherRegistrationForm()

    return render(request, "learning/register_teacher.html", {
        "form": form,
        "recaptcha_site_key": settings.RECAPTCHA_SITE_KEY
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

        if student_id and points:
            student = Student.objects.get(id=student_id)
            student.total_points += points
            student.weekly_points += points
            student.monthly_points += points
            student.save()

            new_trophies = check_and_award_trophies(student)

            return JsonResponse({
                "success": True, 
                "total_points": student.total_points,
                "new_trophies": new_trophies
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

    # Fetch all words for the vocabulary list
    all_words = list(vocab_list.words.values('word', 'translation'))

    # Randomly select up to 30 words
    selected_words = sample(all_words, min(30, len(all_words)))

    # Shuffle the selected words for display order
    shuffle(selected_words)

    return render(request, "learning/destroy_the_wall.html", {
        "vocab_list": vocab_list,
        "words_json": json.dumps(selected_words),  # Serialize for JavaScript
        "student": student,
    })


@student_login_required
def unscramble_the_word(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    words = list(vocab_list.words.values('word', 'translation'))
    shuffle(words)  # Randomize the order of the words
    return render(request, "learning/unscramble_the_word.html", {
        "vocab_list": vocab_list,
        "words_json": json.dumps(words, cls=DjangoJSONEncoder),
        "student": request.user,  # For the stats
    })


@login_required
def create_assignment(request, class_id):
    class_assigned = get_object_or_404(Class, id=class_id)
    vocab_lists = VocabularyList.objects.all()

    if request.method == "POST":
        name = request.POST.get("name")
        vocab_list_id = request.POST.get("vocab_list")
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

        # ✅ NEW MODES ✅
        include_listening_dictation = "include_listening_dictation" in request.POST
        points_per_listening_dictation = int(request.POST.get("points_per_listening_dictation", 1)) if include_listening_dictation else 0

        include_listening_translation = "include_listening_translation" in request.POST
        points_per_listening_translation = int(request.POST.get("points_per_listening_translation", 1)) if include_listening_translation else 0

        vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)

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
def assignment_analytics(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    progress_list = AssignmentProgress.objects.filter(assignment=assignment)
    return render(request, "learning/assignment_analytics.html", {
        "assignment": assignment,
        "progress_list": progress_list,
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

    assignment = get_object_or_404(Assignment, id=assignment_id)
    student = get_object_or_404(Student, id=student_id)

    # Calculate assignment progress
    total_points = assignment.target_points  # Ensure the `target_points` exists in your Assignment model
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



@student_login_required
def gap_fill_mode_assignment(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    vocab_list = assignment.vocab_list
    vocab_words = list(VocabularyWord.objects.filter(list=vocab_list))  # ✅ Correct model used

    # Convert words into a JSON-safe format
    words_list = [{"word": w.word, "translation": w.translation} for w in vocab_words]

    print("DEBUG: Words List:", words_list)  # ✅ Debug to see if words exist

    # Fetch assignment progress separately for correct tracking
    assignment_progress = AssignmentProgress.objects.filter(assignment=assignment, student=student).first()
    current_points = assignment_progress.points_earned if assignment_progress else 0

    return render(request, "learning/assignment_modes/gap_fill_mode_assignment.html", {
        "assignment": assignment,
        "words_json": json.dumps(words_list),  # ✅ Pass JSON-encoded words
        "student": student,
        "total_points": assignment.target_points,
        "current_points": current_points,
        "source_language": vocab_list.source_language,
        "target_language": vocab_list.target_language,
    })


def destroy_wall_mode_assignment(request, assignment_id):
    # Get the assignment
    assignment = get_object_or_404(Assignment, id=assignment_id)

    # Ensure the student is logged in
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    # Fetch the associated vocabulary list
    vocab_list = assignment.vocab_list

    # Get all words from the vocabulary list
    all_words = list(vocab_list.words.values('word', 'translation'))

    # Randomly select up to 30 words
    selected_words = sample(all_words, min(30, len(all_words)))

    # Shuffle words for display order
    shuffle(selected_words)

    return render(request, "learning/assignment_modes/destroy_the_wall_assignment.html", {
        "assignment": assignment,
        "words_json": json.dumps(selected_words),  # Serialize words for JavaScript
        "student": student,
    })

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
    all_words = list(vocab_list.words.all())

    # Randomly sample 10 words or less if the list contains fewer than 10
    words = sample(all_words, min(len(all_words), 10))

    # Separate source and target words, shuffle targets for the match-up
    source_words = words[:]
    target_words = words[:]
    random.shuffle(target_words)

    return render(request, "learning/assignment_modes/match_up_mode_assignment.html", {
        "vocab_list": vocab_list,
        "source_words": source_words,
        "target_words": target_words,
        "student": student,
        "assignment": assignment,  # Pass the assignment to the template
    })

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

    # Get all words from the vocabulary list
    words = list(vocab_list.words.values('word', 'translation'))

    # Shuffle words for display order
    shuffle(words)

    return render(request, "learning/assignment_modes/unscramble_the_word_assignment.html", {
        "assignment": assignment,
        "words_json": json.dumps(words),  # Serialize words for JavaScript
        "student": student,
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

    words = list(vocab_list.words.values('word', 'translation'))
    random.shuffle(words)  

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
                "price_data": {
                    "currency": "gbp",
                    "product_data": {
                        "name": "Pavonify Premium",
                    },
                    "unit_amount": 299,  # 299 pence = £2.99
                    "recurring": {
                        "interval": "month",
                    },
                },
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


    # Fetch words and randomize them **server-side**
    words_queryset = list(vocab_list.words.all())
    random.shuffle(words_queryset)
    words = [{'word': word.word, 'translation': word.translation} for word in words_queryset]

    words_json = json.dumps(words)

    return render(request, 'learning/listening_dictation.html', {
        'vocab_list': vocab_list,
        'words_json': words_json,
        'target_language': vocab_list.target_language,
        'student': student,  
        'weekly_points': student.weekly_points,  # ✅ Pass correct weekly points
        'total_points': student.total_points,  # ✅ Pass correct total points
    })

@student_login_required
def listening_translation_view(request, vocab_list_id):
    vocab_list = get_object_or_404(VocabularyList, id=vocab_list_id)
    student = get_object_or_404(Student, id=request.session.get("student_id"))


    # Fetch words and randomize them **server-side**
    words_queryset = list(vocab_list.words.all())
    random.shuffle(words_queryset)
    words = [{'word': word.word, 'translation': word.translation} for word in words_queryset]

    words_json = json.dumps(words)

    return render(request, 'learning/listening_translation.html', {
        'vocab_list': vocab_list,
        'words_json': words_json,
        'target_language': vocab_list.target_language,
        'student': student,  
        'weekly_points': student.weekly_points,  # ✅ Pass correct weekly points
        'total_points': student.total_points,  # ✅ Pass correct total points
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

    # Ensure student has access to this assignment
    if not student.classes.filter(vocabulary_lists=vocab_list).exists():
        return HttpResponseForbidden("You do not have access to this vocabulary list.")

    # Get all words in the vocabulary list
    words = list(vocab_list.words.values('word', 'translation'))

    return render(request, "learning/assignment_modes/listening_dictation_assignment.html", {
        "assignment": assignment,
        "vocab_list": vocab_list,
        "words_json": json.dumps(words),  # Serialize for JavaScript
        "target_language": vocab_list.target_language,
    })


@student_login_required
def listening_translation_assignment(request, assignment_id):
    # Get the assignment object
    assignment = get_object_or_404(Assignment, id=assignment_id)
    
    # Get the student
    student = get_object_or_404(Student, id=request.session.get("student_id"))

    # Get the vocabulary list assigned to this assignment
    vocab_list = assignment.vocab_list  # ✅ FIXED: Now vocab_list is defined

    # Fetch words and randomize them **server-side**
    words_queryset = list(VocabularyWord.objects.filter(list=vocab_list).values("word", "translation"))

    random.shuffle(words_queryset)  # ✅ Shuffle words

    words_json = json.dumps(words_queryset)  # Convert to JSON for frontend

    return render(request, 'learning/assignment_modes/listening_translation_assignment.html', {  # ✅ FIXED TEMPLATE NAME
        'assignment': assignment,  # ✅ Pass assignment
        'vocab_list': vocab_list,  # ✅ Pass vocabulary list
        'words_json': words_json,  # ✅ JSON of words
        'target_language': vocab_list.target_language,  # ✅ Ensure vocab_list has this field
        'student': student,  # ✅ Pass student object
        'weekly_points': student.weekly_points,  # ✅ Pass correct weekly points
        'total_points': student.total_points,  # ✅ Pass correct total points
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


# Exam board topics (Replace this with real topics from research)
EXAM_BOARD_TOPICS = {
    "GCSE Edexcel": ["Travel & Tourism", "School Life", "Technology & Media", "Healthy Living"],
    "GCSE AQA": ["Family & Relationships", "Hobbies & Interests", "Environment", "Social Issues"],
    "iGCSE Cambridge": ["Work & Jobs", "Global Issues", "Food & Drink", "Festivals"],
    "IB DP": ["Identity", "Experiences", "Human Ingenuity", "Social Organization", "Sharing the Planet"],
    "A Level Edexcel": ["Politics", "Literature & Film", "History & Culture", "Contemporary Issues"],
    "A Level AQA": ["Art & Architecture", "Multiculturalism", "Regional Identity", "Scientific Advances"]
}

@login_required
def reading_lab(request):
    teacher = request.user
    vocabulary_lists = VocabularyList.objects.filter(teacher=teacher)

    if request.method == "POST":
        vocab_list_id = request.POST.get("vocab_list")
        selected_words = request.POST.getlist("selected_words")
        exam_board = request.POST.get("exam_board")
        topic = request.POST.get("topic")
        level = request.POST.get("level")
        word_count = int(request.POST.get("word_count"))

        # Ensure the teacher has enough AI credits
        if teacher.ai_credits <= 0:
            messages.error(request, "You have run out of AI credits. Upgrade to get more!")
            return redirect("reading_lab")

        # Fetch the selected vocabulary list
        try:
            vocab_list = VocabularyList.objects.get(id=vocab_list_id, teacher=teacher)
        except VocabularyList.DoesNotExist:
            messages.error(request, "Invalid vocabulary list.")
            return redirect("reading_lab")

        # Get selected vocabulary words
        words = VocabularyWord.objects.filter(id__in=selected_words)

        # Convert word list into a formatted prompt for Gemini AI
        vocab_prompt = ", ".join([f"{word.word} ({word.translation})" for word in words])

        # AI request to Gemini (Free tier)
        ai_prompt = f"""
        Generate a {word_count}-word reading text for {level} level students.
        The topic is "{topic}" based on the {exam_board} syllabus.
        Include the following vocabulary: {vocab_prompt}.
        Write in {vocab_list.source_language} with a parallel translation in {vocab_list.target_language}.
        """

        # Call Gemini AI API
        headers = {"Authorization": f"Bearer {settings.GEMINI_API_KEY}"}
        response = requests.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateText",
                                 json={"prompt": ai_prompt}, headers=headers)

        ai_data = response.json()
        if "error" in ai_data:
            messages.error(request, "Error generating text. Please try again.")
            return redirect("reading_lab")

        generated_text_source = ai_data["text"]["source"]
        generated_text_target = ai_data["text"]["target"]

        # Save the AI-generated text
        reading_lab_entry = ReadingLabText.objects.create(
            teacher=teacher,
            vocabulary_list=vocab_list,
            exam_board=exam_board,
            topic=topic,
            level=level,
            word_count=word_count,
            generated_text_source=generated_text_source,
            generated_text_target=generated_text_target
        )
        reading_lab_entry.selected_words.set(words)

        # Deduct 1 AI credit
        teacher.ai_credits -= 1
        teacher.save()

        messages.success(request, "Parallel text successfully generated!")
        return redirect("reading_lab")

    return render(request, "learning/reading_lab.html", {
        "vocabulary_lists": vocabulary_lists,
        "exam_board_topics": EXAM_BOARD_TOPICS,
        "levels": ["A1", "A2", "B1", "B2", "C1", "C2"]
    })