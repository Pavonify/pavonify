from django.urls import path

from . import views

app_name = "sportsday"

urlpatterns = [
    path("access/", views.AccessView.as_view(), name="access"),
    path("", views.MeetListView.as_view(), name="meet_list"),
    path("create/", views.MeetCreateView.as_view(), name="meet_create"),
    path("<slug:slug>/", views.DashboardView.as_view(), name="dashboard"),
    path("<slug:slug>/edit/", views.MeetUpdateView.as_view(), name="meet_edit"),
    path("<slug:slug>/students/", views.StudentListView.as_view(), name="students"),
    path("<slug:slug>/teachers/", views.TeacherListView.as_view(), name="teachers"),
    path("<slug:slug>/students/upload/", views.StudentUploadView.as_view(), name="students_upload"),
    path("<slug:slug>/leaderboard/", views.LeaderboardView.as_view(), name="leaderboard"),
    path("api/<slug:slug>/students", views.StudentsAPI.as_view(), name="api_students"),
    path("api/<slug:slug>/events", views.EventsAPI.as_view(), name="api_events"),
    path("api/<slug:slug>/leaderboard", views.LeaderboardAPI.as_view(), name="api_leaderboard"),
]
