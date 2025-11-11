"""URL configuration for the sportsday app."""
from django.urls import path

from . import views

app_name = "sportsday"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("meets/", views.meet_list, name="meet-list"),
    path("meets/new/", views.meet_create, name="meet-create"),
    path("meets/wizard-slug/", views.meet_slugify, name="meet-slugify"),
    path(
        "meets/wizard-scoring-preview/",
        views.meet_wizard_scoring_preview,
        name="meet-wizard-scoring-preview",
    ),
    path(
        "meets/wizard-event-preview/",
        views.meet_wizard_event_preview,
        name="meet-wizard-event-preview",
    ),
    path(
        "meets/wizard-template/<str:kind>/",
        views.meet_wizard_download_template,
        name="meet-wizard-template",
    ),
    path("meets/wizard-stage/", views.meet_wizard_stage, name="meet-wizard-stage"),
    path("meets/<slug:slug>/", views.meet_detail, name="meet-detail"),
    path("meets/<slug:slug>/schedule/", views.meet_schedule_fragment, name="meet-schedule-fragment"),
    path("meets/<slug:slug>/people/", views.meet_people_fragment, name="meet-people-fragment"),
    path("meets/<slug:slug>/lock/", views.meet_toggle_lock, name="meet-toggle-lock"),
    path("meets/<slug:slug>/events/generate/", views.events_generate, name="events-generate"),
    path("meets/<slug:slug>/entries/bulk/", views.entries_bulk, name="entries-bulk"),
    path("students/upload/", views.students_upload, name="students-upload"),
    path("students/", views.student_list, name="students"),
    path("students/<int:student_id>/edit/", views.student_edit, name="student-edit"),
    path("students/<int:student_id>/delete/", views.student_delete, name="student-delete"),
    path("students/table/", views.students_table_fragment, name="students-table-fragment"),
    path("teachers/upload/", views.teachers_upload, name="teachers-upload"),
    path("teachers/", views.teacher_list, name="teachers"),
    path("teachers/table/", views.teachers_table_fragment, name="teachers-table-fragment"),
    path("events/", views.event_list, name="events"),
    path("events/table/", views.events_table_fragment, name="events-table-fragment"),
    path("events/<int:pk>/", views.event_detail, name="event-detail"),
    path("events/<int:pk>/lock/", views.event_toggle_lock, name="event-toggle-lock"),
    path("events/<int:pk>/start-list/", views.event_start_list_fragment, name="event-start-list-fragment"),
    path("events/<int:pk>/start-list/add/", views.event_start_list_add, name="event-start-list-add"),
    path(
        "events/<int:pk>/start-list/remove/<int:entry_id>/",
        views.event_start_list_remove,
        name="event-start-list-remove",
    ),
    path("events/<int:pk>/start-list/reorder/", views.event_start_list_reorder, name="event-start-list-reorder"),
    path(
        "events/<int:pk>/start-list/autobalance/",
        views.event_start_list_autobalance,
        name="event-start-list-autobalance",
    ),
    path(
        "events/<int:pk>/start-list/autoseed/",
        views.event_start_list_autoseed,
        name="event-start-list-autoseed",
    ),
    path("events/<int:pk>/results/", views.event_results_fragment, name="event-results-fragment"),
    path("events/<int:pk>/printables/", views.event_printables_fragment, name="event-printables-fragment"),
    path("events/<int:pk>/printables/start-list/", views.event_start_list_printable, name="event-start-list-printable"),
    path("events/<int:pk>/printables/marshal-cards/", views.event_marshal_cards_printable, name="event-marshal-cards-printable"),
    path("events/<int:pk>/printables/medal-labels/", views.event_medal_labels_printable, name="event-medal-labels-printable"),
    path("events/<int:pk>/qr/", views.event_results_qr, name="event-results-qr"),
    path("leaderboards/", views.leaderboards, name="leaderboards"),
    path("leaderboards/panel/", views.leaderboards_panel_fragment, name="leaderboards-panel-fragment"),
    path("exports/students.csv", views.export_students_csv, name="export-students-csv"),
    path("exports/teachers.csv", views.export_teachers_csv, name="export-teachers-csv"),
    path("exports/startlists.csv", views.export_startlists_csv, name="export-startlists-csv"),
    path("exports/results.csv", views.export_results_csv, name="export-results-csv"),
    path("exports/leaderboard.csv", views.export_leaderboard_csv, name="export-leaderboard-csv"),
]
