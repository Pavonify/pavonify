"""Admin registrations for the sportsday application."""
from django.contrib import admin

from . import models


@admin.register(models.Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "grade", "house", "gender", "is_active")
    list_filter = ("grade", "house", "gender", "is_active")
    search_fields = ("first_name", "last_name", "external_id")


@admin.register(models.Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email")
    search_fields = ("first_name", "last_name", "email", "external_id")


@admin.register(models.Meet)
class MeetAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "slug", "location", "max_events_per_student", "is_locked")
    list_filter = ("date", "is_locked")
    search_fields = ("name", "slug", "location")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(models.SportType)
class SportTypeAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "key",
        "archetype",
        "default_unit",
        "default_capacity",
        "default_attempts",
        "supports_heats",
        "supports_finals",
    )
    list_filter = ("archetype", "supports_heats", "supports_finals")
    search_fields = ("label", "key")


@admin.register(models.Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "meet",
        "sport_type",
        "grade_min",
        "grade_max",
        "gender_limit",
        "capacity",
        "attempts",
        "rounds_total",
        "schedule_dt",
        "is_locked",
    )
    list_filter = ("meet", "sport_type", "gender_limit", "is_locked")
    search_fields = ("name", "notes")
    filter_horizontal = ("assigned_teachers",)


@admin.register(models.Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("event", "student", "round_no", "heat", "lane_or_order", "status")
    list_filter = ("event__meet", "round_no", "status")
    search_fields = ("event__name", "student__first_name", "student__last_name")


@admin.register(models.Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("entry", "attempt_no", "time_seconds", "distance_m", "count", "valid")
    list_filter = ("attempt_no", "valid")


@admin.register(models.Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("entry", "best_value", "rank", "finalized")
    list_filter = ("finalized",)


@admin.register(models.ScoringRule)
class ScoringRuleAdmin(admin.ModelAdmin):
    list_display = ("meet", "points_csv", "participation_point", "tie_method")
    list_filter = ("meet", "tie_method")


@admin.register(models.AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("ts", "action")
    list_filter = ("action", "ts")
    search_fields = ("action",)
