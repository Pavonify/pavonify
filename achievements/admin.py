from django.contrib import admin
from .models import Trophy, TrophyUnlock


@admin.register(Trophy)
class TrophyAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "category", "rarity", "points", "repeatable")
    search_fields = ("id", "name", "category")
    list_filter = ("category", "rarity", "repeatable")


@admin.register(TrophyUnlock)
class TrophyUnlockAdmin(admin.ModelAdmin):
    list_display = ("user", "trophy", "earned_at")
    search_fields = ("user__username", "trophy__name")
    list_filter = ("trophy", "earned_at")
