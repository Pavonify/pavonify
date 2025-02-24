"""
URL configuration for lang_platform project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path
from learning import views
from django.contrib.auth import views as auth_views
from django_countries.fields import CountryField 
from django.contrib import admin
from django.urls import path
from learning import views  # Import views from the learning app
from learning.views import flashcard_mode
from django.contrib.auth.decorators import login_required
from learning.views import update_assignment_points, teacher_upgrade, create_checkout_session, worksheet_lab_view, custom_404_view, teacher_account_settings
from django.conf.urls import handler404
from learning.webhooks import stripe_webhook
handler404 = custom_404_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('teacher-dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('register-teacher/', views.register_teacher, name='register_teacher'),
    path('vocabulary/', views.teacher_dashboard, name='vocabulary_list'),  # Previously "vocabulary_list"
    path('leaderboard/', views.leaderboard, name='leaderboard'),
    path('add-vocabulary-list/', views.add_vocabulary_list, name='add_vocabulary_list'),
    path('delete-vocabulary-list/<int:pk>/', views.delete_vocabulary_list, name='delete_vocabulary_list'),
    path('delete-word/<int:word_id>/', views.delete_vocabulary_word, name='delete_vocabulary_word'),
    path('bulk-delete-words/<int:list_id>/', views.bulk_delete_words, name='bulk_delete_words'),
    path('edit-list/<int:list_id>/', views.edit_vocabulary_list_details, name='edit_vocabulary_list_details'),
    path('add-words/<int:list_id>/', views.add_words_to_list, name='add_words_to_list'),
    path('edit-words/<int:list_id>/', views.edit_vocabulary_words, name='edit_vocabulary_words'),
    path('view-words/<int:list_id>/', views.view_vocabulary_words, name='view_vocabulary_words'),
    path('', views.landing_page, name='landing_page'),  # Landing page
    path('logout/', views.teacher_logout, name='teacher_logout'),  # Logout
    path('student-logout/', views.student_logout, name='student_logout'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),  # Teacher login
    path("create-class/", views.create_class, name="create_class"),
    path("edit-class/<uuid:class_id>/", views.edit_class, name="edit_class"),
    path("add-students/<uuid:class_id>/", views.add_students, name="add_students"),
    path("edit-student/<uuid:student_id>/", views.edit_student, name="edit_student"),
    path("delete-student/<uuid:student_id>/", views.delete_student, name="delete_student"),
    path('delete-class/<uuid:class_id>/', views.delete_class, name='delete_class'),
    path("share-class/<uuid:class_id>/", views.share_class, name="share_class"),
    path(
        'remove-teacher/<uuid:class_id>/<int:teacher_id>/',
        views.remove_teacher_from_class,
        name='remove_teacher_from_class'
    ),
    path("student-login/", views.student_login, name="student_login"),
    path("student-dashboard/", views.student_dashboard, name="student_dashboard"),
    path('attach-vocabulary/<uuid:class_id>/', views.attach_vocab_list, name='attach_vocabulary'),
    path('view-vocabulary/<int:vocab_list_id>/', views.view_vocabulary, name='view_vocabulary'),
    path('attach-vocab-list/<int:vocab_list_id>/', views.attach_vocab_list, name='attach_vocab_list'),
    path('view-attached-vocab/<uuid:class_id>/', views.view_attached_vocab, name='view_attached_vocab'),
    path('flashcard-mode/<int:vocab_list_id>/', views.flashcard_mode, name='flashcard_mode'),
    path('match-up-mode/<int:vocab_list_id>/', views.match_up_mode, name='match_up_mode'),
    path('gap-fill-mode/<int:vocab_list_id>/', views.gap_fill_mode, name='gap_fill_mode'),
    path("lead-teacher-dashboard/", views.lead_teacher_dashboard, name="lead_teacher_dashboard"),
    path("lead-teacher-login/", views.lead_teacher_login, name="lead_teacher_login"),
    path("school-signup/", views.school_signup, name="school_signup"),  # Placeholder for future payment page
    path("update-points/", views.update_points, name="update_points"),
    path('destroy-the-wall/<int:vocab_list_id>/', views.destroy_the_wall, name='destroy_the_wall'),
    path('unscramble-the-word/<int:vocab_list_id>/', views.unscramble_the_word, name='unscramble_the_word'),
    path('create-assignment/<uuid:class_id>/', views.create_assignment, name='create_assignment'),
    path('assignment-analytics/<int:assignment_id>/', views.assignment_analytics, name='assignment_analytics'),
    path('delete-assignment/<int:assignment_id>/', views.delete_assignment, name='delete_assignment'),
    path('assignment/flashcard/<int:assignment_id>/', views.flashcard_mode_assignment, name='flashcard_mode_assignment'),
    path('assignment/destroy-the-wall/<int:assignment_id>/', views.destroy_wall_mode_assignment, name='destroy_wall_mode_assignment'),
    path('assignment/unscramble/<int:assignment_id>/', views.unscramble_the_word_assignment, name='unscramble_the_word_assignment'), 
    path("assignment/<int:assignment_id>/", views.assignment_page, name="assignment_page"),
    path('assignment/match-up/<int:assignment_id>/', views.match_up_mode_assignment, name='match_up_mode_assignment'),
    path('assignment/gap-fill/<int:assignment_id>/', views.gap_fill_mode_assignment, name='gap_fill_mode_assignment'),
    path("assignment/listening-dictation/<int:assignment_id>/", views.listening_dictation_assignment, name="listening_dictation_assignment"),
    path("assignment/listening-translation/<int:assignment_id>/", views.listening_translation_assignment, name="listening_translation_assignment"),
    path('update-assignment-points/', update_assignment_points, name='update_assignment_points'),
    path("create-checkout-session/", create_checkout_session, name="create_checkout_session"),
    path('worksheet_lab/', worksheet_lab_view, name='worksheet_lab'),
    path('listening-dictation/<int:vocab_list_id>/', views.listening_dictation_view, name='listening_dictation'),
    path('listening-translation/<int:vocab_list_id>/', views.listening_translation_view, name='listening_translation'),
    path("teacher/account/", teacher_account_settings, name="teacher_account"),
    path("payment-success/", views.payment_success, name="payment_success"),
    path("stripe/webhook/", stripe_webhook, name="stripe_webhook"),
    path("teacher-cancel-subscription/", views.teacher_cancel_subscription, name="teacher_cancel_subscription"),
    path("reading-lab", views.reading_lab, name="reading_lab"),
    path("reading-lab/<int:text_id>/", views.reading_lab_display, name="reading_lab_display"),
    path("get-words/", views.get_words, name="get_words"),

]



urlpatterns += [
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register-teacher/', views.register_teacher, name='register_teacher'),
    path("update-points/", views.update_points, name="update_points"),
    path('student-logout/', views.student_logout, name='student_logout'),
    path('teacher-logout/', views.teacher_logout, name='teacher_logout'),  # Logout

]