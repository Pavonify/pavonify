import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from learning.models import Student, Word, School
from srs.models import StudentWordProgress
from srs.scheduler import INTERVALS


class Command(BaseCommand):
    help = "Seed SRS demo data"

    def handle(self, *args, **options):
        school, _ = School.objects.get_or_create(id=1, defaults={"name": "Demo School"})
        student, _ = Student.objects.get_or_create(
            username="demo_student",
            defaults={
                "first_name": "Demo",
                "last_name": "Student",
                "year_group": 1,
                "date_of_birth": timezone.now().date(),
                "password": "demo",
                "school": school,
            },
        )
        for i in range(50):
            word, _ = Word.objects.get_or_create(source=f"word{i}", target=f"translation{i}")
            box = i % len(INTERVALS)
            due = timezone.now() + timedelta(hours=INTERVALS[box]["hours"])
            StudentWordProgress.objects.get_or_create(
                student=student,
                word=word,
                defaults={
                    "box_index": box,
                    "status": "learning" if box < 2 else "reviewing",
                    "next_due_at": due,
                },
            )
        self.stdout.write(self.style.SUCCESS("Seeded demo data."))
