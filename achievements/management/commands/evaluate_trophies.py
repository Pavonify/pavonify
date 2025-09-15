from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from achievements.services.evaluator import evaluate_user_trophies


class Command(BaseCommand):
    help = "Evaluate trophies for all users"

    def handle(self, *args, **options):
        User = get_user_model()
        for user in User.objects.all():
            evaluate_user_trophies(user, {})
        self.stdout.write(self.style.SUCCESS("Evaluated trophies."))
