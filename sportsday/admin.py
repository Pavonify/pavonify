from django.contrib import admin

from . import models


@admin.register(models.Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("full_name", "grade", "house", "gender", "is_active")
    list_filter = ("grade", "house", "gender", "is_active")
    search_fields = ("first_name", "last_name", "external_id")


@admin.register(models.Meet)
class MeetAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "slug", "max_events_per_student", "is_locked")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(models.Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "meet",
        "event_type",
        "gender_limit",
        "grade_min",
        "grade_max",
        "capacity",
        "rounds",
        "schedule_block",
        "location",
        "is_locked",
    )
    list_filter = ("event_type", "meet", "gender_limit", "schedule_block")
    search_fields = ("name", "notes")


@admin.register(models.Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("event", "student", "heat", "lane_or_order", "status", "override_limits")
    list_filter = ("event__meet", "status", "heat")
    search_fields = ("event__name", "student__first_name", "student__last_name")


@admin.register(models.Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("entry", "round_no", "rank", "time_seconds", "distance_m", "count", "is_final")
    list_filter = ("round_no", "is_final", "entry__event__event_type")
    search_fields = ("entry__event__name", "entry__student__last_name")


@admin.register(models.ScoringRule)
class ScoringRuleAdmin(admin.ModelAdmin):
    list_display = ("meet", "scope", "per_house", "tie_method", "points_csv")
    list_filter = ("meet", "scope", "per_house")


@admin.register(models.AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("ts", "user", "action")
    list_filter = ("action",)
    search_fields = ("payload",)


@admin.register(models.House)
class HouseAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "color", "created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(models.SportsdayAccessConfig)
class SportsdayAccessConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "is_enabled", "cookie_name", "cookie_ttl_hours", "updated_at")


@admin.register(models.LeaderboardSnapshot)
class LeaderboardSnapshotAdmin(admin.ModelAdmin):
    list_display = ("meet", "scope", "created_at")
    list_filter = ("meet", "scope")
