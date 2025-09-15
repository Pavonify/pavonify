from django.conf import settings
from django.db import models


class Trophy(models.Model):
    id = models.SlugField(primary_key=True, max_length=60)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=40)
    trigger_type = models.CharField(max_length=20)
    metric = models.CharField(max_length=80)
    comparator = models.CharField(max_length=10)
    threshold = models.JSONField()
    window = models.CharField(max_length=30)
    subject_scope = models.CharField(max_length=20, default="any")
    repeatable = models.BooleanField(default=False)
    cooldown = models.CharField(max_length=10, default="none")
    points = models.IntegerField(default=0)
    icon = models.CharField(max_length=30, default="trophy")
    rarity = models.CharField(max_length=12, default="common")
    description = models.TextField(default="")
    constraints = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


class TrophyUnlock(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trophy_unlocks",
    )
    trophy = models.ForeignKey(
        Trophy, on_delete=models.CASCADE, related_name="unlocks"
    )
    earned_at = models.DateTimeField(auto_now_add=True)
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("user", "trophy", "earned_at")
        indexes = [models.Index(fields=["user", "trophy", "earned_at"])]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.user} - {self.trophy}"
