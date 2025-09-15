from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.mail import mail_admins
from django.utils.timezone import now
from django.db.models import Count
from datetime import timedelta

from learning.models import VocabularyList, VocabularyWord


class Command(BaseCommand):
    """Flag suspicious user behaviour and purge abandoned lists."""

    help = "Flag users exceeding typical list/word counts and purge abandoned lists"

    MAX_LISTS_PER_USER = 100
    MAX_WORDS_PER_LIST = 1000
    MAX_DAILY_LIST_GROWTH = 20
    MAX_DAILY_WORD_GROWTH = 500
    ABANDONED_DAYS = 180

    def handle(self, *args, **options):
        self.flag_users()
        self.purge_abandoned_lists()

    def flag_users(self):
        User = get_user_model()
        day_ago = now() - timedelta(days=1)
        for user in User.objects.filter(is_active=True):
            lists = VocabularyList.objects.filter(teacher=user)
            list_count = lists.count()
            recent_list_count = lists.filter(created_at__gte=day_ago).count()
            recent_word_count = VocabularyWord.objects.filter(list__teacher=user, created_at__gte=day_ago).count()
            oversized = lists.annotate(word_count=Count("words")).filter(word_count__gt=self.MAX_WORDS_PER_LIST)

            reasons = []
            if list_count > self.MAX_LISTS_PER_USER:
                reasons.append(f"{list_count} lists created")
            if recent_list_count > self.MAX_DAILY_LIST_GROWTH:
                reasons.append(f"{recent_list_count} lists created today")
            if recent_word_count > self.MAX_DAILY_WORD_GROWTH:
                reasons.append(f"{recent_word_count} words created today")
            if oversized.exists():
                reasons.append("list exceeding word limit")

            if reasons:
                user.is_active = False
                user.save(update_fields=["is_active"])
                msg = f"User {user.username} suspended: {', '.join(reasons)}"
                mail_admins("User suspended", msg)
                self.stdout.write(msg)

    def purge_abandoned_lists(self):
        cutoff = now() - timedelta(days=self.ABANDONED_DAYS)
        abandoned = VocabularyList.objects.filter(updated_at__lt=cutoff, classes__isnull=True).distinct()
        count = abandoned.count()
        if count:
            abandoned.delete()
        self.stdout.write(f"Purged {count} abandoned lists")
